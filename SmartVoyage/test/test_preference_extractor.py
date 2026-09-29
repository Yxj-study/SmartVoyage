import unittest

from SmartVoyage.memory.extractor import (
    PreferenceExtraction,
    create_llm_preference_extractor,
)
from SmartVoyage.memory.models import PreferenceCandidate


class FakeRunnable:
    def __init__(self, result):
        self.result = result
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.result


class FakeLlm:
    def __init__(self, result):
        self.runnable = FakeRunnable(result)

    def with_structured_output(self, _schema):
        return self.runnable


class PreferenceExtractorTest(unittest.TestCase):
    def extract(self, query, candidates):
        llm = FakeLlm(PreferenceExtraction(candidates=candidates))
        extractor = create_llm_preference_extractor(llm)
        return extractor("u1", "s1", query)

    def test_explicit_future_preference_is_stable_upsert(self):
        result = self.extract(
            "请记住我以后优先坐高铁",
            [
                PreferenceCandidate(
                    preference_key="preferred_transport",
                    value="高铁",
                )
            ],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].value, "train")
        self.assertEqual(result[0].scope, "stable")
        self.assertEqual(result[0].operation, "upsert")
        self.assertEqual(result[0].source_text, "请记住我以后优先坐高铁")

    def test_one_trip_budget_is_forced_to_temporary_scope(self):
        result = self.extract(
            "这次预算500元",
            [
                PreferenceCandidate(
                    preference_key="max_ticket_budget",
                    value=500,
                    scope="stable",
                )
            ],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].scope, "temporary")

    def test_forget_request_is_forced_to_delete(self):
        result = self.extract(
            "忘掉我的座位偏好",
            [
                PreferenceCandidate(
                    preference_key="preferred_seat_class",
                    value="二等座",
                    operation="upsert",
                )
            ],
        )

        self.assertEqual(result[0].operation, "delete")
        self.assertEqual(result[0].scope, "stable")

    def test_invalid_candidate_does_not_poison_other_memory_updates(self):
        result = self.extract(
            "以后优先高铁，也记住我的家庭住址",
            [
                PreferenceCandidate(
                    preference_key="preferred_transport",
                    value="train",
                ),
                PreferenceCandidate(preference_key="home_address", value="南京"),
            ],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].preference_key, "preferred_transport")


if __name__ == "__main__":
    unittest.main()
