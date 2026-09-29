from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from SmartVoyage.evaluation.schemas import (
    EvaluationCase,
    EvaluationPrediction,
    MetricSummary,
)


_DATE_TIME_AT_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00(?:Z|[+-]\d\d:\d\d)?$")
_NUMBER = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)$")


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value)).normalize()
    if isinstance(value, str):
        stripped = value.strip()
        date_match = _DATE_TIME_AT_MIDNIGHT.fullmatch(stripped)
        if date_match:
            return date_match.group(1)
        if _NUMBER.fullmatch(stripped):
            try:
                return Decimal(stripped).normalize()
            except InvalidOperation:
                pass
        return stripped.lower()
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    return value


def _field_score(expected: dict[str, Any], actual: dict[str, Any]) -> tuple[int, int]:
    correct = sum(
        _normalize_value(actual.get(key)) == _normalize_value(value)
        for key, value in expected.items()
    )
    return correct, len(expected)


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _index_by_id(items, item_name: str):
    index = {}
    for item in items:
        if item.id in index:
            raise ValueError(f"{item_name} ID 必须唯一: {item.id}")
        index[item.id] = item
    return index


def score_cases(
    cases: list[EvaluationCase],
    predictions: list[EvaluationPrediction],
) -> MetricSummary:
    case_by_id = _index_by_id(cases, "样本")
    prediction_by_id = _index_by_id(predictions, "预测")
    if set(case_by_id) != set(prediction_by_id):
        raise ValueError("预测 ID 与样本 ID 不一致")

    sample_count = len(cases)
    failed_count = 0
    task_exact = 0
    plan_exact = 0
    task_tp = task_fp = task_fn = 0
    slot_correct = slot_total = 0
    worker_correct = worker_total = 0
    tool_attempted = tool_succeeded = 0
    sql_attempted = sql_succeeded = 0
    task_successes = task_success_total = 0
    multi_successes = multi_total = 0
    memory_correct = memory_total = 0
    application_correct = application_total = 0
    cross_user_checks = cross_user_leaks = 0
    latencies: list[float] = []

    for case in cases:
        prediction = prediction_by_id[case.id]
        failed = bool(prediction.error)
        failed_count += int(failed)

        expected_tasks = set(case.expected_tasks)
        predicted_tasks = set(prediction.predicted_tasks)
        tasks_match = not failed and expected_tasks == predicted_tasks
        task_exact += int(tasks_match)
        task_tp += len(expected_tasks & predicted_tasks)
        task_fp += len(predicted_tasks - expected_tasks)
        task_fn += len(expected_tasks - predicted_tasks)

        correct, total = _field_score(
            case.expected_slots,
            {} if failed else prediction.predicted_slots,
        )
        slot_correct += correct
        slot_total += total
        slots_match = correct == total
        plan_exact += int(tasks_match and slots_match)

        if case.expected_workers is not None:
            worker_total += 1
            worker_correct += int(
                not failed
                and set(case.expected_workers) == set(prediction.selected_workers)
            )

        tool_attempted += prediction.tool_calls_attempted
        tool_succeeded += prediction.tool_calls_succeeded
        sql_attempted += prediction.sql_queries_attempted
        sql_succeeded += prediction.sql_queries_succeeded

        forbidden_observed = bool(
            set(case.forbidden_actions) & set(prediction.observed_actions)
        )
        if case.assess_task_success:
            task_success_total += 1
            task_successes += int(
                not failed and prediction.task_success is True and not forbidden_observed
            )

        if case.turns:
            multi_total += 1
            multi_successes += int(
                not failed and prediction.multi_turn_success is True
            )

        if case.expected_preferences is not None:
            correct, total = _field_score(
                case.expected_preferences,
                {} if failed else (prediction.retrieved_preferences or {}),
            )
            memory_correct += correct
            memory_total += total

        if case.expected_applied_preferences is not None:
            correct, total = _field_score(
                case.expected_applied_preferences,
                {} if failed else (prediction.applied_preferences or {}),
            )
            application_correct += correct
            application_total += total

        cross_user_checks += prediction.cross_user_checks
        cross_user_leaks += prediction.cross_user_leaks
        if prediction.latency_ms is not None:
            latencies.append(prediction.latency_ms)

    precision = _safe_ratio(task_tp, task_tp + task_fp)
    recall = _safe_ratio(task_tp, task_tp + task_fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )

    return MetricSummary(
        sample_count=sample_count,
        failed_count=failed_count,
        task_set_exact_match=task_exact / sample_count if sample_count else 0.0,
        task_precision=precision,
        task_recall=recall,
        task_f1=f1,
        slot_accuracy=_safe_ratio(slot_correct, slot_total),
        plan_exact_match=plan_exact / sample_count if sample_count else 0.0,
        agent_selection_accuracy=_safe_ratio(worker_correct, worker_total),
        tool_call_success_rate=_safe_ratio(tool_succeeded, tool_attempted),
        sql_execution_success_rate=_safe_ratio(sql_succeeded, sql_attempted),
        task_success_rate=_safe_ratio(task_successes, task_success_total),
        multi_turn_task_success=_safe_ratio(multi_successes, multi_total),
        memory_retrieval_accuracy=_safe_ratio(memory_correct, memory_total),
        preference_application_accuracy=_safe_ratio(
            application_correct, application_total
        ),
        cross_user_leakage_rate=_safe_ratio(cross_user_leaks, cross_user_checks),
        latency_p50_ms=_nearest_rank(latencies, 0.50),
        latency_p95_ms=_nearest_rank(latencies, 0.95),
    )
