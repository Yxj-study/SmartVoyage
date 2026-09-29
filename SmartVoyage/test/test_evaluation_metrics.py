import unittest

from SmartVoyage.evaluation.metrics import score_cases
from SmartVoyage.evaluation.schemas import EvaluationCase, EvaluationPrediction


class EvaluationMetricTest(unittest.TestCase):
    def test_failed_predictions_remain_in_denominator(self):
        cases = [
            EvaluationCase(id="a", query="查天气", expected_tasks=["weather"]),
            EvaluationCase(id="b", query="查机票", expected_tasks=["ticket"]),
        ]
        predictions = [
            EvaluationPrediction(
                id="a", predicted_tasks=["weather"], latency_ms=10
            ),
            EvaluationPrediction(id="b", error="model timeout", latency_ms=20),
        ]

        summary = score_cases(cases, predictions)

        self.assertEqual(summary.sample_count, 2)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(summary.task_set_exact_match, 0.5)

    def test_task_micro_metrics_use_all_labels(self):
        cases = [
            EvaluationCase(
                id="a", query="查天气和票", expected_tasks=["weather", "ticket"]
            ),
            EvaluationCase(id="b", query="推荐景点", expected_tasks=["attraction"]),
        ]
        predictions = [
            EvaluationPrediction(id="a", predicted_tasks=["weather"]),
            EvaluationPrediction(
                id="b", predicted_tasks=["attraction", "order"]
            ),
        ]

        summary = score_cases(cases, predictions)

        self.assertAlmostEqual(summary.task_precision, 2 / 3)
        self.assertAlmostEqual(summary.task_recall, 2 / 3)
        self.assertAlmostEqual(summary.task_f1, 2 / 3)

    def test_slot_values_are_normalized_without_hiding_wrong_fields(self):
        cases = [
            EvaluationCase(
                id="a",
                query="查票",
                expected_tasks=["ticket"],
                expected_slots={
                    "date": "2026-09-06",
                    "max_price": "500.00",
                    "ticket_type": "train",
                },
            )
        ]
        predictions = [
            EvaluationPrediction(
                id="a",
                predicted_tasks=["ticket"],
                predicted_slots={
                    "date": "2026-09-06T00:00:00",
                    "max_price": 500,
                    "ticket_type": "flight",
                },
            )
        ]

        summary = score_cases(cases, predictions)

        self.assertAlmostEqual(summary.slot_accuracy, 2 / 3)
        self.assertEqual(summary.plan_exact_match, 0.0)

    def test_forbidden_action_makes_task_unsuccessful(self):
        cases = [
            EvaluationCase(
                id="a",
                query="只查询不要下单",
                expected_tasks=["ticket"],
                forbidden_actions=["order"],
                assess_task_success=True,
            )
        ]
        predictions = [
            EvaluationPrediction(
                id="a",
                predicted_tasks=["ticket", "order"],
                observed_actions=["ticket", "order"],
                task_success=True,
            )
        ]

        summary = score_cases(cases, predictions)

        self.assertEqual(summary.task_success_rate, 0.0)

    def test_call_success_rates_use_attempt_counts(self):
        cases = [EvaluationCase(id="a", query="调用工具")]
        predictions = [
            EvaluationPrediction(
                id="a",
                tool_calls_attempted=4,
                tool_calls_succeeded=3,
                sql_queries_attempted=2,
                sql_queries_succeeded=1,
            )
        ]

        summary = score_cases(cases, predictions)

        self.assertEqual(summary.tool_call_success_rate, 0.75)
        self.assertEqual(summary.sql_execution_success_rate, 0.5)

    def test_memory_metrics_compare_only_labeled_fields(self):
        cases = [
            EvaluationCase(
                id="a",
                query="按我的偏好查票",
                expected_preferences={
                    "preferred_transport": "train",
                    "max_ticket_budget": 500,
                },
                expected_applied_preferences={
                    "preferred_transport": "train",
                },
            )
        ]
        predictions = [
            EvaluationPrediction(
                id="a",
                retrieved_preferences={
                    "preferred_transport": "train",
                    "max_ticket_budget": 600,
                    "preferred_seat_class": "二等座",
                },
                applied_preferences={"preferred_transport": "train"},
                cross_user_checks=2,
                cross_user_leaks=0,
            )
        ]

        summary = score_cases(cases, predictions)

        self.assertEqual(summary.memory_retrieval_accuracy, 0.5)
        self.assertEqual(summary.preference_application_accuracy, 1.0)
        self.assertEqual(summary.cross_user_leakage_rate, 0.0)

    def test_non_applicable_metrics_are_none_and_latency_uses_nearest_rank(self):
        cases = [EvaluationCase(id=str(i), query="") for i in range(1, 5)]
        predictions = [
            EvaluationPrediction(id="1", latency_ms=10),
            EvaluationPrediction(id="2", latency_ms=20),
            EvaluationPrediction(id="3", latency_ms=30),
            EvaluationPrediction(id="4", latency_ms=40),
        ]

        summary = score_cases(cases, predictions)

        self.assertIsNone(summary.slot_accuracy)
        self.assertIsNone(summary.agent_selection_accuracy)
        self.assertIsNone(summary.memory_retrieval_accuracy)
        self.assertEqual(summary.latency_p50_ms, 20)
        self.assertEqual(summary.latency_p95_ms, 40)

    def test_duplicate_or_missing_prediction_ids_are_rejected(self):
        cases = [EvaluationCase(id="a", query="")]

        with self.assertRaisesRegex(ValueError, "预测 ID 必须唯一"):
            score_cases(
                cases,
                [EvaluationPrediction(id="a"), EvaluationPrediction(id="a")],
            )
        with self.assertRaisesRegex(ValueError, "预测 ID 与样本 ID 不一致"):
            score_cases(cases, [EvaluationPrediction(id="b")])


if __name__ == "__main__":
    unittest.main()
