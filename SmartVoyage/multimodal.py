from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from SmartVoyage.travel_knowledge import LANDMARK_ALIASES, TRAVEL_PROFILES


SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class InvalidImageError(ValueError):
    pass


class ImageTooLargeError(ValueError):
    pass


class VisionUnavailableError(RuntimeError):
    pass


class VisionObservation(BaseModel):
    landmark: str = ""
    city: str = ""
    scene: str = ""
    ocr_text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class GraphFact(BaseModel):
    subject: str
    relation: str
    object: str


class MultimodalTrace(BaseModel):
    node: str
    label: str
    status: str
    summary: str


class MultimodalResult(BaseModel):
    vision: VisionObservation
    graph_facts: list[GraphFact]
    itinerary: list[str]
    trace: list[MultimodalTrace]


class VisionAnalyzer(Protocol):
    def analyze(self, image_data_url: str) -> VisionObservation | dict: ...


class GraphLookup(Protocol):
    backend: str
    def facts_for(self, landmark: str) -> list[GraphFact]: ...


TRAVEL_GRAPH: dict[str, list[GraphFact]] = {
    name: [
        GraphFact(subject=profile["city"], relation="包含", object=name),
        GraphFact(subject=name, relation="附近", object=profile["nearby"]),
        GraphFact(subject=profile["transport"], relation="可到达", object=name),
        GraphFact(subject=name, relation="特色", object=profile["feature"]),
    ]
    for name, profile in TRAVEL_PROFILES.items()
}


class StaticGraphLookup:
    backend = "static"

    def facts_for(self, landmark: str) -> list[GraphFact]:
        return list(TRAVEL_GRAPH.get(landmark, []))


def _decode_image_data_url(image_data_url: str) -> bytes:
    match = re.fullmatch(
        r"data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\r\n]+)",
        image_data_url,
        flags=re.IGNORECASE,
    )
    if not match:
        raise InvalidImageError("图片数据格式无效")
    mime, encoded = match.groups()
    mime = mime.lower()
    if mime not in SUPPORTED_MIME:
        raise InvalidImageError("仅支持 JPG、PNG 和 WebP")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidImageError("图片 Base64 数据无效") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise ImageTooLargeError("图片不能超过 5 MiB")
    if not payload:
        raise InvalidImageError("图片内容为空")
    return payload


def _build_itinerary(vision: VisionObservation, facts: list[GraphFact]) -> list[str]:
    if not facts:
        subject = vision.landmark or vision.scene or "该地点"
        return [f"已识别为“{subject}”，但未匹配到图谱实体；建议确认地点后再生成路线。"]
    transport = next((fact.subject for fact in facts if fact.relation == "可到达"), "公共交通")
    nearby = next((fact.object for fact in facts if fact.relation == "附近"), "周边景点")
    landmark = vision.landmark
    return [
        f"先乘坐{transport}前往{landmark}，预留约 2 小时游览。",
        f"随后前往附近的{nearby}，形成同区域半日路线。",
    ]


def _normalize_known_landmark(vision: VisionObservation) -> VisionObservation:
    if vision.landmark.strip() in TRAVEL_GRAPH:
        return vision
    evidence = " ".join(
        [vision.landmark, vision.city, vision.scene, vision.ocr_text]
    ).replace(" ", "")
    match = next((name for name in TRAVEL_GRAPH if name in evidence), "")
    if not match:
        match = next(
            (
                canonical
                for alias, canonical in sorted(
                    LANDMARK_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
                )
                if alias.replace(" ", "") in evidence
            ),
            "",
        )
    return vision.model_copy(update={"landmark": match}) if match else vision


def analyze_travel_image(
    image_data_url: str,
    analyzer: VisionAnalyzer,
    graph_lookup: GraphLookup | None = None,
) -> MultimodalResult:
    _decode_image_data_url(image_data_url)
    try:
        raw = analyzer.analyze(image_data_url)
        vision = raw if isinstance(raw, VisionObservation) else VisionObservation.model_validate(raw)
        vision = _normalize_known_landmark(vision)
    except Exception as exc:
        raise VisionUnavailableError("视觉模型暂时不可用") from exc

    facts = (graph_lookup or StaticGraphLookup()).facts_for(vision.landmark.strip())
    itinerary = _build_itinerary(vision, facts)
    return MultimodalResult(
        vision=vision,
        graph_facts=facts,
        itinerary=itinerary,
        trace=[
            MultimodalTrace(
                node="vision",
                label="VLM 视觉理解",
                status="completed",
                summary=f"识别地点：{vision.landmark or '未知'}；场景：{vision.scene or '未分类'}",
            ),
            MultimodalTrace(
                node="graph",
                label="知识图谱补全",
                status="completed" if facts else "skipped",
                summary=f"命中 {len(facts)} 条可审查关系" if facts else "未匹配到图谱实体",
            ),
            MultimodalTrace(
                node="itinerary",
                label="路线生成",
                status="completed",
                summary=f"生成 {len(itinerary)} 个行程步骤",
            ),
        ],
    )


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    return json.loads(candidate)


@dataclass
class DashScopeVisionAnalyzer:
    api_key: str
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-vl-plus"

    @classmethod
    def from_environment(cls) -> "DashScopeVisionAnalyzer":
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise VisionUnavailableError("DASHSCOPE_API_KEY 未配置")
        return cls(
            api_key=api_key,
            base_url=os.getenv("DASHSCOPE_BASE_URL", cls.base_url),
            model=os.getenv("SMARTVOYAGE_VLM_MODEL", cls.model),
        )

    def analyze(self, image_data_url: str) -> dict:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        completion = client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {
                            "type": "text",
                            "text": (
                                "识别这张旅行图片。只输出 JSON："
                                '{"landmark":"地点名或空字符串","city":"城市或空字符串",'
                                '"scene":"场景类型","ocr_text":"可见文字或空字符串",'
                                '"confidence":0到1之间的数字}。不要输出额外说明。'
                            ),
                        },
                    ],
                }
            ],
        )
        content = completion.choices[0].message.content or "{}"
        return _extract_json(content)
