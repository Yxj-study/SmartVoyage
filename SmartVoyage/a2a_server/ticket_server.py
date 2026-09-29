#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: ticket_server.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/6
描述: 
"""
import json
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import pytz

from SmartVoyage.config import Config
from SmartVoyage.create_logger import logger

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)


# 数据表 schema
table_schema_string = """  # 定义票务表SQL schema字符串，用于Prompt上下文
CREATE TABLE train_tickets (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增，唯一标识每条记录',
    departure_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '出发城市（如“北京”）',
    arrival_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '到达城市（如“上海”）',
    departure_time DATETIME NOT NULL COMMENT '出发时间（如“2025-08-12 07:00:00”）',
    arrival_time DATETIME NOT NULL COMMENT '到达时间（如“2025-08-12 11:30:00”）',
    train_number VARCHAR(20) NOT NULL COMMENT '火车车次（如“G1001”）',
    seat_type VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '座位类型（如“二等座”）',
    total_seats INT NOT NULL COMMENT '总座位数（如 1000）',
    remaining_seats INT NOT NULL COMMENT '剩余座位数（如 50）',
    price DECIMAL(10, 2) NOT NULL COMMENT '票价（如 553.50）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间，自动记录插入时间',
    UNIQUE KEY unique_train (departure_time, train_number)
) COMMENT='火车票信息表';

-- 机票表
CREATE TABLE flight_tickets (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增，唯一标识每条记录',
    departure_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '出发城市（如“北京”）',
    arrival_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '到达城市（如“上海”）',
    departure_time DATETIME NOT NULL COMMENT '出发时间（如“2025-08-12 08:00:00”）',
    arrival_time DATETIME NOT NULL COMMENT '到达时间（如“2025-08-12 10:30:00”）',
    flight_number VARCHAR(20) NOT NULL COMMENT '航班号（如“CA1234”）',
    cabin_type VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '舱位类型（如“经济舱”）',
    total_seats INT NOT NULL COMMENT '总座位数（如 200）',
    remaining_seats INT NOT NULL COMMENT '剩余座位数（如 10）',
    price DECIMAL(10, 2) NOT NULL COMMENT '票价（如 1200.00）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间，自动记录插入时间',
    UNIQUE KEY unique_flight (departure_time, flight_number)
) COMMENT='航班机票信息表';

-- 演唱会票表
CREATE TABLE concert_tickets (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增，唯一标识每条记录',
    artist VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '艺人名称（如“周杰伦”）',
    city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '举办城市（如“上海”）',
    venue VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '场馆（如“上海体育场”）',
    start_time DATETIME NOT NULL COMMENT '开始时间（如“2025-08-12 19:00:00”）',
    end_time DATETIME NOT NULL COMMENT '结束时间（如“2025-08-12 22:00:00”）',
    ticket_type VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '票类型（如“VIP”）',
    total_seats INT NOT NULL COMMENT '总座位数（如 5000）',
    remaining_seats INT NOT NULL COMMENT '剩余座位数（如 100）',
    price DECIMAL(10, 2) NOT NULL COMMENT '票价（如 880.00）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间，自动记录插入时间',
    UNIQUE KEY unique_concert (start_time, artist, ticket_type)
) COMMENT='演唱会门票信息表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的票务SQL生成器，需要从对话历史（含用户的问题）中提取用户的意图以及关键信息，然后基于train_tickets、flight_tickets、concert_tickets表生成SELECT语句。
根据对话历史：
1. 提取用户的意图，意图有3种（train: 火车/高铁, flight: 机票, concert: 演唱会），输出：{{"type": "train/flight/concert"}}；如果无法识别意图，或者意图不在这3种内，则模仿最后1个示例回复即可。
2. 根据用户的意图，生成对应表的 SELECT 语句，仅查询指定字段：
- train_tickets: id, departure_city, arrival_city, departure_time, arrival_time, train_number, seat_type, price, remaining_seats
- flight_tickets: id, departure_city, arrival_city, departure_time, arrival_time, flight_number, cabin_type, price, remaining_seats
- concert_tickets: id, artist, city, venue, start_time, end_time, ticket_type, price, remaining_seats
3. 如果用户在查询票务信息时，缺少必要信息，则输出：{{"status": "input_required", "message": "请提供票务类型（如火车票、机票、演唱会）和必要信息（如城市、日期）。"}} ，如示例所示；如果对话历史中信息齐全，则输出纯SQL即可。
其中，每种意图必要的信息有：
- flight/train: 【departure_city (出发城市), arrival_city (到达城市), date (日期)】 或 【train_number/flight_number (车次)】
- concert: city (城市), artist (艺人), date (日期)。
4. 按要求输出两行数据或一行数据即可，不需要输出其他内容。


示例：
- 对话: user: 火车票 北京 上海 2025-07-31 硬卧
输出: 
{{"type": "train"}}
SELECT id, departure_city, arrival_city, departure_time, arrival_time, train_number, seat_type, price, remaining_seats FROM train_tickets WHERE departure_city = '北京' AND arrival_city = '上海' AND DATE(departure_time) = '2025-07-31' AND seat_type = '硬卧'

- 对话: user: 机票 上海 广州 2025-09-11 头等舱
输出: 
{{"type": "flight"}}
SELECT id, departure_city, arrival_city, departure_time, arrival_time, flight_number, cabin_type, price, remaining_seats FROM flight_tickets WHERE departure_city = '上海' AND arrival_city = '广州' AND DATE(departure_time) = '2025-09-11' AND cabin_type = '头等舱'

- 对话: user: 演唱会 北京 刀郎 2025-08-23 看台
输出: 
{{"type": "concert"}}
SELECT id, artist, city, venue, start_time, end_time, ticket_type, price, remaining_seats FROM concert_tickets WHERE city = '北京' AND artist = '刀郎' AND DATE(start_time) = '2025-08-23' AND ticket_type = '看台'

- 对话: user: 火车票
输出: 
{{"status": "input_required", "message": "请提供票务类型（如火车票、机票、演唱会）和必要信息（如城市、日期）。"}}

- 对话: user: 你好
输出: 
{{"status": "input_required", "message": "请提供票务类型（如火车票、机票、演唱会）和必要信息（如城市、日期）。"}} 

表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 定义查询函数
async def get_ticket_info(sql):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8001/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("query_tickets", {"sql": sql})
                    result_data = json.loads(result) if isinstance(result, str) else result
                    logger.info(f"票务查询结果：{result_data}")
                    return result_data.content[0].text
                except Exception as e:
                    logger.error(f"票务 MCP 测试出错：{str(e)}")
                    return {"status": "error", "message": f"票务 MCP 查询出错：{str(e)}"}
    except Exception as e:
        logger.error(f"连接或会话初始化时发生错误: {e}")
        return {"status": "error", "message": "连接或会话初始化时发生错误"}

# Agent 卡片定义
agent_card = AgentCard(
    name="TicketQueryAssistant",
    description="基于 LangChain 提供票务查询服务的助手",
    url="http://localhost:5006",
    version="1.0.4",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute ticket query",
            description="根据客户端提供的输入执行票务查询，返回数据库结果，支持自然语言输入",
            examples=["火车票 北京 上海 2025-07-31 硬卧", "机票 北京 上海 2025-07-31 经济舱",
                      "演唱会 北京 刀郎 2025-08-23 看台"]
        )
    ]
)


# 票务查询服务器类
class TicketQueryServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.schema = table_schema_string

    # 定义生成SQL查询方法，输入对话历史，返回SQL或追问JSON
    def generate_sql_query(self, conversation: str) -> dict:
        try:
            # 组装链
            chain = self.sql_prompt | self.llm
            # 调用链
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')  # 获取当前日期，格式化为字符串
            output = chain.invoke({"conversation": conversation, "current_date": current_date, "table_schema_string": self.schema}).content.strip()
            logger.info(f"原始 LLM 输出: {output}")

            # 处理结果，返回字典
            lines = output.split('\n')
            type_line = lines[0].strip()
            if type_line.startswith('```json'):  # 检查是否以```json开头
                type_line = lines[1].strip()  # 取下一行为类型行
                sql_lines = lines[3:-1] if lines[-1].strip() == '```' else lines[3:]  # 提取SQL行，跳过代码块标记
            else:
                sql_lines = lines[1:] if len(lines) > 1 else []  # 取剩余行为SQL行

            # 提取 type 和 SQL
            if type_line.startswith('{"type":'):  # 如果以{"type":开头
                query_type = json.loads(type_line)["type"]  # 解析并提取类型
                sql_query = ' '.join([line.strip() for line in sql_lines if line.strip() and not line.startswith('```')])  # 连接SQL行，过滤空行和代码块
                logger.info(f"分类类型: {query_type}, 生成的 SQL: {sql_query}")
                return {"status": "sql", "type": query_type, "sql": sql_query}  # 返回SQL状态字典，包括类型
            elif type_line.startswith('{"status": "input_required"'):  # 检查是否为追问JSON
                return json.loads(type_line)
            else:  # 无效格式
                logger.error(f"无效的 LLM 输出格式: {output}")
                return {"status": "input_required", "message": "无法解析查询类型或SQL，请提供更明确的信息。"}  # 返回默认追问
        except Exception as e:
            logger.error(f"SQL 生成失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供查询票务的相关信息。"}  # 返回追问JSON

    # 处理任务：提取输入，生成SQL，调用MCP，格式化结果
    def handle_task(self, task):
        # 1 提取输入
        content = (task.message or {}).get("content", {})  # 从消息中获取内容
        # 提取conversation，即客户端发起的任务中的query语句
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        try:
            # 2 基于用户问题生成SQL查询
            gen_result = self.generate_sql_query(conversation)
            # 检查是否需要追问，如果是则添加追问消息后返回任务
            if gen_result["status"] == "input_required":
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": gen_result["message"]}})
                return task

            # 否则则提取SQL查询，并进行MCP调用
            sql_query = gen_result["sql"]
            query_type = gen_result["type"]
            logger.info(f"执行 SQL 查询: {sql_query} (类型: {query_type})")

            # 3 调用MCP
            ticket_result = asyncio.run(get_ticket_info(sql_query))

            # 4 格式化结果
            response = json.loads(ticket_result) if isinstance(ticket_result, str) else ticket_result
            logger.info(f"MCP 返回: {response}")
            # 检查响应状态
            if response.get("status") == "success":
                data = response.get("data", [])  # 提取数据列表
                response_text = ""  # 初始化响应文本
                for d in data:  # 遍历每个数据项
                    if query_type == "train":  # 火车票类型
                        response_text += f"{d['departure_city']} 到 {d['arrival_city']} {d['departure_time']}: 车次 {d['train_number']}，{d['seat_type']}，票价 {d['price']}元，剩余 {d['remaining_seats']} 张\n"  # 格式化火车票文本
                    elif query_type == "flight":  # 机票类型
                        response_text += f"{d['departure_city']} 到 {d['arrival_city']} {d['departure_time']}: 航班 {d['flight_number']}，{d['cabin_type']}，票价 {d['price']}元，剩余 {d['remaining_seats']} 张\n"  # 格式化机票文本
                    elif query_type == "concert":  # 演唱会类型
                        response_text += f"{d['city']} {d['start_time']}: {d['artist']} 演唱会，{d['ticket_type']}，场地 {d['venue']}，票价 {d['price']}元，剩余 {d['remaining_seats']} 张\n"  # 格式化演唱会文本
                if not response_text:  # 检查文本是否为空
                    response_text = "无结果。如果需要其他日期，请补充。"

                # 设置任务产物为文本部分，并设置任务状态为完成
                task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            elif response.get("status") == "no_data":
                response_text = response.get("message", "请输出查询票务的详细信息。")

                # 设置任务状态为输入所需，添加追问消息
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": response_text}})
            else:
                response_text = response.get("message", "查询失败，请重试或提供更多细节。")

                # 设置任务状态为失败，添加错误信息
                task.status = TaskStatus(state=TaskState.FAILED,
                                         message={"role": "agent", "content": {"text": response_text}})
            return task
        except Exception as e:  # 捕获异常
            logger.error(f"查询失败: {str(e)}")

            # 设置任务状态为失败，添加错误信息
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent",
                                              "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}})
            return task

if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化票务查询服务器
    ticket_server = TicketQueryServer()
    # 打印服务器信息
    print("\n=== 服务器信息 ===")
    print(f"名称: {ticket_server.agent_card.name}")
    print(f"描述: {ticket_server.agent_card.description}")
    print("\n技能:")
    for skill in ticket_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(ticket_server, host="127.0.0.1", port=5006)