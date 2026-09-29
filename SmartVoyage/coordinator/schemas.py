from __future__ import annotations

import re
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, TypedDict

from pydantic import AliasChoices, BaseModel, Field, field_validator


PolicyField = Literal[
    "price",
    "departure_time",
    "arrival_time",
    "duration_minutes",
    "ticket_type",
    "seat_class",
    "remaining_tickets",
    "number",
    "carrier",
]
PolicyOperator = Literal[
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "in",
    "not_in",
    "between",
]


class FilterCondition(BaseModel):
    field: PolicyField
    operator: PolicyOperator
    value: Any


class SortRule(BaseModel):
    field: PolicyField
    order: Literal["asc", "desc"] = "asc"


class TravelPlan(BaseModel):
    ticket_type: Literal["flight", "train", "concert"] | None = None
    departure: str | None = None
    destination: str | None = None
    date: Date | None = None
    weather_days: int = Field(default=1, ge=1, le=7)
    quantity: int = Field(default=1, ge=1, le=9)
    tasks: list[Literal["weather", "ticket", "attraction", "order"]] = Field(
        default_factory=list
    )
    weather_required_for_ticket: bool = False
    filters: list[FilterCondition] = Field(default_factory=list)
    sorts: list[SortRule] = Field(default_factory=list)
    action: Literal["query", "book_if_available"] = "query"
    clarification: str | None = None
    requires_confirmation: bool = True


class TicketCandidate(BaseModel):
    ticket_type: Literal["flight", "train", "concert"]
    departure: str
    destination: str
    departure_time: datetime
    arrival_time: datetime | None = None
    duration_minutes: int | None = None
    number: str
    seat_class: str
    price: Decimal
    remaining_tickets: int
    carrier: str | None = None


class TicketCandidateList(BaseModel):
    tickets: list[TicketCandidate] = Field(default_factory=list)


class Attraction(BaseModel):
    name: str
    reason: str


class AttractionList(BaseModel):
    attractions: list[Attraction] = Field(default_factory=list)


class SupervisorDecision(BaseModel):
    next_action: Literal[
        "weather", "ticket", "attraction", "order", "finalizer", "supervisor"
    ]


class WeatherResult(BaseModel):
    city: str
    weather: str = Field(
        validation_alias=AliasChoices("weather", "weather_day", "text_day")
    )
    date: Date | None = None
    wind_scale: int | None = Field(
        default=None,
        validation_alias=AliasChoices("wind_scale", "wind_level", "wind_scale_day"),
    )
    precipitation: Decimal = Decimal("0")
    temperature_min: int | None = None
    temperature_max: int | None = None

    @field_validator("wind_scale", mode="before")
    @classmethod
    def normalize_wind_scale(cls, value):
        if value is None or isinstance(value, int):
            return value
        digits = [int(part) for part in re.findall(r"\d+", str(value))]
        return max(digits) if digits else None


class OrderResult(BaseModel):
    status: Literal["success", "failed", "cancelled"]
    message: str
    order_id: str | None = None
    selected_ticket: TicketCandidate | None = None


class TraceEvent(BaseModel):
    node: str
    label: str
    status: Literal["started", "completed", "skipped", "waiting", "failed"]
    summary: str


class TravelState(TypedDict, total=False):
    thread_id: str
    user_id: str
    session_id: str
    messages: list[dict[str, Any]]
    user_query: str
    plan: TravelPlan
    requested_tasks: list[str]
    completed_tasks: list[str]
    skipped_tasks: list[str]
    next_action: str
    step_count: int
    weather_result: WeatherResult
    weather_good: bool
    ticket_candidates: list[TicketCandidate]
    eligible_tickets: list[TicketCandidate]
    selected_ticket: TicketCandidate
    attractions: list[dict[str, str]]
    pending_confirmation: bool
    confirmed: bool
    order_result: OrderResult
    trace: list[TraceEvent]
    errors: list[dict[str, str]]
    memory_errors: list[dict[str, str]]
    loaded_preferences: list[Any]
    applied_preferences: dict[str, Any]
    preference_updates: list[Any]
    clarification: str
    final_answer: str
