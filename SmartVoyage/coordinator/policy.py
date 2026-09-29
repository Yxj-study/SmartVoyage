from datetime import datetime
from decimal import Decimal
from operator import eq, ge, gt, le, lt, ne
from typing import Any, Callable, Sequence

from SmartVoyage.coordinator.schemas import (
    FilterCondition,
    SortRule,
    TicketCandidate,
    WeatherResult,
)


_COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": eq,
    "ne": ne,
    "lt": lt,
    "lte": le,
    "gt": gt,
    "gte": ge,
}


def _coerce_value(actual: Any, expected: Any) -> Any:
    if isinstance(actual, datetime):
        if isinstance(expected, datetime):
            return expected
        return datetime.fromisoformat(str(expected))
    if isinstance(actual, Decimal):
        return Decimal(str(expected))
    if isinstance(actual, int) and not isinstance(actual, bool):
        return int(expected)
    return expected


def _matches(ticket: TicketCandidate, condition: FilterCondition) -> bool:
    actual = getattr(ticket, condition.field)
    operator = condition.operator

    if operator in _COMPARATORS:
        expected = _coerce_value(actual, condition.value)
        return _COMPARATORS[operator](actual, expected)

    if operator in {"in", "not_in"}:
        if not isinstance(condition.value, (list, tuple, set)):
            raise ValueError(f"{operator} 操作符需要列表值")
        expected_values = [_coerce_value(actual, value) for value in condition.value]
        contained = actual in expected_values
        return contained if operator == "in" else not contained

    if operator == "between":
        if not isinstance(condition.value, (list, tuple)) or len(condition.value) != 2:
            raise ValueError("between 操作符需要两个边界值")
        lower = _coerce_value(actual, condition.value[0])
        upper = _coerce_value(actual, condition.value[1])
        return lower <= actual <= upper

    raise ValueError(f"不支持的条件操作符: {operator}")


def apply_ticket_policy(
    tickets: Sequence[TicketCandidate],
    filters: Sequence[FilterCondition],
    sorts: Sequence[SortRule],
) -> list[TicketCandidate]:
    """Filter and stable-sort candidates without executing generated code."""
    result = [
        ticket
        for ticket in tickets
        if all(_matches(ticket, condition) for condition in filters)
    ]

    for rule in reversed(sorts):
        result.sort(
            key=lambda ticket: getattr(ticket, rule.field),
            reverse=rule.order == "desc",
        )
    return result


def is_good_weather(weather: WeatherResult) -> bool:
    """Return whether deterministic travel-safety rules accept the weather."""
    adverse_terms = ("雨", "雪", "雷", "冰雹", "沙尘", "台风", "暴")
    if any(term in weather.weather for term in adverse_terms):
        return False
    if weather.wind_scale is not None and weather.wind_scale > 5:
        return False
    return weather.precipitation <= 0
