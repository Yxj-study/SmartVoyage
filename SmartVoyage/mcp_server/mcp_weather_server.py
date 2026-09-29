#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: mcp_weather_server.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/4
描述:
"""
import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from SmartVoyage.config import Config
from SmartVoyage.create_logger import logger
from SmartVoyage.query_data.sql_guard import validate_read_only_query
from SmartVoyage.utils.format import DateEncoder, default_encoder

conf = Config()

# 天气服务类
class WeatherService:  # 定义天气服务类，封装数据库操作逻辑
    def __init__(self):
        # 连接数据库
        self.conn = mysql.connector.connect(
            host=conf.host,
            user=conf.user,
            password=conf.password,
            database=conf.database
        )

    # 定义执行SQL查询方法，输入SQL字符串，返回JSON字符串
    def execute_query(self, sql: str) -> str:
        try:
            sql = validate_read_only_query(sql, frozenset({"weather_data"}))
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            # 格式化结果
            for result in results:  # 遍历每个结果字典
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):  # 检查值是否为特殊类型
                        result[key] = default_encoder(value)  # 使用自定义编码器格式化该值
            # 序列化为JSON，如果有结果返回success，否则no_data；使用DateEncoder，非ASCII不转义
            return json.dumps({"status": "success", "data": results} if results else {"status": "no_data", "message": "未找到天气数据，请确认城市和日期。"}, cls=DateEncoder, ensure_ascii=False)
        except Exception as e:
            logger.error(f"天气查询错误: {str(e)}")
            # 返回错误JSON响应
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# 创建天气MCP服务器
def create_weather_mcp_server():
    # 创建FastMCP实例
    weather_mcp = FastMCP(name="WeatherTools",
                         instructions="天气查询工具，基于 weather_data 表。",
                         log_level="ERROR",
                         host="127.0.0.1", port=8002)

    # 实例化天气服务对象
    service = WeatherService()

    @weather_mcp.tool(
        name="query_weather",
        description="查询天气数据，输入 SQL，如 'SELECT * FROM weather_data WHERE city = \"北京\" AND fx_date = \"2025-07-30\"'"
    )
    def query_weather(sql: str) -> str:
        logger.info(f"执行天气查询: {sql}")
        return service.execute_query(sql)

    # 打印服务器信息
    logger.info("=== 天气MCP服务器信息 ===")
    logger.info(f"名称: {weather_mcp.name}")
    logger.info(f"描述: {weather_mcp.instructions}")

    # 运行服务器
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8002/mcp")
        weather_mcp.run(transport="streamable-http")  # 使用 streamable-http 传输方式
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == '__main__':
    create_weather_mcp_server()



# if __name__ == "__main__":
#     service = WeatherService()
#     sql = "SELECT * FROM weather_data WHERE city='西安' limit 2"
#     print(service.execute_query(sql))

    # {"status": "success", "data": results}

    # {"status": "success",
    # "data":
    #   [
    #   {"id": 1, "city": "西安", "fx_date": "2026-02-04", "sunrise": "7:21:00",
    #       "sunset": "17:37:00", "moonrise": "20:21:00", "moonset": "8:41:00",
    #       "moon_phase": "亏凸月", "moon_phase_icon": "805", "temp_max": 12,
    #       "temp_min": -2, "icon_day": "100", "text_day": "晴", "icon_night": "150",
    #       "text_night": "晴", "wind360_day": 225, "wind_dir_day": "西南风", "wind_scale_day": "1-3",
    #       "wind_speed_day": 3, "wind360_night": 0, "wind_dir_night": "北风", "wind_scale_night": "1-3",
    #       "wind_speed_night": 16, "precip": 0.0, "uv_index": 3, "humidity": 29, "pressure": 1016,
    #       "vis": 25, "cloud": 0, "update_time": "2026-02-04 11:13:00"},
    #   {"id": 2, "city": "西安", "fx_date": "2026-02-05", "sunrise": "7:20:00", "sunset": "17:38:00",
    #       "moonrise": "21:26:00", "moonset": "9:03:00", "moon_phase": "亏凸月", "moon_phase_icon": "805",
    #       "temp_max": 3, "temp_min": -7, "icon_day": "101", "text_day": "多云", "icon_night": "151",
    #       "text_night": "多云", "wind360_day": 0, "wind_dir_day": "北风", "wind_scale_day": "1-3",
    #       "wind_speed_day": 16, "wind360_night": 45, "wind_dir_night": "东北风", "wind_scale_night": "1-3",
    #       "wind_speed_night": 3, "precip": 0.0, "uv_index": 2, "humidity": 19, "pressure": 1030, "vis": 25,
    #       "cloud": 0, "update_time": "2026-02-04 11:13:00"}
    #   ]
    #  }
