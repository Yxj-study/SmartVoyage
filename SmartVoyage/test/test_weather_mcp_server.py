#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_weather_mcp_server.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/4
描述: 
"""
import asyncio
import json

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# 定义服务器地址
server_url = "http://127.0.0.1:8002/mcp"

async def test_weather_mcp():
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client(server_url) as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    print("会话初始化成功，可以开始调用工具。")

                    # 从 session 自动获取 MCP server 提供的工具列表。
                    tools = await load_mcp_tools(session)
                    print(f"tools-->{tools}")

                    # 测试1: 查询指定日期天气
                    sql = "SELECT * FROM weather_data WHERE city = '西安' AND fx_date = '2026-02-04'"
                    result = await session.call_tool("query_weather", {"sql": sql})
                    print(11111,result)
                    # meta=None
                    # content=[
                    #   TextContent(
                    #       type='text',
                    #       text='{
                    #           "status": "success",
                    #           "data": [{"id": 1, "city": "西安", "fx_date": "2026-02-04", "sunrise": "7:21:00", "sunset": "17:37:00",
                    #           "moonrise": "20:21:00", "moonset": "8:41:00", "moon_phase": "亏凸月", "moon_phase_icon": "805",
                    #           "temp_max": 12, "temp_min": -2, "icon_day": "100", "text_day": "晴", "icon_night": "150",
                    #           "text_night": "晴", "wind360_day": 225, "wind_dir_day": "西南风", "wind_scale_day": "1-3",
                    #           "wind_speed_day": 3, "wind360_night": 0, "wind_dir_night": "北风", "wind_scale_night": "1-3",
                    #           "wind_speed_night": 16, "precip": 0.0, "uv_index": 3, "humidity": 29, "pressure": 1016, "vis": 25,
                    #           "cloud": 0, "update_time": "2026-02-04 11:13:00"}]
                    #           }',
                    #       annotations=None,
                    #       meta=None)]
                    #  structuredContent={
                    #       'result': '{
                    #           "status": "success",
                    #           "data": [{"id": 1, "city": "西安", "fx_date": "2026-02-04", "sunrise": "7:21:00", "sunset": "17:37:00",
                    #           "moonrise": "20:21:00", "moonset": "8:41:00", "moon_phase": "亏凸月", "moon_phase_icon": "805",
                    #           "temp_max": 12, "temp_min": -2, "icon_day": "100", "text_day": "晴", "icon_night": "150",
                    #           "text_night": "晴", "wind360_day": 225, "wind_dir_day": "西南风", "wind_scale_day": "1-3",
                    #           "wind_speed_day": 3, "wind360_night": 0, "wind_dir_night": "北风", "wind_scale_night": "1-3",
                    #           "wind_speed_night": 16, "precip": 0.0, "uv_index": 3, "humidity": 29, "pressure": 1016, "vis": 25,
                    #           "cloud": 0, "update_time": "2026-02-04 11:13:00"}]}'
                    #   }
                    #   isError=False

                    print(22222,isinstance(result, str))
                    # False
                    result_data = json.loads(result) if isinstance(result, str) else result
                    print(f"指定日期天气结果：{result_data}")

                    # 指定日期天气结果：
                    # meta=None
                    # content=[
                    #   TextContent(type='text',
                    #   text='{
                    #       "status": "success",
                    #       "data": [{"id": 1, "city": "西安", "fx_date": "2026-02-04", "sunrise": "7:21:00", "sunset": "17:37:00",
                    #       "moonrise": "20:21:00", "moonset": "8:41:00", "moon_phase": "亏凸月", "moon_phase_icon": "805",
                    #       "temp_max": 12, "temp_min": -2, "icon_day": "100", "text_day": "晴", "icon_night": "150",
                    #       "text_night": "晴", "wind360_day": 225, "wind_dir_day": "西南风", "wind_scale_day": "1-3",
                    #       "wind_speed_day": 3, "wind360_night": 0, "wind_dir_night": "北风", "wind_scale_night": "1-3",
                    #       "wind_speed_night": 16, "precip": 0.0, "uv_index": 3, "humidity": 29, "pressure": 1016,
                    #       "vis": 25, "cloud": 0, "update_time": "2026-02-04 11:13:00"}]
                    #       }',
                    #       annotations=None,
                    #       meta=None)
                    #  ]

                    #   structuredContent={'result':
                    #       '{"status": "success",
                    #       "data": [{"id": 1, "city": "西安", "fx_date": "2026-02-04", "sunrise": "7:21:00", "sunset": "17:37:00",
                    #       "moonrise": "20:21:00", "moonset": "8:41:00", "moon_phase": "亏凸月", "moon_phase_icon": "805",
                    #       "temp_max": 12, "temp_min": -2, "icon_day": "100", "text_day": "晴", "icon_night": "150",
                    #       "text_night": "晴", "wind360_day": 225, "wind_dir_day": "西南风", "wind_scale_day": "1-3",
                    #       "wind_speed_day": 3, "wind360_night": 0, "wind_dir_night": "北风", "wind_scale_night": "1-3",
                    #       "wind_speed_night": 16, "precip": 0.0, "uv_index": 3, "humidity": 29, "pressure": 1016,
                    #       "vis": 25, "cloud": 0, "update_time": "2026-02-04 11:13:00"}]}'
                    #   } isError=False

                    # 测试2: 查询未来3天天气
                    # sql_range = "SELECT * FROM weather_data WHERE city = '西安' AND fx_date BETWEEN '2026-02-04' AND '2026-02-06'"
                    # result_range = await session.call_tool("query_weather", {"sql": sql_range})
                    # result_range_data = json.loads(result_range) if isinstance(result_range, str) else result_range
                    # print(f"天气范围查询结果：{result_range_data}")
                except Exception as e:
                    print(f"天气 MCP 测试出错：{str(e)}")
    except Exception as e:
        print(f"连接或会话初始化时发生错误: {e}")
        print("请确认服务端脚本已启动并运行在 http://127.0.0.1:8002/mcp")


if __name__ == "__main__":
    asyncio.run(test_weather_mcp())