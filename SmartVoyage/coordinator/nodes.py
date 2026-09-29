from dataclasses import dataclass
from typing import Callable

from langgraph.types import interrupt

from SmartVoyage.coordinator.policy import apply_ticket_policy, is_good_weather
from SmartVoyage.coordinator.schemas import (
    OrderResult,
    TicketCandidate,
    TraceEvent,
    TravelPlan,
    TravelState,
    WeatherResult,
)
from SmartVoyage.memory.models import PreferenceCandidate, PreferenceRecord
from SmartVoyage.memory.policy import apply_preferences


def _empty_preferences(_user_id: str) -> list[PreferenceRecord]:
    return []


def _empty_candidates(
    _user_id: str, _session_id: str, _query: str
) -> list[PreferenceCandidate]:
    return []


def _ignore_preferences(
    _user_id: str,
    _session_id: str,
    _candidates: list[PreferenceCandidate],
) -> list[PreferenceRecord]:
    return []


@dataclass
class CoordinatorDependencies:
    plan: Callable[[str, list[dict]], TravelPlan]
    choose_next: Callable[[TravelState], str]
    query_weather: Callable[[TravelPlan], WeatherResult]
    query_tickets: Callable[[TravelPlan], list[TicketCandidate]]
    recommend_attractions: Callable[[TravelPlan], list[dict[str, str]]]
    place_order: Callable[[TicketCandidate, int], OrderResult]
    load_preferences: Callable[[str], list[PreferenceRecord]] = _empty_preferences
    extract_preferences: Callable[
        [str, str, str], list[PreferenceCandidate]
    ] = _empty_candidates
    persist_preferences: Callable[
        [str, str, list[PreferenceCandidate]], list
    ] = _ignore_preferences


def _append_unique(values: list[str], *items: str) -> list[str]:
    result = list(values)
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _trace(state: TravelState, event: TraceEvent) -> list[TraceEvent]:
    return [*state.get("trace", []), event]


def memory_load_node(dependencies: CoordinatorDependencies):
    def run(state: TravelState) -> dict:
        user_id = state.get("user_id")
        session_id = state.get("session_id")
        if not user_id or not session_id:
            return {"loaded_preferences": [], "memory_errors": []}
        try:
            preferences = dependencies.load_preferences(user_id)
            return {
                "loaded_preferences": preferences,
                "memory_errors": [],
                "trace": _trace(
                    state,
                    TraceEvent(
                        node="memory_load",
                        label="Memory Load",
                        status="completed",
                        summary=f"加载 {len(preferences)} 条长期偏好",
                    ),
                ),
            }
        except Exception as exc:
            return {
                "loaded_preferences": [],
                "memory_errors": [
                    {"stage": "memory_load", "message": str(exc)}
                ],
                "trace": _trace(
                    state,
                    TraceEvent(
                        node="memory_load",
                        label="Memory Load",
                        status="failed",
                        summary="长期偏好读取失败，本轮使用空偏好继续",
                    ),
                ),
            }

    return run


def _applied_preference_values(
    before: TravelPlan,
    after: TravelPlan,
    preferences: list[PreferenceRecord],
) -> dict:
    values = {
        item.preference_key: item.value
        for item in preferences
        if item.status == "active"
    }
    applied = {}
    if before.ticket_type is None and after.ticket_type is not None:
        if "preferred_transport" in values:
            applied["preferred_transport"] = values["preferred_transport"]

    before_fields = {condition.field for condition in before.filters}
    for condition in after.filters:
        if condition.field in before_fields:
            continue
        if condition.field == "price" and "max_ticket_budget" in values:
            applied["max_ticket_budget"] = values["max_ticket_budget"]
        elif condition.field == "departure_time" and "preferred_departure_period" in values:
            applied["preferred_departure_period"] = values[
                "preferred_departure_period"
            ]
        elif condition.field == "seat_class":
            key = (
                "preferred_cabin_class"
                if after.ticket_type == "flight"
                else "preferred_seat_class"
            )
            if key in values:
                applied[key] = values[key]
    return applied


def planner_node(dependencies: CoordinatorDependencies):
    def run(state: TravelState) -> dict:
        original_plan = dependencies.plan(
            state["user_query"], state.get("messages", [])
        )
        preferences = state.get("loaded_preferences", [])
        plan = apply_preferences(state["user_query"], original_plan, preferences)
        applied_preferences = _applied_preference_values(
            original_plan, plan, preferences
        )
        return {
            "plan": plan,
            "requested_tasks": list(plan.tasks),
            "completed_tasks": [],
            "skipped_tasks": [],
            "errors": [],
            "applied_preferences": applied_preferences,
            "trace": _trace(
                state,
                TraceEvent(
                    node="planner",
                    label="Planner",
                    status="completed",
                    summary=(
                        f"识别任务：{', '.join(plan.tasks) or '需要追问'}；"
                        f"应用长期偏好 {len(applied_preferences)} 项"
                    ),
                ),
            ),
            "step_count": 0,
            "clarification": plan.clarification or "",
        }

    return run


def memory_persist_node(dependencies: CoordinatorDependencies):
    def run(state: TravelState) -> dict:
        user_id = state.get("user_id")
        session_id = state.get("session_id")
        if not user_id or not session_id:
            return {"preference_updates": []}
        try:
            candidates = dependencies.extract_preferences(
                user_id, session_id, state["user_query"]
            )
            stable_candidates = [
                candidate
                for candidate in candidates
                if candidate.operation != "ignore" and candidate.scope == "stable"
            ]
            updates = dependencies.persist_preferences(
                user_id, session_id, stable_candidates
            )
            return {
                "preference_updates": updates,
                "trace": _trace(
                    state,
                    TraceEvent(
                        node="memory_persist",
                        label="Memory Persist",
                        status="completed",
                        summary=f"沉淀 {len(updates)} 条长期偏好变更",
                    ),
                ),
            }
        except Exception as exc:
            return {
                "preference_updates": [],
                "memory_errors": [
                    *state.get("memory_errors", []),
                    {"stage": "memory_persist", "message": str(exc)},
                ],
                "trace": _trace(
                    state,
                    TraceEvent(
                        node="memory_persist",
                        label="Memory Persist",
                        status="failed",
                        summary="长期偏好写入失败，旅行任务结果仍然保留",
                    ),
                ),
            }

    return run


def supervisor_node(dependencies: CoordinatorDependencies):
    allowed_actions = {
        "weather",
        "ticket",
        "attraction",
        "order",
        "confirmation",
        "finalizer",
        "supervisor",
    }

    def run(state: TravelState) -> dict:
        step_count = state.get("step_count", 0) + 1
        skipped = list(state.get("skipped_tasks", []))

        if step_count >= 8:
            action = "finalizer"
        else:
            proposed = dependencies.choose_next(state)
            action = proposed if proposed in allowed_actions else "finalizer"

            domain_actions = {"weather", "ticket", "attraction", "order"}
            done = set(state.get("completed_tasks", [])) | set(skipped)
            pending = [task for task in state["plan"].tasks if task not in done]

            if action == "finalizer" and pending:
                action = pending[0]
            elif action in domain_actions and action in done:
                action = pending[0] if pending else "finalizer"

            if action in domain_actions and action not in state["plan"].tasks:
                action = pending[0] if pending else "finalizer"

            if action == "ticket" and state["plan"].weather_required_for_ticket:
                if "weather" not in state.get("completed_tasks", []):
                    action = "weather"
                elif not state.get("weather_good", False):
                    skipped = _append_unique(skipped, "ticket", "order")
                    action = "supervisor"

            if action == "order":
                if "selected_ticket" not in state:
                    skipped = _append_unique(skipped, "order")
                    action = "supervisor"
                elif not state.get("confirmed", False):
                    if "confirmation" in state.get("completed_tasks", []):
                        skipped = _append_unique(skipped, "order")
                        action = "supervisor"
                    else:
                        action = "confirmation"

        return {
            "next_action": action,
            "step_count": step_count,
            "skipped_tasks": skipped,
            "trace": _trace(
                state,
                TraceEvent(
                    node="supervisor",
                    label="Supervisor",
                    status="completed",
                    summary=f"下一动作：{action}",
                ),
            ),
        }

    return run


def weather_worker_node(dependencies: CoordinatorDependencies):
    def run(state: TravelState) -> dict:
        weather = dependencies.query_weather(state["plan"])
        return {
            "weather_result": weather,
            "trace": _trace(
                state,
                TraceEvent(
                    node="weather_worker",
                    label="Weather Agent",
                    status="completed",
                    summary=f"{weather.city}：{weather.weather}",
                ),
            ),
        }

    return run


def weather_policy_node(state: TravelState) -> dict:
    accepted = is_good_weather(state["weather_result"])
    return {
        "weather_good": accepted,
        "completed_tasks": _append_unique(state.get("completed_tasks", []), "weather"),
        "trace": _trace(
            state,
            TraceEvent(
                node="weather_policy",
                label="Weather Policy",
                status="completed",
                summary="天气满足出行条件" if accepted else "天气不满足出行条件",
            ),
        ),
    }


def ticket_worker_node(dependencies: CoordinatorDependencies):
    def run(state: TravelState) -> dict:
        candidates = dependencies.query_tickets(state["plan"])
        return {
            "ticket_candidates": candidates,
            "trace": _trace(
                state,
                TraceEvent(
                    node="ticket_worker",
                    label="Ticket Agent",
                    status="completed",
                    summary=f"查询到 {len(candidates)} 条候选票",
                ),
            ),
        }

    return run


def ticket_policy_node(state: TravelState) -> dict:
    eligible = apply_ticket_policy(
        state.get("ticket_candidates", []),
        state["plan"].filters,
        state["plan"].sorts,
    )
    delta = {
        "eligible_tickets": eligible,
        "completed_tasks": _append_unique(state.get("completed_tasks", []), "ticket"),
        "trace": _trace(
            state,
            TraceEvent(
                node="ticket_policy",
                label="Ticket Policy",
                status="completed",
                summary=f"筛选出 {len(eligible)} 条符合条件的票",
            ),
        ),
    }
    if eligible:
        delta["selected_ticket"] = eligible[0]
    elif "order" in state["plan"].tasks:
        delta["skipped_tasks"] = _append_unique(state.get("skipped_tasks", []), "order")
    return delta


def attraction_worker_node(dependencies: CoordinatorDependencies):
    def run(state: TravelState) -> dict:
        attractions = dependencies.recommend_attractions(state["plan"])
        return {
            "attractions": attractions,
            "completed_tasks": _append_unique(
                state.get("completed_tasks", []), "attraction"
            ),
            "trace": _trace(
                state,
                TraceEvent(
                    node="attraction_worker",
                    label="Attraction Tool",
                    status="completed",
                    summary=f"推荐 {len(attractions)} 个景点",
                ),
            ),
        }

    return run


def order_worker_node(dependencies: CoordinatorDependencies):
    def run(state: TravelState) -> dict:
        result = dependencies.place_order(
            state["selected_ticket"], state["plan"].quantity
        )
        return {
            "order_result": result,
            "completed_tasks": _append_unique(state.get("completed_tasks", []), "order"),
            "trace": _trace(
                state,
                TraceEvent(
                    node="order_worker",
                    label="Order Agent",
                    status="completed" if result.status == "success" else "failed",
                    summary=result.message,
                ),
            ),
        }

    return run


def confirmation_node(state: TravelState) -> dict:
    decision = interrupt(
        {
            "type": "booking_confirmation",
            "ticket": state["selected_ticket"].model_dump(mode="json"),
            "quantity": state["plan"].quantity,
        }
    )
    confirmed = bool(decision)
    delta = {
        "pending_confirmation": False,
        "confirmed": confirmed,
        "completed_tasks": _append_unique(
            state.get("completed_tasks", []), "confirmation"
        ),
        "trace": _trace(
            state,
            TraceEvent(
                node="confirmation",
                label="Human Confirmation",
                status="completed" if confirmed else "skipped",
                summary="用户已确认预订" if confirmed else "用户已取消预订",
            ),
        ),
    }
    if not confirmed:
        delta["skipped_tasks"] = _append_unique(
            state.get("skipped_tasks", []), "order"
        )
    return delta


def clarification_node(state: TravelState) -> dict:
    return {"final_answer": state.get("clarification", "请补充必要信息。")}


def finalizer_node(state: TravelState) -> dict:
    if state.get("step_count", 0) >= 8:
        return {"final_answer": "任务达到最大执行步数，已停止并返回现有结果。"}

    lines: list[str] = []
    if "weather_result" in state:
        weather = state["weather_result"]
        date_suffix = f"（{weather.date.isoformat()}）" if weather.date else ""
        lines.append(f"天气：{weather.city} {weather.weather}{date_suffix}")
    if state.get("eligible_tickets"):
        ticket = state["eligible_tickets"][0]
        lines.append(f"票务：{ticket.number}，{ticket.price} 元")
    if state.get("attractions"):
        names = "、".join(item["name"] for item in state["attractions"])
        lines.append(f"景点：{names}")
    if state.get("skipped_tasks"):
        lines.append(f"已跳过：{', '.join(state['skipped_tasks'])}")
    if "order_result" in state:
        lines.append(f"订单：{state['order_result'].message}")
    return {"final_answer": "\n".join(lines) or "任务已完成。"}
