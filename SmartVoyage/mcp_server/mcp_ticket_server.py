#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: mcp_ticket_server.py
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
from SmartVoyage.utils.format import DateEncoder, default_encoder
from SmartVoyage.query_data.query1 import TicketService

conf = Config()



# 创建票务MCP服务器
def create_ticket_mcp_server():
    # 创建FastMCP实例
    ticket_mcp = FastMCP(name="TicketTools",
                         instructions="票务查询工具，基于 train_tickets, flight_tickets, concert_tickets 表。只支持查询。",
                         log_level="ERROR",
                         host="127.0.0.1", port=8001)

    # 实例化票务服务对象
    service = TicketService()

    @ticket_mcp.tool(
        name="query_tickets",
        description="查询票务数据，输入 SQL，如 'SELECT * FROM train_tickets WHERE departure_city = \"北京\" AND arrival_city = \"上海\"'"
    )
    def query_tickets(sql: str) -> str:
        logger.info(f"执行票务查询: {sql}")
        return service.execute_query(sql)

    # 打印服务器信息
    logger.info("=== 票务MCP服务器信息 ===")
    logger.info(f"名称: {ticket_mcp.name}")
    logger.info(f"描述: {ticket_mcp.instructions}")

    # 运行服务器
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8001/mcp")
        ticket_mcp.run(transport="streamable-http")  # 使用 streamable-http 传输方式
    except Exception as e:
        print(f"服务器启动失败: {e}")

create_ticket_mcp_server()