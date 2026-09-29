#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""和风天气 API 手工连通性测试。密钥只从环境变量读取。"""

import json
import os

import requests


API_KEY = os.getenv("QWEATHER_API_KEY", "")
URL = "https://m7487r6ych.re.qweatherapi.com/v7/weather/30d?location=101010100"


def main() -> None:
    if not API_KEY:
        raise SystemExit("请先通过环境变量 QWEATHER_API_KEY 配置和风天气密钥。")

    headers = {
        "X-QW-Api-Key": API_KEY,
        "Accept-Encoding": "gzip",
    }
    try:
        response = requests.get(URL, headers=headers, timeout=10)
        response.raise_for_status()
        payload = json.loads(response.text)
        print(f"request_status={payload.get('code')}")
        print(f"forecast_days={len(payload.get('daily', []))}")
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise SystemExit(f"和风天气请求失败: {type(exc).__name__}") from exc


if __name__ == "__main__":
    main()
