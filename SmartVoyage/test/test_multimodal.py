import base64
import unittest

from SmartVoyage.multimodal import (
    ImageTooLargeError,
    InvalidImageError,
    VisionUnavailableError,
    analyze_travel_image,
    TRAVEL_GRAPH,
)


def data_url(mime: str = "image/png", payload: bytes = b"\x89PNG\r\n\x1a\nimage") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


class FakeVisionAnalyzer:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or {
            "landmark": "中山陵",
            "city": "南京",
            "scene": "历史文化景点",
            "ocr_text": "博爱",
            "confidence": 0.94,
        }
        self.error = error
        self.calls = []

    def analyze(self, image_data_url: str):
        self.calls.append(image_data_url)
        if self.error:
            raise self.error
        return self.result


class MultimodalServiceTest(unittest.TestCase):
    def test_recognized_landmark_expands_graph_and_builds_itinerary(self):
        analyzer = FakeVisionAnalyzer()

        result = analyze_travel_image(data_url(), analyzer)

        self.assertEqual(result.vision.landmark, "中山陵")
        self.assertTrue(any(fact.relation == "附近" for fact in result.graph_facts))
        self.assertTrue(any("明孝陵" in step for step in result.itinerary))
        self.assertEqual([item.node for item in result.trace], ["vision", "graph", "itinerary"])
        self.assertEqual(len(analyzer.calls), 1)

    def test_unknown_landmark_returns_no_fabricated_graph_facts(self):
        analyzer = FakeVisionAnalyzer(
            {
                "landmark": "未知海岸",
                "city": "",
                "scene": "海边",
                "ocr_text": "",
                "confidence": 0.55,
            }
        )

        result = analyze_travel_image(data_url(), analyzer)

        self.assertEqual(result.graph_facts, [])
        self.assertTrue(any("未匹配到图谱实体" in step for step in result.itinerary))

    def test_ocr_can_correct_a_sign_text_misclassified_as_the_landmark(self):
        analyzer = FakeVisionAnalyzer(
            {
                "landmark": "博爱",
                "city": "南京",
                "scene": "历史建筑",
                "ocr_text": "南京 · 中山陵 · 博爱",
                "confidence": 0.98,
            }
        )

        result = analyze_travel_image(data_url(), analyzer)

        self.assertEqual(result.vision.landmark, "中山陵")
        self.assertGreater(len(result.graph_facts), 0)
        self.assertTrue(any("明孝陵" in step for step in result.itinerary))

    def test_popular_city_graph_has_at_least_fifty_landmarks_across_thirty_cities(self):
        cities = {
            fact.subject
            for facts in TRAVEL_GRAPH.values()
            for fact in facts
            if fact.relation == "包含"
        }
        self.assertGreaterEqual(len(TRAVEL_GRAPH), 50)
        self.assertGreaterEqual(len(cities), 30)

    def test_changsha_statue_alias_maps_to_orange_isle(self):
        analyzer = FakeVisionAnalyzer(
            {
                "landmark": "毛泽东青年艺术雕塑",
                "city": "长沙",
                "scene": "雕塑",
                "ocr_text": "",
                "confidence": 0.98,
            }
        )

        result = analyze_travel_image(data_url(), analyzer)

        self.assertEqual(result.vision.landmark, "橘子洲头")
        self.assertTrue(any(fact.object == "岳麓山" for fact in result.graph_facts))

    def test_analyze_uses_injected_graph_lookup(self):
        class Lookup:
            backend = "neo4j"

            def facts_for(self, landmark):
                from SmartVoyage.multimodal import GraphFact
                return [GraphFact(subject="测试城", relation="包含", object=landmark)]

        analyzer = FakeVisionAnalyzer(
            {"landmark": "中山陵", "city": "南京", "scene": "景点", "ocr_text": "", "confidence": 0.9}
        )
        result = analyze_travel_image(data_url(), analyzer, graph_lookup=Lookup())
        self.assertEqual(result.graph_facts[0].subject, "测试城")

    def test_rejects_malformed_base64(self):
        with self.assertRaises(InvalidImageError):
            analyze_travel_image("data:image/png;base64,%%%", FakeVisionAnalyzer())

    def test_rejects_unsupported_mime(self):
        with self.assertRaises(InvalidImageError):
            analyze_travel_image(data_url("image/gif"), FakeVisionAnalyzer())

    def test_rejects_payload_over_five_mib(self):
        oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)
        with self.assertRaises(ImageTooLargeError):
            analyze_travel_image(data_url(payload=oversized), FakeVisionAnalyzer())

    def test_wraps_analyzer_failure_as_unavailable(self):
        analyzer = FakeVisionAnalyzer(error=RuntimeError("upstream failed"))
        with self.assertRaises(VisionUnavailableError):
            analyze_travel_image(data_url(), analyzer)


if __name__ == "__main__":
    unittest.main()
