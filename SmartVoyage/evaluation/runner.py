from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from SmartVoyage.evaluation.metrics import score_cases
from SmartVoyage.evaluation.schemas import (
    EvaluationCase,
    EvaluationPrediction,
    EvaluationReport,
)


METRIC_DEFINITIONS = {
    "task_set_exact_match": "预测任务集合与标注集合完全一致的样本数/总样本数",
    "task_f1": "weather、ticket、attraction、order 多标签任务的 Micro-F1",
    "slot_accuracy": "规范化后正确槽位字段数/标注槽位字段数",
    "plan_exact_match": "任务集合和全部标注槽位同时正确的样本数/总样本数",
    "agent_selection_accuracy": "Worker 集合与标注集合一致的适用样本数/适用样本数",
    "tool_call_success_rate": "成功工具调用数/尝试工具调用数",
    "sql_execution_success_rate": "成功只读 SQL 数/尝试合法 SQL 数",
    "task_success_rate": "满足验收条件且无禁止动作的样本数/适用样本数",
    "multi_turn_task_success": "完整多轮流程成功数/多轮样本数",
    "memory_retrieval_accuracy": "正确检索偏好字段数/标注偏好字段数",
    "preference_application_accuracy": "正确应用偏好字段数/标注应用字段数",
    "cross_user_leakage_rate": "观察到其他用户偏好的次数/隔离检查次数",
    "latency_p50_ms": "全部样本端到端耗时的最近秩 P50",
    "latency_p95_ms": "全部样本端到端耗时的最近秩 P95",
}


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    for file_path in files:
        if path.is_dir():
            digest.update(file_path.name.encode("utf-8"))
            digest.update(b"\x00")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def load_cases(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    if not files:
        raise ValueError(f"没有找到 JSONL 评测文件: {path}")
    for file_path in files:
        with file_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                case = EvaluationCase.model_validate_json(line)
                if case.id in seen_ids:
                    raise ValueError(
                        f"样本 ID 必须唯一: {case.id}，"
                        f"文件 {file_path.name} 第 {line_number} 行"
                    )
                seen_ids.add(case.id)
                cases.append(case)
    return cases


def run_evaluation(
    cases: list[EvaluationCase],
    executor: Callable[[EvaluationCase], EvaluationPrediction],
    mode: str,
    dataset_sha256: str,
    dataset_path: str,
) -> EvaluationReport:
    if mode not in {"offline", "integration"}:
        raise ValueError(f"不支持的评测模式: {mode}")

    predictions: list[EvaluationPrediction] = []
    for case in cases:
        started = perf_counter()
        try:
            prediction = executor(case)
            if prediction.id != case.id:
                raise ValueError(
                    f"执行器返回的预测 ID {prediction.id} 与样本 {case.id} 不一致"
                )
            elapsed_ms = (perf_counter() - started) * 1000
            if prediction.latency_ms is None:
                prediction = prediction.model_copy(update={"latency_ms": elapsed_ms})
        except Exception as exc:
            elapsed_ms = (perf_counter() - started) * 1000
            prediction = EvaluationPrediction(
                id=case.id,
                latency_ms=elapsed_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
        predictions.append(prediction)

    return EvaluationReport(
        created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        mode=mode,
        dataset_path=dataset_path,
        dataset_sha256=dataset_sha256,
        metric_definitions=METRIC_DEFINITIONS,
        summary=score_cases(cases, predictions),
        predictions=predictions,
    )


def write_report(report: EvaluationReport, output_directory: Path) -> dict[str, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    stamp = report.created_at.strftime("%Y%m%dT%H%M%S%z")
    prefix = f"{stamp}-{report.mode}"
    details_path = output_directory / f"{prefix}-details.json"
    summary_path = output_directory / f"{prefix}-summary.json"
    csv_path = output_directory / f"{prefix}-cases.csv"

    details_path.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    summary_payload = report.model_dump(exclude={"predictions"}, mode="json")
    summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "id",
            "error",
            "latency_ms",
            "predicted_tasks",
            "predicted_slots",
            "selected_workers",
            "task_success",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for prediction in report.predictions:
            writer.writerow(
                {
                    "id": prediction.id,
                    "error": prediction.error or "",
                    "latency_ms": prediction.latency_ms,
                    "predicted_tasks": json.dumps(
                        prediction.predicted_tasks, ensure_ascii=False
                    ),
                    "predicted_slots": json.dumps(
                        prediction.predicted_slots, ensure_ascii=False, default=str
                    ),
                    "selected_workers": json.dumps(
                        prediction.selected_workers, ensure_ascii=False
                    ),
                    "task_success": prediction.task_success,
                }
            )

    return {"details": details_path, "summary": summary_path, "csv": csv_path}
