#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SmartVoyage 项目配置。敏感信息通过环境变量传入。"""

import os

from dotenv import load_dotenv


project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
load_dotenv(os.path.join(project_root, ".env"))
env = "test"


class Config:
    def __init__(self):
        # 大模型配置：API Key 不再硬编码到源码。
        self.base_url = os.getenv(
            "SMARTVOYAGE_BASE_URL", "https://api.siliconflow.cn/v1"
        )
        self.api_key = os.getenv("SMARTVOYAGE_API_KEY", "")
        self.model_name = os.getenv(
            "SMARTVOYAGE_MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct"
        )
        self.amap_maps_api_key = os.getenv("AMAP_MAPS_API_KEY", "")

        # 数据库配置
        self.host = os.getenv("SMARTVOYAGE_DB_HOST", "localhost")
        self.user = os.getenv("SMARTVOYAGE_DB_USER", "root")
        self.password = os.getenv("SMARTVOYAGE_DB_PASSWORD", "")
        self.database = os.getenv("SMARTVOYAGE_DB_NAME", "travel_rag")

        self.log_file = os.path.join(project_root, "SmartVoyage4", "logs/app.log")
        self.url_123 = ""

        self.intent = {
            "weather": "WeatherQueryAssistant",
            "flight": "TicketQueryAssistant",
            "train": "TicketQueryAssistant",
            "concert": "TicketQueryAssistant",
            "order": "TicketOrderAssistant",
        }
        self.temperature = 0.1

    def get_mysql_config(self, runtime_env):
        """根据运行环境返回数据库配置。"""
        # Runtime-specific credentials are supplied through environment variables.
        return self.host, self.user, self.password, self.database


if __name__ == "__main__":
    print(Config().log_file)
    print(Config().get_mysql_config(env))
