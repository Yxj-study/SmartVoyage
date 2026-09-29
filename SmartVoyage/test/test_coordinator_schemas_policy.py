import unittest

from pydantic import ValidationError

from SmartVoyage.coordinator.policy import apply_ticket_policy, is_good_weather
from SmartVoyage.coordinator.schemas import (
    FilterCondition,
    SortRule,
    TicketCandidate,
    WeatherResult,
)


class CoordinatorPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tickets = [
            TicketCandidate(
                ticket_type="flight",
                departure="长沙",
                destination="北京",
                departure_time="2026-08-19T20:10:00",
                arrival_time="2026-08-19T22:30:00",
                number="CZ3127",
                seat_class="经济舱",
                price="880.00",
                remaining_tickets=12,
            ),
            TicketCandidate(
                ticket_type="flight",
                departure="长沙",
                destination="北京",
                departure_time="2026-08-19T21:00:00",
                arrival_time="2026-08-19T23:20:00",
                number="HU7636",
                seat_class="经济舱",
                price="760.00",
                remaining_tickets=4,
            ),
            TicketCandidate(
                ticket_type="flight",
                departure="长沙",
                destination="北京",
                departure_time="2026-08-19T17:00:00",
                arrival_time="2026-08-19T19:20:00",
                number="CA1350",
                seat_class="经济舱",
                price="650.00",
                remaining_tickets=10,
            ),
        ]

    def test_price_and_time_filters_choose_cheapest_evening_flight(self):
        result = apply_ticket_policy(
            self.tickets,
            filters=[
                FilterCondition(field="price", operator="lt", value=1000),
                FilterCondition(
                    field="departure_time",
                    operator="gte",
                    value="2026-08-19T18:00:00",
                ),
                FilterCondition(field="remaining_tickets", operator="gt", value=0),
            ],
            sorts=[SortRule(field="price", order="asc")],
        )

        self.assertEqual([ticket.number for ticket in result], ["HU7636", "CZ3127"])

    def test_unknown_policy_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            FilterCondition(field="__class__", operator="eq", value="x")

    def test_weather_policy_accepts_clear_weather(self):
        weather = WeatherResult(
            city="北京",
            weather="晴",
            wind_scale=3,
            precipitation=0,
        )

        self.assertTrue(is_good_weather(weather))

    def test_weather_policy_rejects_thunderstorm(self):
        weather = WeatherResult(
            city="北京",
            weather="雷阵雨",
            wind_scale=2,
            precipitation=8,
        )

        self.assertFalse(is_good_weather(weather))

    def test_weather_result_accepts_amap_normalized_aliases(self):
        weather = WeatherResult.model_validate(
            {
                "city": "北京",
                "date": "2026-08-19",
                "weather_day": "晴",
                "wind_level": "1-3级",
            }
        )

        self.assertEqual(weather.weather, "晴")
        self.assertEqual(weather.wind_scale, 3)


if __name__ == "__main__":
    unittest.main()
