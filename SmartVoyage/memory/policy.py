from __future__ import annotations

from decimal import Decimal, InvalidOperation

from SmartVoyage.coordinator.schemas import FilterCondition, TravelPlan
from SmartVoyage.memory.models import PreferenceCandidate, PreferenceRecord


SUPPORTED_PREFERENCE_KEYS = frozenset(
    {
        "preferred_transport",
        "max_ticket_budget",
        "preferred_seat_class",
        "preferred_cabin_class",
        "preferred_departure_period",
        "preferred_hotel_level",
        "preferred_attraction_types",
    }
)

_DEPARTURE_PERIODS = {
    "morning": ("06:00:00", "11:59:59"),
    "afternoon": ("12:00:00", "17:59:59"),
    "evening": ("18:00:00", "23:59:59"),
    "night": ("00:00:00", "05:59:59"),
    "上午": ("06:00:00", "11:59:59"),
    "下午": ("12:00:00", "17:59:59"),
    "晚上": ("18:00:00", "23:59:59"),
    "夜间": ("00:00:00", "05:59:59"),
}


def _nonempty_string(value, label: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"{label}不能为空")
    return normalized


def validate_candidate(candidate: PreferenceCandidate) -> PreferenceCandidate:
    key = candidate.preference_key
    if key not in SUPPORTED_PREFERENCE_KEYS:
        raise ValueError(f"不支持的偏好字段: {key}")

    if candidate.operation in {"delete", "ignore"}:
        return candidate.model_copy(deep=True)

    value = candidate.value
    if key == "preferred_transport":
        normalized = str(value).strip().lower()
        aliases = {"火车": "train", "高铁": "train", "飞机": "flight", "机票": "flight"}
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"train", "flight"}:
            raise ValueError("交通偏好必须是 train 或 flight")
        value = normalized
    elif key == "max_ticket_budget":
        try:
            budget = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("预算必须为正数") from exc
        if budget <= 0:
            raise ValueError("预算必须为正数")
        value = int(budget) if budget == budget.to_integral() else float(budget)
    elif key in {
        "preferred_seat_class",
        "preferred_cabin_class",
        "preferred_hotel_level",
    }:
        value = _nonempty_string(value, "偏好值")
    elif key == "preferred_departure_period":
        period = _nonempty_string(value, "出发时段")
        if period not in _DEPARTURE_PERIODS:
            raise ValueError("不支持的出发时段")
        value = period
    elif key == "preferred_attraction_types":
        if not isinstance(value, list):
            raise ValueError("景点类型偏好必须是列表")
        normalized_values = []
        for item in value:
            normalized = _nonempty_string(item, "景点类型")
            if normalized not in normalized_values:
                normalized_values.append(normalized)
        if not normalized_values:
            raise ValueError("景点类型偏好不能为空")
        value = normalized_values

    return candidate.model_copy(update={"value": value}, deep=True)


def _has_filter(plan: TravelPlan, field: str) -> bool:
    return any(condition.field == field for condition in plan.filters)


def apply_preferences(
    query: str,
    plan: TravelPlan,
    preferences: list[PreferenceRecord],
) -> TravelPlan:
    """Fill only information missing from the current request/plan."""

    del query  # The structured plan is authoritative for current-request values.
    result = plan.model_copy(deep=True)
    active = {
        record.preference_key: record.value
        for record in preferences
        if record.status == "active" and record.preference_key in SUPPORTED_PREFERENCE_KEYS
    }
    needs_ticket = "ticket" in result.tasks or "order" in result.tasks

    if needs_ticket and result.ticket_type is None and "preferred_transport" in active:
        transport = validate_candidate(
            PreferenceCandidate(
                preference_key="preferred_transport",
                value=active["preferred_transport"],
            )
        ).value
        result.ticket_type = transport

    if needs_ticket and not _has_filter(result, "price") and "max_ticket_budget" in active:
        budget = validate_candidate(
            PreferenceCandidate(
                preference_key="max_ticket_budget",
                value=active["max_ticket_budget"],
            )
        ).value
        result.filters.append(
            FilterCondition(field="price", operator="lte", value=budget)
        )

    seat_key = (
        "preferred_cabin_class"
        if result.ticket_type == "flight"
        else "preferred_seat_class"
    )
    if needs_ticket and not _has_filter(result, "seat_class") and seat_key in active:
        seat_value = validate_candidate(
            PreferenceCandidate(preference_key=seat_key, value=active[seat_key])
        ).value
        result.filters.append(
            FilterCondition(field="seat_class", operator="eq", value=seat_value)
        )

    if (
        needs_ticket
        and result.date
        and not _has_filter(result, "departure_time")
        and "preferred_departure_period" in active
    ):
        period = validate_candidate(
            PreferenceCandidate(
                preference_key="preferred_departure_period",
                value=active["preferred_departure_period"],
            )
        ).value
        start, end = _DEPARTURE_PERIODS[period]
        result.filters.append(
            FilterCondition(
                field="departure_time",
                operator="between",
                value=[f"{result.date.isoformat()}T{start}", f"{result.date.isoformat()}T{end}"],
            )
        )

    return result
