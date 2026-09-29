import uuid
import json
import re
from typing import Any

from python_a2a import A2AClient, Message, MessageRole, Task, TextContent

from SmartVoyage.coordinator.schemas import (
    TicketCandidate,
    TicketCandidateList,
    WeatherResult,
)


class AgentResponseError(RuntimeError):
    """Raised when an A2A task contains no usable text."""


class ResultNormalizationError(RuntimeError):
    """Raised when an Agent response cannot be normalized after retry."""


class LazyAgentNetwork:
    """Register A2A endpoints without contacting them during UI startup."""

    def __init__(self, urls: dict[str, str], timeout: int = 5):
        self.agent_urls = dict(urls)
        self.agents = {name: None for name in urls}
        self._clients = {}
        self._timeout = timeout

    def get_agent(self, name: str):
        if name not in self.agent_urls:
            raise KeyError(f"未知 Agent: {name}")
        if name not in self._clients:
            self._clients[name] = A2AClient(
                self.agent_urls[name], timeout=self._timeout
            )
            self.agents[name] = self._clients[name]
        return self._clients[name]

    def get_agent_card(self, name: str):
        return self.get_agent(name).get_agent_card()


def _parse_amap_weather_sentence(text: str) -> WeatherResult | None:
    if "天气预报" not in text or "白天" not in text:
        return None

    city_match = re.search(r"(?:今天|明天|后天)?(.+?)(?:市)?天气预报", text)
    weather_match = re.search(r"白天([^，。]+)", text)
    if not city_match or not weather_match:
        return None

    city = city_match.group(1).removesuffix("市")
    weather = weather_match.group(1)
    wind_match = re.search(r"风力(\d+)(?:-(\d+))?级", text)
    maximum_match = re.search(r"最高温度(-?\d+)", text)
    minimum_match = re.search(r"最低温度(-?\d+)", text)
    wind_scale = None
    if wind_match:
        wind_scale = max(
            int(value) for value in wind_match.groups() if value is not None
        )
    adverse_terms = ("雨", "雪", "雷", "冰雹", "沙尘", "台风", "暴")
    precipitation = 1 if any(term in weather for term in adverse_terms) else 0
    return WeatherResult(
        city=city,
        weather=weather,
        wind_scale=wind_scale,
        precipitation=precipitation,
        temperature_max=int(maximum_match.group(1)) if maximum_match else None,
        temperature_min=int(minimum_match.group(1)) if minimum_match else None,
    )


def _parse_ticket_json(text: str) -> list[TicketCandidate] | None:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("status") == "no_data":
        return []
    rows = payload.get("data")
    if payload.get("status") != "success" or not isinstance(rows, list):
        return None

    candidates: list[TicketCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("flight_number"):
            ticket_type = "flight"
            number = row["flight_number"]
            seat_class = row.get("cabin_type", "")
        elif row.get("train_number"):
            ticket_type = "train"
            number = row["train_number"]
            seat_class = row.get("seat_type", "")
        elif row.get("artist"):
            ticket_type = "concert"
            number = row["artist"]
            seat_class = row.get("ticket_type", "")
        else:
            continue

        departure = row.get("departure_city") or row.get("city") or ""
        destination = row.get("arrival_city") or row.get("venue") or departure
        departure_time = row.get("departure_time") or row.get("start_time")
        if not departure_time:
            continue
        candidates.append(
            TicketCandidate(
                ticket_type=ticket_type,
                departure=departure,
                destination=destination,
                departure_time=departure_time,
                arrival_time=row.get("arrival_time") or row.get("end_time"),
                number=number,
                seat_class=seat_class,
                price=row.get("price", 0),
                remaining_tickets=row.get("remaining_seats", 0),
                carrier=row.get("carrier"),
            )
        )
    return candidates


def _parse_ticket_lines(text: str) -> list[TicketCandidate] | None:
    """Parse the stable human-readable format emitted by TicketQueryServer."""
    route_pattern = re.compile(
        r"^(?P<departure>.+?)\s+到\s+(?P<destination>.+?)\s+"
        r"(?P<departure_time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}):\s*"
        r"(?P<label>航班|车次)\s+(?P<number>[^，,]+)[，,]"
        r"(?P<seat_class>[^，,]+)[，,]票价\s*(?P<price>\d+(?:\.\d+)?)元[，,]"
        r"剩余\s*(?P<remaining>\d+)\s*张$"
    )
    concert_pattern = re.compile(
        r"^(?P<city>.+?)\s+(?P<departure_time>\d{4}-\d{2}-\d{2}\s+"
        r"\d{2}:\d{2}:\d{2}):\s*(?P<artist>.+?)\s+演唱会[，,]"
        r"(?P<seat_class>[^，,]+)[，,]场地\s+(?P<venue>[^，,]+)[，,]"
        r"票价\s*(?P<price>\d+(?:\.\d+)?)元[，,]剩余\s*"
        r"(?P<remaining>\d+)\s*张$"
    )

    candidates: list[TicketCandidate] = []
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not nonempty_lines:
        return None
    if len(nonempty_lines) == 1 and nonempty_lines[0].startswith("无结果"):
        return []

    for line in nonempty_lines:
        route = route_pattern.match(line)
        if route:
            values = route.groupdict()
            candidates.append(
                TicketCandidate(
                    ticket_type="flight" if values["label"] == "航班" else "train",
                    departure=values["departure"],
                    destination=values["destination"],
                    departure_time=values["departure_time"],
                    number=values["number"].strip(),
                    seat_class=values["seat_class"].strip(),
                    price=values["price"],
                    remaining_tickets=int(values["remaining"]),
                )
            )
            continue

        concert = concert_pattern.match(line)
        if concert:
            values = concert.groupdict()
            candidates.append(
                TicketCandidate(
                    ticket_type="concert",
                    departure=values["city"],
                    destination=values["venue"].strip(),
                    departure_time=values["departure_time"],
                    number=values["artist"].strip(),
                    seat_class=values["seat_class"].strip(),
                    price=values["price"],
                    remaining_tickets=int(values["remaining"]),
                )
            )
            continue

        return None
    return candidates


def _state_value(state: Any) -> str:
    return str(getattr(state, "value", state)).lower()


def _message_text(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    content = message.get("content", {})
    if isinstance(content, dict):
        text = content.get("text")
        return str(text) if text is not None else None
    return None


def extract_a2a_text(task: Any) -> str:
    """Extract the user-visible text from completed or input-required tasks."""
    if _state_value(task.status.state) == "completed":
        for artifact in task.artifacts or []:
            for part in artifact.get("parts", []):
                if part.get("type") == "text" and part.get("text") is not None:
                    return str(part["text"])

    status_text = _message_text(getattr(task.status, "message", None))
    if status_text:
        return status_text
    raise AgentResponseError(f"A2A任务未返回文本，状态为: {_state_value(task.status.state)}")


class CoordinatorClients:
    def __init__(self, network: Any, llm: Any):
        self.network = network
        self.llm = llm

    async def call_agent(self, agent_name: str, query: str) -> str:
        if self.network is None:
            raise RuntimeError("AgentNetwork 未初始化")
        agent = self.network.get_agent(agent_name)
        message = Message(content=TextContent(text=query), role=MessageRole.USER)
        task = Task(id=f"task-{uuid.uuid4()}", message=message.to_dict())
        response = await agent.send_task_async(task)
        return extract_a2a_text(response)

    def _normalize(self, schema: type, prompt: str) -> Any:
        runnable = self.llm.with_structured_output(schema)
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                return runnable.invoke(prompt)
            except Exception as exc:
                last_error = exc
        raise ResultNormalizationError(
            f"Agent结果无法转换为{schema.__name__}: {type(last_error).__name__}"
        ) from last_error

    def normalize_weather(self, text: str) -> WeatherResult:
        deterministic = _parse_amap_weather_sentence(text)
        if deterministic is not None:
            return deterministic
        prompt = (
            "把下面天气查询结果转换为结构化天气数据。"
            "只提取原文存在的信息，不要编造。\n查询结果：\n"
            f"{text}"
        )
        return self._normalize(WeatherResult, prompt)

    def normalize_tickets(self, text: str) -> list[TicketCandidate]:
        deterministic = _parse_ticket_json(text)
        if deterministic is not None:
            return deterministic
        deterministic = _parse_ticket_lines(text)
        if deterministic is not None:
            return deterministic
        prompt = (
            "把下面票务查询结果转换为候选票列表。"
            "number保存航班号、车次或演出票标识；只提取原文存在的信息。\n"
            f"查询结果：\n{text}"
        )
        result = self._normalize(TicketCandidateList, prompt)
        return result.tickets
