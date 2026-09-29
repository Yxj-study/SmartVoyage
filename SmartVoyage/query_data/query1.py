#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: query1.py
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


# 票务服务类
class TicketService:  # 定义票务服务类，封装数据库操作逻辑
    def __init__(self):  # 初始化方法，建立数据库连接
        # 连接数据库
        self.conn = mysql.connector.connect(
            host=conf.host,
            user=conf.user,
            password=conf.password,
            database=conf.database,
            autocommit=True,
            charset="utf8mb4",
            use_unicode=True,
        )

    # 定义执行SQL查询方法，输入SQL字符串，返回JSON字符串
    def execute_query(self, sql: str) -> str:
        try:
            sql = validate_read_only_query(
                sql,
                frozenset(
                    {"train_tickets", "flight_tickets", "concert_tickets"}
                ),
            )
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
            return json.dumps({"status": "success", "data": results} if results else {"status": "no_data",
                                                                                      "message": "未找到票务数据，请确认查询条件。"},
                              cls=DateEncoder, ensure_ascii=False)
        except Exception as e:
            logger.error(f"票务查询错误: {str(e)}")
            # 返回错误JSON响应
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
