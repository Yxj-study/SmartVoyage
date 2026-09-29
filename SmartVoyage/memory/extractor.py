from __future__ import annotations

from pydantic import BaseModel, Field

from SmartVoyage.memory.models import PreferenceCandidate
from SmartVoyage.memory.policy import validate_candidate


class PreferenceExtraction(BaseModel):
    candidates: list[PreferenceCandidate] = Field(default_factory=list)


_STABLE_MARKERS = ("记住", "以后", "通常", "总是", "默认", "偏好", "喜欢", "不喜欢")
_TEMPORARY_MARKERS = ("这次", "本次", "今天", "明天", "这趟", "当前行程")
_DELETE_MARKERS = ("忘掉", "删除", "清除", "不要再记住", "不再记住")


def create_llm_preference_extractor(llm):
    runnable = llm.with_structured_output(PreferenceExtraction)

    def extract(
        _user_id: str,
        _session_id: str,
        query: str,
    ) -> list[PreferenceCandidate]:
        prompt = f"""
你负责从旅行对话中提取长期用户偏好，不负责回答问题。
只允许字段：preferred_transport、max_ticket_budget、preferred_seat_class、
preferred_cabin_class、preferred_departure_period、preferred_hotel_level、
preferred_attraction_types。
只有“以后、通常、默认、偏好、喜欢、请记住”等稳定表达使用 stable。
“这次、本次、今天、明天、这趟”等仅当前行程有效的条件必须使用 temporary。
“忘掉、删除、清除、不再记住”使用 delete。没有偏好时返回空 candidates。
用户输入：{query}
""".strip()
        extraction = runnable.invoke(prompt)
        has_stable_marker = any(marker in query for marker in _STABLE_MARKERS)
        has_temporary_marker = any(marker in query for marker in _TEMPORARY_MARKERS)
        has_delete_marker = any(marker in query for marker in _DELETE_MARKERS)

        valid_candidates = []
        for candidate in extraction.candidates:
            updates = {"source_text": query}
            if has_delete_marker:
                updates.update({"operation": "delete", "scope": "stable"})
            elif has_temporary_marker and not has_stable_marker:
                updates["scope"] = "temporary"
            elif has_stable_marker:
                updates["scope"] = "stable"
            else:
                updates["scope"] = "temporary"
            normalized = candidate.model_copy(update=updates, deep=True)
            try:
                valid_candidates.append(validate_candidate(normalized))
            except ValueError:
                continue
        return valid_candidates

    return extract
