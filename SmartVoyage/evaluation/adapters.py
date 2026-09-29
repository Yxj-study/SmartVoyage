from __future__ import annotations

from time import perf_counter
from typing import Any

from langgraph.types import Command

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
    WeatherResult,
)
from SmartVoyage.evaluation.schemas import EvaluationCase, EvaluationPrediction
from SmartVoyage.memory.models import PreferenceCandidate
from SmartVoyage.memory.repository import InMemoryPreferenceRepository


_WORKER_BY_NODE = {
    "weather_worker": "weather",
    "ticket_worker": "ticket",
    "attraction_worker": "attraction",
    "order_worker": "order",
}


def _event_dict(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        return event.model_dump()
    return event if isinstance(event, dict) else {}


def prediction_from_state(
    case_id: str,
    state: dict[str, Any],
    latency_ms: float | None = None,
) -> EvaluationPrediction:
    plan = state.get("plan")
    plan_data = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else {}
    tasks = list(plan_data.get("tasks", []))
    slots = {
        key: value
        for key, value in plan_data.items()
        if key not in {"tasks", "filters", "sorts", "clarification"}
        and value is not None
    }
    trace = [_event_dict(event) for event in state.get("trace", [])]
    selected_workers = []
    observed_actions = []
    tool_attempted = tool_succeeded = 0
    for event in trace:
        node = str(event.get("node", ""))
        observed_actions.append(_WORKER_BY_NODE.get(node, node))
        worker = _WORKER_BY_NODE.get(node)
        if worker:
            selected_workers.append(worker)
            tool_attempted += 1
            tool_succeeded += int(event.get("status") == "completed")

    requested = set(state.get("requested_tasks", tasks))
    resolved = set(state.get("completed_tasks", [])) | set(
        state.get("skipped_tasks", [])
    )
    errors = state.get("errors", [])
    task_success = not errors and requested.issubset(resolved)

    return EvaluationPrediction(
        id=case_id,
        predicted_tasks=tasks,
        predicted_slots=slots,
        selected_workers=list(dict.fromkeys(selected_workers)),
        observed_actions=observed_actions,
        tool_calls_attempted=tool_attempted,
        tool_calls_succeeded=tool_succeeded,
        task_success=task_success,
        latency_ms=latency_ms,
        error=None if not errors else str(errors),
    )


def execute_offline_case(case: EvaluationCase) -> EvaluationPrediction:
    """Run the real coordinator with deterministic external-service fixtures."""

    if case.turns:
        return _execute_offline_memory_case(case)
    if case.fixture is None:
        raise ValueError("离线样本缺少 fixture 外部输入")
    fixture = case.fixture
    repository = InMemoryPreferenceRepository()
    user_id = case.user_id
    session_id = str(fixture.get("session_id", f"{case.id}-session"))

    for key, value in fixture.get("initial_preferences", {}).items():
        repository.upsert(
            user_id,
            "evaluation-seed",
            PreferenceCandidate(preference_key=key, value=value),
        )

    raw_plan = TravelPlan.model_validate(fixture.get("plan", {}))
    weather = (
        WeatherResult.model_validate(fixture["weather"])
        if fixture.get("weather") is not None
        else None
    )
    tickets = [
        TicketCandidate.model_validate(item) for item in fixture.get("tickets", [])
    ]
    attractions = list(fixture.get("attractions", []))
    order_result = (
        OrderResult.model_validate(fixture["order_result"])
        if fixture.get("order_result") is not None
        else None
    )
    preference_candidates = [
        PreferenceCandidate.model_validate(item)
        for item in fixture.get("preference_candidates", [])
    ]

    def choose_next(state):
        done = set(state.get("completed_tasks", [])) | set(
            state.get("skipped_tasks", [])
        )
        return next(
            (task for task in state["plan"].tasks if task not in done),
            "finalizer",
        )

    def persist_preferences(current_user_id, current_session_id, candidates):
        updates = []
        for candidate in candidates:
            if candidate.operation == "delete":
                repository.delete(
                    current_user_id,
                    current_session_id,
                    candidate.preference_key,
                    candidate.source_text,
                )
                updates.append(candidate)
            elif candidate.operation == "upsert":
                updates.append(
                    repository.upsert(
                        current_user_id, current_session_id, candidate
                    )
                )
        return updates

    dependencies = CoordinatorDependencies(
        plan=lambda query, _messages: sanitize_plan(query, raw_plan),
        choose_next=choose_next,
        query_weather=lambda _plan: weather,
        query_tickets=lambda _plan: tickets,
        recommend_attractions=lambda _plan: attractions,
        place_order=lambda ticket, _quantity: order_result
        or OrderResult(
            status="success",
            message="模拟预订成功",
            selected_ticket=ticket,
        ),
        load_preferences=repository.list_active,
        extract_preferences=lambda *_args: preference_candidates,
        persist_preferences=persist_preferences,
    )
    graph = build_coordinator(dependencies, create_memory_checkpointer())
    config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}
    started = perf_counter()
    state = graph.invoke(
        {
            "user_id": user_id,
            "session_id": session_id,
            "user_query": case.query,
            "messages": [],
        },
        config=config,
    )
    if state.get("__interrupt__") and "confirmation" in fixture:
        state = graph.invoke(Command(resume=bool(fixture["confirmation"])), config=config)

    prediction = prediction_from_state(
        case.id,
        state,
        latency_ms=(perf_counter() - started) * 1000,
    )
    loaded = _preference_dict(state.get("loaded_preferences", []))
    leaks = sum(
        1
        for record in state.get("loaded_preferences", [])
        if getattr(record, "user_id", user_id) != user_id
    )
    return prediction.model_copy(
        update={
            "retrieved_preferences": loaded,
            "applied_preferences": dict(state.get("applied_preferences", {})),
            "cross_user_checks": 1,
            "cross_user_leaks": leaks,
        }
    )


def _execute_offline_memory_case(case: EvaluationCase) -> EvaluationPrediction:
    """Run every labeled turn through one graph and one shared memory store."""

    repository = InMemoryPreferenceRepository()
    active_fixture: dict[str, Any] = {}
    turn_iterator = iter(case.turns)

    def choose_next(state):
        done = set(state.get("completed_tasks", [])) | set(
            state.get("skipped_tasks", [])
        )
        return next(
            (task for task in state["plan"].tasks if task not in done),
            "finalizer",
        )

    def plan(query, _messages):
        raw_plan = TravelPlan.model_validate(active_fixture.get("plan", {}))
        return sanitize_plan(query, raw_plan)

    def query_weather(_plan):
        value = active_fixture.get("weather")
        return WeatherResult.model_validate(value) if value is not None else None

    def query_tickets(_plan):
        return [
            TicketCandidate.model_validate(item)
            for item in active_fixture.get("tickets", [])
        ]

    def place_order(ticket, _quantity):
        value = active_fixture.get("order_result")
        if value is not None:
            return OrderResult.model_validate(value)
        return OrderResult(
            status="success",
            message="模拟预订成功",
            selected_ticket=ticket,
        )

    def extract_preferences(*_args):
        return [
            PreferenceCandidate.model_validate(item)
            for item in active_fixture.get("preference_candidates", [])
        ]

    def persist_preferences(current_user_id, current_session_id, candidates):
        updates = []
        for candidate in candidates:
            if candidate.operation == "delete":
                repository.delete(
                    current_user_id,
                    current_session_id,
                    candidate.preference_key,
                    candidate.source_text,
                )
                updates.append(candidate)
            elif candidate.operation == "upsert":
                updates.append(
                    repository.upsert(
                        current_user_id, current_session_id, candidate
                    )
                )
        return updates

    dependencies = CoordinatorDependencies(
        plan=plan,
        choose_next=choose_next,
        query_weather=query_weather,
        query_tickets=query_tickets,
        recommend_attractions=lambda _plan: list(
            active_fixture.get("attractions", [])
        ),
        place_order=place_order,
        load_preferences=repository.list_active,
        extract_preferences=extract_preferences,
        persist_preferences=persist_preferences,
    )
    graph = build_coordinator(dependencies, create_memory_checkpointer())

    def invoke_turn(user_id: str, session_id: str, query: str):
        nonlocal active_fixture
        turn = next(turn_iterator)
        if turn.query != query:
            raise ValueError("多轮样本执行顺序与标注不一致")
        active_fixture = turn.fixture
        config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}
        state = graph.invoke(
            {
                "user_id": user_id,
                "session_id": session_id,
                "user_query": query,
                "messages": [],
            },
            config=config,
        )
        if state.get("__interrupt__") and "confirmation" in active_fixture:
            state = graph.invoke(
                Command(resume=bool(active_fixture["confirmation"])),
                config=config,
            )
        return state

    return execute_memory_case(case, invoke_turn)


def _preference_dict(records: list[Any]) -> dict[str, Any]:
    result = {}
    for record in records:
        if hasattr(record, "model_dump"):
            item = record.model_dump()
        elif isinstance(record, dict):
            item = record
        else:
            continue
        if item.get("status", "active") == "active" and item.get("preference_key"):
            result[str(item["preference_key"])] = item.get("value")
    return result


def execute_memory_case(case: EvaluationCase, invoke_turn) -> EvaluationPrediction:
    """Execute a labeled multi-turn case while checking user isolation."""

    started = perf_counter()
    last_primary_state: dict[str, Any] = {}
    retrieved_preferences: dict[str, Any] = {}
    applied_preferences: dict[str, Any] = {}
    cross_user_checks = 0
    cross_user_leaks = 0
    successful = True
    try:
        for index, turn in enumerate(case.turns):
            user_id = turn.user_id or case.user_id
            session_id = turn.session_id or f"{case.id}-{index + 1}"
            state = invoke_turn(user_id, session_id, turn.query)
            response = str(state.get("final_answer", ""))
            if any(text not in response for text in turn.expected_response_contains):
                successful = False

            loaded_records = state.get("loaded_preferences", [])
            cross_user_checks += 1
            for record in loaded_records:
                record_user_id = (
                    record.user_id
                    if hasattr(record, "user_id")
                    else record.get("user_id") if isinstance(record, dict) else None
                )
                cross_user_leaks += int(
                    bool(record_user_id) and record_user_id != user_id
                )

            if user_id == case.user_id:
                last_primary_state = state
                loaded = _preference_dict(loaded_records)
                if loaded:
                    retrieved_preferences = loaded
                if state.get("applied_preferences"):
                    applied_preferences = dict(state["applied_preferences"])

        base = prediction_from_state(
            case.id,
            last_primary_state,
            latency_ms=(perf_counter() - started) * 1000,
        )
        return base.model_copy(
            update={
                "multi_turn_success": successful and base.task_success is True,
                "retrieved_preferences": retrieved_preferences,
                "applied_preferences": applied_preferences,
                "cross_user_checks": cross_user_checks,
                "cross_user_leaks": cross_user_leaks,
            }
        )
    except Exception as exc:
        return EvaluationPrediction(
            id=case.id,
            multi_turn_success=False,
            retrieved_preferences=retrieved_preferences,
            applied_preferences=applied_preferences,
            cross_user_checks=cross_user_checks,
            cross_user_leaks=cross_user_leaks,
            latency_ms=(perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )
