import unittest

from SmartVoyage.coordinator.schemas import FilterCondition, TravelPlan
from SmartVoyage.memory.models import PreferenceCandidate, PreferenceRecord
from SmartVoyage.memory.policy import apply_preferences, validate_candidate


class MemoryPolicyTest(unittest.TestCase):
    def test_long_term_transport_fills_missing_ticket_type(self):
        plan = TravelPlan(
            tasks=["ticket"],
            departure="南京",
            destination="上海",
        )

        result = apply_preferences(
            "帮我查去上海的票",
            plan,
            [
                PreferenceRecord(
                    user_id="u1",
                    preference_key="preferred_transport",
                    value="train",
                )
            ],
        )

        self.assertEqual(result.ticket_type, "train")

    def test_current_request_overrides_long_term_transport(self):
        plan = TravelPlan(ticket_type="flight", tasks=["ticket"])

        result = apply_preferences(
            "这次坐飞机",
            plan,
            [
                PreferenceRecord(
                    user_id="u1",
                    preference_key="preferred_transport",
                    value="train",
                )
            ],
        )

        self.assertEqual(result.ticket_type, "flight")

    def test_budget_is_added_only_when_request_has_no_price_filter(self):
        preference = PreferenceRecord(
            user_id="u1",
            preference_key="max_ticket_budget",
            value=500,
        )
        missing_budget = TravelPlan(tasks=["ticket"])
        explicit_budget = TravelPlan(
            tasks=["ticket"],
            filters=[FilterCondition(field="price", operator="lte", value=800)],
        )

        filled = apply_preferences("查一下车票", missing_budget, [preference])
        unchanged = apply_preferences("预算不超过800", explicit_budget, [preference])

        self.assertEqual(len(filled.filters), 1)
        self.assertEqual(filled.filters[0].field, "price")
        self.assertEqual(filled.filters[0].operator, "lte")
        self.assertEqual(filled.filters[0].value, 500)
        self.assertEqual(len(unchanged.filters), 1)
        self.assertEqual(unchanged.filters[0].value, 800)

    def test_seat_preference_does_not_duplicate_explicit_seat_filter(self):
        plan = TravelPlan(
            ticket_type="train",
            tasks=["ticket"],
            filters=[
                FilterCondition(field="seat_class", operator="eq", value="一等座")
            ],
        )

        result = apply_preferences(
            "这次要一等座",
            plan,
            [
                PreferenceRecord(
                    user_id="u1",
                    preference_key="preferred_seat_class",
                    value="二等座",
                )
            ],
        )

        self.assertEqual(len(result.filters), 1)
        self.assertEqual(result.filters[0].value, "一等座")

    def test_unknown_preference_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持的偏好字段"):
            validate_candidate(
                PreferenceCandidate(preference_key="home_address", value="x")
            )

    def test_invalid_transport_and_budget_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "交通偏好"):
            validate_candidate(
                PreferenceCandidate(
                    preference_key="preferred_transport",
                    value="spaceship",
                )
            )
        with self.assertRaisesRegex(ValueError, "预算必须为正数"):
            validate_candidate(
                PreferenceCandidate(
                    preference_key="max_ticket_budget",
                    value=0,
                )
            )

    def test_attraction_types_are_trimmed_and_deduplicated(self):
        candidate = validate_candidate(
            PreferenceCandidate(
                preference_key="preferred_attraction_types",
                value=["历史文化", " 历史文化 ", "自然风光"],
            )
        )

        self.assertEqual(candidate.value, ["历史文化", "自然风光"])


if __name__ == "__main__":
    unittest.main()
