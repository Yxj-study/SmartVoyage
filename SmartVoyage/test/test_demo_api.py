import unittest
import base64

from fastapi.testclient import TestClient

from SmartVoyage.demo_api import create_demo_app


class FakeVisionAnalyzer:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def analyze(self, _image_data_url: str):
        if self.error:
            raise self.error
        return {
            "landmark": "中山陵",
            "city": "南京",
            "scene": "历史文化景点",
            "ocr_text": "博爱",
            "confidence": 0.94,
        }


def png_data_url() -> str:
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\nimage").decode()
    return f"data:image/png;base64,{payload}"


class DemoApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_demo_app())

    def test_health_reports_langgraph_demo(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine"], "langgraph")

    def test_weather_and_attraction_query_runs_graph(self):
        response = self.client.post(
            "/api/query",
            json={"query": "帮我查北京天气并推荐景点"},
        )
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("北京", payload["answer"])
        self.assertIn("weather", payload["completed_tasks"])
        self.assertIn("attraction", payload["completed_tasks"])
        self.assertTrue(any(item["node"] == "supervisor" for item in payload["trace"]))

    def test_weather_query_uses_injected_provider_result(self):
        def query_weather(plan):
            from SmartVoyage.coordinator.schemas import WeatherResult
            return WeatherResult(city=plan.destination or "未知", weather="多云", temperature_min=12, temperature_max=20)

        client = TestClient(create_demo_app(weather_query=query_weather))
        response = client.post("/api/query", json={"query": "帮我查北京天气"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("北京 多云", response.json()["answer"])

    def test_popular_city_attractions_come_from_the_shared_graph_dataset(self):
        response = self.client.post("/api/query", json={"query": "推荐长沙景点"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("橘子洲头", response.json()["answer"])
        self.assertIn("岳麓山", response.json()["answer"])

    def test_booking_request_stops_before_real_order(self):
        response = self.client.post(
            "/api/query",
            json={"query": "帮我预订2026年10月1日南京到上海的高铁票"},
        )
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["pending_confirmation"])
        self.assertNotIn("order", payload["completed_tasks"])

    def test_confirm_resumes_the_same_session_and_creates_only_a_demo_order(self):
        session_id = "confirm-demo-session"
        initial = self.client.post(
            "/api/query",
            json={
                "query": "帮我预订2026年10月1日南京到上海的高铁票",
                "session_id": session_id,
            },
        )
        self.assertTrue(initial.json()["pending_confirmation"])

        response = self.client.post(
            "/api/confirm",
            json={"session_id": session_id, "confirmed": True},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["pending_confirmation"])
        self.assertIn("order", payload["completed_tasks"])
        self.assertIn("演示订单", payload["answer"])

    def test_cancel_resumes_the_same_session_without_creating_an_order(self):
        session_id = "cancel-demo-session"
        self.client.post(
            "/api/query",
            json={
                "query": "帮我预订2026年10月1日南京到上海的高铁票",
                "session_id": session_id,
            },
        )

        response = self.client.post(
            "/api/confirm",
            json={"session_id": session_id, "confirmed": False},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["pending_confirmation"])
        self.assertNotIn("order", payload["completed_tasks"])
        self.assertIn("order", payload["skipped_tasks"])

    def test_image_analysis_returns_vlm_graph_and_itinerary_trace(self):
        client = TestClient(create_demo_app(vision_analyzer=FakeVisionAnalyzer()))

        response = client.post(
            "/api/analyze-image", json={"image_data_url": png_data_url()}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["vision"]["landmark"], "中山陵")
        self.assertTrue(payload["graph_facts"])
        self.assertEqual(
            [item["node"] for item in payload["trace"]],
            ["vision", "graph", "itinerary"],
        )

    def test_image_analysis_rejects_invalid_data_url(self):
        client = TestClient(create_demo_app(vision_analyzer=FakeVisionAnalyzer()))
        response = client.post(
            "/api/analyze-image", json={"image_data_url": "https://example.com/a.png"}
        )
        self.assertEqual(response.status_code, 422)

    def test_image_analysis_reports_upstream_failure_without_breaking_text_api(self):
        client = TestClient(
            create_demo_app(vision_analyzer=FakeVisionAnalyzer(RuntimeError("down")))
        )
        response = client.post(
            "/api/analyze-image", json={"image_data_url": png_data_url()}
        )
        text_response = client.post(
            "/api/query", json={"query": "帮我查北京天气并推荐景点"}
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(text_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
