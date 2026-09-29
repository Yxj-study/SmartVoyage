import unittest
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from SmartVoyage.coordinator.ui import (
    build_thread_id,
    format_confirmation,
    interpret_graph_result,
)


class CoordinatorUiTest(unittest.TestCase):
    def test_interrupt_result_becomes_pending_confirmation(self):
        payload = {
            "type": "booking_confirmation",
            "ticket": {
                "number": "HU7636",
                "departure": "长沙",
                "destination": "北京",
                "departure_time": "2026-08-19T21:00:00",
                "seat_class": "经济舱",
                "price": "760.00",
            },
            "quantity": 1,
        }
        result = {
            "__interrupt__": (SimpleNamespace(value=payload),),
            "trace": [],
        }

        interpreted = interpret_graph_result(result)

        self.assertEqual(interpreted["pending_confirmation"], payload)
        self.assertIsNone(interpreted["response"])

    def test_completed_result_becomes_assistant_response(self):
        result = {
            "final_answer": "找到符合条件的航班。",
            "trace": [],
        }

        interpreted = interpret_graph_result(result)

        self.assertIsNone(interpreted["pending_confirmation"])
        self.assertEqual(interpreted["response"], "找到符合条件的航班。")

    def test_confirmation_markdown_contains_exact_ticket(self):
        payload = {
            "ticket": {
                "number": "HU7636",
                "departure": "长沙",
                "destination": "北京",
                "departure_time": "2026-08-19T21:00:00",
                "seat_class": "经济舱",
                "price": "760.00",
            },
            "quantity": 1,
        }

        markdown = format_confirmation(payload)

        self.assertIn("HU7636", markdown)
        self.assertIn("760.00", markdown)
        self.assertIn("长沙 → 北京", markdown)

    def test_app_identifies_langgraph_supervisor_mode(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"

        app = AppTest.from_file(str(app_path)).run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any("LangGraph Supervisor" in title.value for title in app.title)
        )
        self.assertTrue(
            any("本地演示用户 ID" in item.label for item in app.text_input)
        )

    def test_thread_id_separates_user_and_session(self):
        self.assertEqual(build_thread_id("user-a", "session-1"), "user-a:session-1")
        self.assertNotEqual(
            build_thread_id("user-a", "session-1"),
            build_thread_id("user-b", "session-1"),
        )
        with self.assertRaisesRegex(ValueError, "用户 ID 不能为空"):
            build_thread_id("", "session-1")


if __name__ == "__main__":
    unittest.main()
