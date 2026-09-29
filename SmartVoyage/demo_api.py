from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable

from fastapi import FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field

from SmartVoyage.coordinator.graph import (
    build_coordinator,
    create_memory_checkpointer,
    sanitize_plan,
)
from SmartVoyage.coordinator.nodes import CoordinatorDependencies
from SmartVoyage.coordinator.schemas import (
    OrderResult,
    TicketCandidate,
    TravelPlan,
    TravelState,
    WeatherResult,
)
from SmartVoyage.amap_weather import environment_weather_query
from SmartVoyage.multimodal import (
    DashScopeVisionAnalyzer,
    ImageTooLargeError,
    InvalidImageError,
    VisionAnalyzer,
    VisionUnavailableError,
    analyze_travel_image,
)
from SmartVoyage.neo4j_graph import build_graph_lookup
from SmartVoyage.travel_knowledge import TRAVEL_PROFILES


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    session_id: str | None = None


class ImageAnalyzeRequest(BaseModel):
    image_data_url: str = Field(min_length=1, max_length=8_000_000)
    session_id: str | None = None


class ConfirmationRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    confirmed: bool


def _choose_next(state: TravelState) -> str:
    done = set(state.get("completed_tasks", [])) | set(state.get("skipped_tasks", []))
    for task in state["plan"].tasks:
        if task not in done:
            return task
    return "finalizer"


def _plan(query: str, _messages: list[dict]) -> TravelPlan:
    return sanitize_plan(query, TravelPlan())


def _tickets(plan: TravelPlan) -> list[TicketCandidate]:
    departure = plan.departure or "南京"
    destination = plan.destination or "上海"
    travel_date = plan.date or datetime.now().date()
    start = datetime.combine(travel_date, datetime.min.time()).replace(hour=9)
    ticket_type = plan.ticket_type or "train"
    prefix = {"flight": "MU", "train": "G", "concert": "SHOW"}[ticket_type]
    return [
        TicketCandidate(
            ticket_type=ticket_type,
            departure=departure,
            destination=destination,
            departure_time=start,
            arrival_time=start + timedelta(hours=2),
            number=f"{prefix}1024",
            seat_class="经济舱" if ticket_type == "flight" else "二等座",
            price=Decimal("328.00"),
            remaining_tickets=18,
            carrier="SmartVoyage Demo",
        ),
        TicketCandidate(
            ticket_type=ticket_type,
            departure=departure,
            destination=destination,
            departure_time=start + timedelta(hours=2),
            arrival_time=start + timedelta(hours=4),
            number=f"{prefix}2048",
            seat_class="经济舱" if ticket_type == "flight" else "二等座",
            price=Decimal("358.00"),
            remaining_tickets=12,
            carrier="SmartVoyage Demo",
        ),
    ]


def _attractions(plan: TravelPlan) -> list[dict[str, str]]:
    city = plan.destination or plan.departure or "目的地"
    candidates = [
        {"name": name, "reason": profile["feature"]}
        for name, profile in TRAVEL_PROFILES.items()
        if profile["city"] == city
    ]
    return candidates[:3] or [{"name": f"{city}博物馆", "reason": "了解当地历史文化"}]


def _place_order(ticket: TicketCandidate, quantity: int) -> OrderResult:
    return OrderResult(
        status="success",
        message=f"演示订单：{ticket.number} × {quantity}",
        order_id=f"DEMO-{uuid.uuid4().hex[:8]}",
        selected_ticket=ticket,
    )


def create_demo_graph(
    weather_query: Callable[[TravelPlan], WeatherResult] = environment_weather_query,
):
    dependencies = CoordinatorDependencies(
        plan=_plan,
        choose_next=_choose_next,
        query_weather=weather_query,
        query_tickets=_tickets,
        recommend_attractions=_attractions,
        place_order=_place_order,
    )
    return build_coordinator(dependencies, create_memory_checkpointer())


def _serialize_trace(result: dict) -> list[dict]:
    return [item.model_dump(mode="json") for item in result.get("trace", [])]


def _workflow_response(result: dict, session_id: str, started: float) -> dict:
    pending = bool(result.get("__interrupt__"))
    answer = result.get("final_answer")
    if pending:
        answer = "已生成候选票务方案，请确认或取消。公开演示只生成模拟订单，不会执行真实下单。"
    return {
        "answer": answer or "任务已完成。",
        "session_id": session_id,
        "processing_time": float(time.perf_counter() - started),
        "completed_tasks": result.get("completed_tasks", []),
        "skipped_tasks": result.get("skipped_tasks", []),
        "pending_confirmation": pending,
        "trace": _serialize_trace(result),
    }


def create_demo_app(
    vision_analyzer: VisionAnalyzer | None = None,
    weather_query: Callable[[TravelPlan], WeatherResult] = environment_weather_query,
) -> FastAPI:
    graph = create_demo_graph(weather_query)
    graph_lookup = build_graph_lookup()
    app = FastAPI(title="SmartVoyage LangGraph Demo API", version="1.0.0")

    @app.get("/health")
    async def health() -> dict:
        graph_stats = graph_lookup.stats() if hasattr(graph_lookup, "stats") else {
            "backend": graph_lookup.backend,
            "cities": len({profile["city"] for profile in TRAVEL_PROFILES.values()}),
            "landmarks": len(TRAVEL_PROFILES),
        }
        return {"status": "healthy", "engine": "langgraph", "mode": "safe_demo", "knowledge_graph": graph_stats}

    @app.post("/api/query")
    async def query(request: QueryRequest) -> dict:
        text = request.query.strip()
        if not text:
            raise HTTPException(status_code=422, detail="query must not be blank")
        session_id = request.session_id or str(uuid.uuid4())
        started = time.perf_counter()
        result = graph.invoke(
            {
                "user_id": "portfolio-demo",
                "session_id": session_id,
                "user_query": text,
                "messages": [],
            },
            config={"configurable": {"thread_id": f"portfolio-demo:{session_id}"}},
        )
        return _workflow_response(result, session_id, started)

    @app.post("/api/confirm")
    async def confirm(request: ConfirmationRequest) -> dict:
        started = time.perf_counter()
        try:
            result = graph.invoke(
                Command(resume=request.confirmed),
                config={
                    "configurable": {
                        "thread_id": f"portfolio-demo:{request.session_id}"
                    }
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=409,
                detail="确认状态已失效，请重新运行预订任务",
            ) from exc
        return _workflow_response(result, request.session_id, started)

    @app.post("/api/analyze-image")
    async def analyze_image(request: ImageAnalyzeRequest) -> dict:
        started = time.perf_counter()
        try:
            analyzer = vision_analyzer or DashScopeVisionAnalyzer.from_environment()
            result = analyze_travel_image(request.image_data_url, analyzer, graph_lookup)
        except ImageTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except InvalidImageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except VisionUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            **result.model_dump(mode="json"),
            "session_id": request.session_id or str(uuid.uuid4()),
            "processing_time": float(time.perf_counter() - started),
        }

    return app


app = create_demo_app()
