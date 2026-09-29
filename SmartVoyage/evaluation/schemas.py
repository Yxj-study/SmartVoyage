from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EvaluationTurn(BaseModel):
    query: str
    user_id: str | None = None
    session_id: str | None = None
    expected_response_contains: list[str] = Field(default_factory=list)
    fixture: dict[str, Any] = Field(default_factory=dict)


class EvaluationCase(BaseModel):
    id: str = Field(min_length=1)
    user_id: str = "eval-user"
    query: str = ""
    expected_tasks: list[str] = Field(default_factory=list)
    expected_slots: dict[str, Any] = Field(default_factory=dict)
    expected_workers: list[str] | None = None
    forbidden_actions: list[str] = Field(default_factory=list)
    assess_task_success: bool = False
    turns: list[EvaluationTurn] = Field(default_factory=list)
    expected_preferences: dict[str, Any] | None = None
    expected_applied_preferences: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    fixture: dict[str, Any] | None = None


class EvaluationPrediction(BaseModel):
    id: str = Field(min_length=1)
    predicted_tasks: list[str] = Field(default_factory=list)
    predicted_slots: dict[str, Any] = Field(default_factory=dict)
    selected_workers: list[str] = Field(default_factory=list)
    observed_actions: list[str] = Field(default_factory=list)
    tool_calls_attempted: int = Field(default=0, ge=0)
    tool_calls_succeeded: int = Field(default=0, ge=0)
    sql_queries_attempted: int = Field(default=0, ge=0)
    sql_queries_succeeded: int = Field(default=0, ge=0)
    task_success: bool | None = None
    multi_turn_success: bool | None = None
    retrieved_preferences: dict[str, Any] | None = None
    applied_preferences: dict[str, Any] | None = None
    cross_user_checks: int = Field(default=0, ge=0)
    cross_user_leaks: int = Field(default=0, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    error: str | None = None

    @model_validator(mode="after")
    def successful_counts_cannot_exceed_attempts(self):
        if self.tool_calls_succeeded > self.tool_calls_attempted:
            raise ValueError("成功工具调用数不能超过尝试数")
        if self.sql_queries_succeeded > self.sql_queries_attempted:
            raise ValueError("成功 SQL 数不能超过尝试数")
        if self.cross_user_leaks > self.cross_user_checks:
            raise ValueError("跨用户泄漏数不能超过检查数")
        return self


class MetricSummary(BaseModel):
    sample_count: int
    failed_count: int
    task_set_exact_match: float
    task_precision: float | None = None
    task_recall: float | None = None
    task_f1: float | None = None
    slot_accuracy: float | None = None
    plan_exact_match: float
    agent_selection_accuracy: float | None = None
    tool_call_success_rate: float | None = None
    sql_execution_success_rate: float | None = None
    task_success_rate: float | None = None
    multi_turn_task_success: float | None = None
    memory_retrieval_accuracy: float | None = None
    preference_application_accuracy: float | None = None
    cross_user_leakage_rate: float | None = None
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None


class EvaluationReport(BaseModel):
    created_at: datetime
    mode: Literal["offline", "integration"]
    dataset_path: str
    dataset_sha256: str
    percentile_method: str = "nearest-rank"
    metric_definitions: dict[str, str]
    summary: MetricSummary
    predictions: list[EvaluationPrediction]
