import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from SmartVoyage.evaluation.runner import (
    compute_sha256,
    load_cases,
    run_evaluation,
    write_report,
)
from SmartVoyage.evaluation.schemas import EvaluationPrediction


class EvaluationRunnerTest(unittest.TestCase):
    def test_runner_keeps_exception_as_failed_prediction_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "cases.jsonl"
            dataset.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {"id": "ok", "query": "查天气", "expected_tasks": ["weather"]},
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {"id": "failed", "query": "查机票", "expected_tasks": ["ticket"]},
                            ensure_ascii=False,
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            cases = load_cases(dataset)

            def executor(case):
                if case.id == "failed":
                    raise TimeoutError("model timeout")
                return EvaluationPrediction(
                    id=case.id,
                    predicted_tasks=["weather"],
                )

            report = run_evaluation(
                cases,
                executor,
                mode="offline",
                dataset_sha256=compute_sha256(dataset),
                dataset_path=str(dataset),
            )
            paths = write_report(report, root / "reports")

            self.assertEqual(report.summary.sample_count, 2)
            self.assertEqual(report.summary.failed_count, 1)
            self.assertEqual(report.mode, "offline")
            self.assertEqual(report.dataset_sha256, compute_sha256(dataset))
            self.assertIn("model timeout", paths["details"].read_text(encoding="utf-8"))
            self.assertNotIn("SMARTVOYAGE_API_KEY", paths["details"].read_text(encoding="utf-8"))
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            self.assertEqual(summary["summary"]["sample_count"], 2)
            with paths["csv"].open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["id"] for row in rows], ["ok", "failed"])

    def test_loader_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "duplicates.jsonl"
            dataset.write_text(
                '{"id":"same","query":"a"}\n{"id":"same","query":"b"}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "样本 ID 必须唯一"):
                load_cases(dataset)

    def test_directory_loader_combines_jsonl_files_and_hashes_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.jsonl").write_text(
                '{"id":"b","query":"b"}\n', encoding="utf-8"
            )
            (root / "a.jsonl").write_text(
                '{"id":"a","query":"a"}\n', encoding="utf-8"
            )

            cases = load_cases(root)
            first_hash = compute_sha256(root)
            (root / "a.jsonl").write_text(
                '{"id":"a","query":"changed"}\n', encoding="utf-8"
            )
            second_hash = compute_sha256(root)

            self.assertEqual([case.id for case in cases], ["a", "b"])
            self.assertNotEqual(first_hash, second_hash)

    def test_state_adapter_extracts_plan_workers_and_failures(self):
        from SmartVoyage.coordinator.schemas import TravelPlan
        from SmartVoyage.evaluation.adapters import prediction_from_state

        state = {
            "plan": TravelPlan(
                ticket_type="train",
                departure="南京",
                destination="上海",
                tasks=["ticket"],
            ),
            "completed_tasks": ["ticket"],
            "trace": [
                {
                    "node": "ticket_worker",
                    "label": "Ticket Agent",
                    "status": "completed",
                    "summary": "查询成功",
                }
            ],
            "errors": [],
            "final_answer": "已找到车票",
        }

        prediction = prediction_from_state("case-1", state, latency_ms=12.5)

        self.assertEqual(prediction.predicted_tasks, ["ticket"])
        self.assertEqual(prediction.predicted_slots["ticket_type"], "train")
        self.assertEqual(prediction.selected_workers, ["ticket"])
        self.assertEqual(prediction.tool_calls_attempted, 1)
        self.assertEqual(prediction.tool_calls_succeeded, 1)
        self.assertTrue(prediction.task_success)

    def test_cli_requires_explicit_network_permission_for_integration(self):
        from SmartVoyage.evaluation.cli import main

        with self.assertRaisesRegex(SystemExit, "必须显式提供 --allow-network"):
            main(
                [
                    "--mode",
                    "integration",
                    "--dataset",
                    "cases.jsonl",
                    "--output",
                    "reports",
                ]
            )

    def test_offline_cli_executes_real_graph_from_fixture_inputs(self):
        from SmartVoyage.evaluation.cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "cases.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "id": "offline-1",
                        "query": "查北京天气",
                        "expected_tasks": ["weather"],
                        "expected_workers": ["weather"],
                        "assess_task_success": True,
                        "fixture": {
                            "plan": {"destination": "北京", "tasks": ["weather"]},
                            "weather": {
                                "city": "北京",
                                "weather": "晴",
                                "wind_scale": 2,
                                "precipitation": 0
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = root / "reports"

            with patch("builtins.print"):
                exit_code = main(
                    [
                        "--mode",
                        "offline",
                        "--dataset",
                        str(dataset),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            summaries = list(output.glob("*-offline-summary.json"))
            self.assertEqual(len(summaries), 1)
            payload = json.loads(summaries[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["task_set_exact_match"], 1.0)
            self.assertEqual(payload["summary"]["agent_selection_accuracy"], 1.0)
            self.assertEqual(payload["summary"]["task_success_rate"], 1.0)

    def test_offline_cli_executes_cross_session_memory_fixture(self):
        from SmartVoyage.evaluation.cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "memory.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "id": "memory-1",
                        "user_id": "user-a",
                        "query": "跨会话偏好",
                        "expected_preferences": {"preferred_transport": "train"},
                        "expected_applied_preferences": {"preferred_transport": "train"},
                        "turns": [
                            {
                                "user_id": "user-a",
                                "session_id": "a-1",
                                "query": "请记住我以后优先坐高铁",
                                "expected_response_contains": ["任务已完成"],
                                "fixture": {
                                    "plan": {"tasks": []},
                                    "preference_candidates": [
                                        {
                                            "preference_key": "preferred_transport",
                                            "value": "train"
                                        }
                                    ]
                                }
                            },
                            {
                                "user_id": "user-a",
                                "session_id": "a-2",
                                "query": "查南京到上海的票",
                                "expected_response_contains": ["任务已完成"],
                                "fixture": {
                                    "plan": {
                                        "departure": "南京",
                                        "destination": "上海",
                                        "date": "2026-09-10",
                                        "tasks": ["ticket"]
                                    }
                                }
                            },
                            {
                                "user_id": "user-b",
                                "session_id": "b-1",
                                "query": "查南京到上海的票",
                                "expected_response_contains": ["任务已完成"],
                                "fixture": {
                                    "plan": {
                                        "departure": "南京",
                                        "destination": "上海",
                                        "date": "2026-09-10",
                                        "tasks": ["ticket"]
                                    }
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = root / "reports"

            with patch("builtins.print"):
                main(
                    [
                        "--mode",
                        "offline",
                        "--dataset",
                        str(dataset),
                        "--output",
                        str(output),
                    ]
                )

            summary_path = next(output.glob("*-offline-summary.json"))
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["memory_retrieval_accuracy"], 1.0)
            self.assertEqual(payload["summary"]["preference_application_accuracy"], 1.0)
            self.assertEqual(payload["summary"]["cross_user_leakage_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
