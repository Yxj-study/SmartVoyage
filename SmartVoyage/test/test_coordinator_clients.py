import unittest
import json
from types import SimpleNamespace

from SmartVoyage.coordinator.clients import CoordinatorClients, extract_a2a_text
from SmartVoyage.coordinator.schemas import TicketCandidateList, WeatherResult


class FakeRunnable:
    def __init__(self, result):
        self.result = result

    def invoke(self, _payload):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeStructuredLlm:
    def __init__(self, weather_result, ticket_result):
        self.weather_result = weather_result
        self.ticket_result = ticket_result

    def with_structured_output(self, schema):
        if schema is WeatherResult:
            return FakeRunnable(self.weather_result)
        if schema is TicketCandidateList:
            return FakeRunnable(self.ticket_result)
        raise AssertionError(f"unexpected schema: {schema}")


class A2AClientTest(unittest.TestCase):
    def test_extract_completed_artifact(self):
        task = SimpleNamespace(
            status=SimpleNamespace(state="completed"),
            artifacts=[{"parts": [{"type": "text", "text": "航班结果"}]}],
        )

        self.assertEqual(extract_a2a_text(task), "航班结果")

    def test_extract_input_required_message(self):
        task = SimpleNamespace(
            status=SimpleNamespace(
                state="input-required",
                message={"content": {"text": "请提供日期"}},
            ),
            artifacts=[],
        )

        self.assertEqual(extract_a2a_text(task), "请提供日期")

    def test_normalize_weather_uses_structured_result(self):
        expected = WeatherResult(
            city="北京",
            weather="晴",
            wind_scale=3,
            precipitation=0,
        )
        clients = CoordinatorClients(
            network=None,
            llm=FakeStructuredLlm(
                weather_result=expected,
                ticket_result=TicketCandidateList(tickets=[]),
            ),
        )

        self.assertEqual(clients.normalize_weather("北京晴，风力3级"), expected)

    def test_normalize_amap_weather_sentence_without_llm_schema(self):
        clients = CoordinatorClients(
            network=None,
            llm=FakeStructuredLlm(
                weather_result=RuntimeError("LLM fallback must not run"),
                ticket_result=TicketCandidateList(tickets=[]),
            ),
        )

        result = clients.normalize_weather(
            "今天北京市天气预报：白天雷阵雨，晚上多云。"
            "最高温度30℃，最低温度22℃。风向西南，风力1-3级。"
        )

        self.assertEqual(result.city, "北京")
        self.assertEqual(result.weather, "雷阵雨")
        self.assertEqual(result.wind_scale, 3)
        self.assertEqual(result.temperature_max, 30)
        self.assertEqual(result.temperature_min, 22)
        self.assertGreater(result.precipitation, 0)

    def test_normalize_tickets_returns_candidate_list(self):
        expected = TicketCandidateList(
            tickets=[
                {
                    "ticket_type": "flight",
                    "departure": "长沙",
                    "destination": "北京",
                    "departure_time": "2026-08-19T21:00:00",
                    "arrival_time": "2026-08-19T23:20:00",
                    "number": "HU7636",
                    "seat_class": "经济舱",
                    "price": "760.00",
                    "remaining_tickets": 4,
                }
            ]
        )
        clients = CoordinatorClients(
            network=None,
            llm=FakeStructuredLlm(
                weather_result=WeatherResult(
                    city="北京", weather="晴", wind_scale=3, precipitation=0
                ),
                ticket_result=expected,
            ),
        )

        result = clients.normalize_tickets("HU7636，经济舱760元，余票4张")

        self.assertEqual([ticket.number for ticket in result], ["HU7636"])

    def test_normalize_ticket_agent_json_without_llm(self):
        clients = CoordinatorClients(
            network=None,
            llm=FakeStructuredLlm(
                weather_result=WeatherResult(
                    city="北京", weather="晴", wind_scale=3, precipitation=0
                ),
                ticket_result=RuntimeError("LLM fallback must not run"),
            ),
        )
        raw = json.dumps(
            {
                "status": "success",
                "data": [
                    {
                        "id": 123,
                        "departure_city": "长沙",
                        "arrival_city": "北京",
                        "departure_time": "2026-08-19 21:00:00",
                        "arrival_time": "2026-08-19 23:20:00",
                        "flight_number": "HU7636",
                        "cabin_type": "经济舱",
                        "price": 760.0,
                        "remaining_seats": 4,
                    }
                ],
            },
            ensure_ascii=False,
        )

        result = clients.normalize_tickets(raw)

        self.assertEqual(result[0].ticket_type, "flight")
        self.assertEqual(result[0].number, "HU7636")
        self.assertEqual(result[0].departure, "长沙")
        self.assertEqual(result[0].seat_class, "经济舱")

    def test_normalize_ticket_agent_formatted_lines_without_llm(self):
        clients = CoordinatorClients(
            network=None,
            llm=FakeStructuredLlm(
                weather_result=WeatherResult(
                    city="北京", weather="晴", wind_scale=3, precipitation=0
                ),
                ticket_result=RuntimeError("LLM fallback must not run"),
            ),
        )
        raw = (
            "长沙 到 北京 2026-08-19 20:10:00: 航班 CZ3127，经济舱，"
            "票价 880.0元，剩余 9 张\n"
            "长沙 到 北京 2026-08-19 21:00:00: 航班 HU7636，经济舱，"
            "票价 760.0元，剩余 4 张\n"
        )

        result = clients.normalize_tickets(raw)

        self.assertEqual([ticket.number for ticket in result], ["CZ3127", "HU7636"])
        self.assertEqual(result[1].ticket_type, "flight")
        self.assertEqual(result[1].departure, "长沙")
        self.assertEqual(result[1].destination, "北京")
        self.assertEqual(str(result[1].price), "760.0")
        self.assertEqual(result[1].remaining_tickets, 4)


if __name__ == "__main__":
    unittest.main()
