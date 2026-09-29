import unittest
from datetime import date

from SmartVoyage.amap_weather import AmapMcpWeatherClient, AmapWeatherClient, WeatherServiceError
from SmartVoyage.coordinator.schemas import TravelPlan


class AmapWeatherClientTest(unittest.TestCase):
    def test_mcp_weather_parses_forecast_payload(self):
        payload = '''{"forecasts":[{"city":"北京市","casts":[{"date":"2026-09-29","dayweather":"多云","daytemp":"25","nighttemp":"16","daypower":"3"}]}]}'''
        result = AmapMcpWeatherClient("secret", call_tool=lambda _city: payload).query(
            TravelPlan(destination="北京", date=date(2026, 9, 29), tasks=["weather"])
        )
        self.assertEqual(result.city, "北京市")
        self.assertEqual(result.weather, "多云")
        self.assertEqual(result.temperature_min, 16)
        self.assertEqual(result.temperature_max, 25)

    def test_mcp_weather_parses_live_payload(self):
        payload = '''{"lives":[{"city":"上海市","weather":"小雨","temperature":"21","windpower":"≤3","reporttime":"2026-09-29 12:00:00"}]}'''
        result = AmapMcpWeatherClient("secret", call_tool=lambda _city: payload).query(
            TravelPlan(destination="上海", tasks=["weather"])
        )
        self.assertEqual(result.weather, "小雨")
        self.assertGreater(result.precipitation, 0)

    def test_mcp_weather_returns_available_multi_day_forecast_without_fabrication(self):
        payload = '''{"forecasts":[{"city":"北京市","casts":[
          {"date":"2026-09-29","dayweather":"多云","daytemp":"25","nighttemp":"16","daypower":"3"},
          {"date":"2026-09-30","dayweather":"小雨","daytemp":"22","nighttemp":"15","daypower":"4"},
          {"date":"2026-10-01","dayweather":"晴","daytemp":"24","nighttemp":"14","daypower":"3"},
          {"date":"2026-10-02","dayweather":"阴","daytemp":"21","nighttemp":"13","daypower":"3"}
        ]}]}'''
        result = AmapMcpWeatherClient("secret", call_tool=lambda _city: payload).query(
            TravelPlan(
                destination="北京",
                date=date(2026, 9, 29),
                weather_days=7,
                tasks=["weather"],
            )
        )

        self.assertIn("09-29 多云", result.weather)
        self.assertIn("09-30 小雨", result.weather)
        self.assertIn("10-02 阴", result.weather)
        self.assertIn("请求7天，当前接口返回4天", result.weather)
        self.assertEqual(result.temperature_min, 13)
        self.assertEqual(result.temperature_max, 25)
        self.assertGreater(result.precipitation, 0)

    def test_queries_geocode_then_forecast_and_selects_requested_date(self):
        calls = []

        def fetch_json(path, params):
            calls.append((path, params))
            if path.endswith("/geocode/geo"):
                return {"status": "1", "geocodes": [{"adcode": "110000"}]}
            return {
                "status": "1",
                "forecasts": [{
                    "city": "北京市",
                    "casts": [
                        {"date": "2026-09-24", "dayweather": "阴", "daytemp": "23", "nighttemp": "15", "daypower": "3"},
                        {"date": "2026-09-25", "dayweather": "小雨", "daytemp": "20", "nighttemp": "13", "daypower": "4-5"},
                    ],
                }],
            }

        result = AmapWeatherClient("secret", fetch_json=fetch_json).query(
            TravelPlan(destination="北京", date=date(2026, 9, 25), tasks=["weather"])
        )

        self.assertEqual([call[0] for call in calls], ["/v3/geocode/geo", "/v3/weather/weatherInfo"])
        self.assertEqual(result.city, "北京市")
        self.assertEqual(result.weather, "小雨")
        self.assertEqual(result.temperature_min, 13)
        self.assertEqual(result.temperature_max, 20)
        self.assertEqual(result.wind_scale, 5)
        self.assertGreater(result.precipitation, 0)

    def test_rejects_an_unresolved_city_instead_of_fabricating_sunny_weather(self):
        def fetch_json(_path, _params):
            return {"status": "1", "geocodes": []}

        with self.assertRaises(WeatherServiceError):
            AmapWeatherClient("secret", fetch_json=fetch_json).query(
                TravelPlan(destination="不存在城市", tasks=["weather"])
            )


if __name__ == "__main__":
    unittest.main()
