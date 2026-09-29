import unittest
from unittest.mock import AsyncMock, patch

from SmartVoyage.a2a_server.order_server import execute_selected_order


class SelectedOrderTest(unittest.IsolatedAsyncioTestCase):
    async def test_selected_flight_is_forwarded_without_reselection(self):
        payload = {
            "action": "order_selected_ticket",
            "selected_ticket": {
                "ticket_type": "flight",
                "departure": "长沙",
                "destination": "北京",
                "departure_time": "2026-08-19T21:00:00",
                "arrival_time": "2026-08-19T23:20:00",
                "number": "HU7636",
                "seat_class": "经济舱",
                "price": "760.00",
                "remaining_tickets": 4,
            },
            "quantity": 1,
        }
        tool_result = {"status": "success", "message": "预定成功"}

        with patch(
            "SmartVoyage.a2a_server.order_server.call_order_tool",
            new=AsyncMock(return_value=tool_result),
        ) as order_tool:
            result = await execute_selected_order(payload)

        tool_name, arguments = order_tool.await_args.args
        self.assertEqual(result["selected_ticket"]["number"], "HU7636")
        self.assertEqual(tool_name, "order_flight")
        self.assertEqual(arguments["flight_number"], "HU7636")
        self.assertEqual(arguments["departure_date"], "2026-08-19")
        self.assertEqual(arguments["seat_type"], "经济舱")
        self.assertEqual(arguments["number"], 1)

    async def test_selected_order_rejects_missing_ticket_number(self):
        payload = {
            "action": "order_selected_ticket",
            "selected_ticket": {
                "ticket_type": "flight",
                "departure_time": "2026-08-19T21:00:00",
                "seat_class": "经济舱",
            },
            "quantity": 1,
        }

        result = await execute_selected_order(payload)

        self.assertEqual(result["status"], "error")
        self.assertIn("number", result["message"])


if __name__ == "__main__":
    unittest.main()
