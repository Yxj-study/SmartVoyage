#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: weather_server.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/4
描述: 
"""
import json
import asyncio
import logging
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from langchain.agents import create_agent
from langchain_mcp_adapters.tools import load_mcp_tools
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from SmartVoyage.config import Config
from datetime import datetime
import pytz

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
table_schema_string = """  # 定义天气数据表的SQL schema字符串，用于Prompt上下文
CREATE TABLE IF NOT EXISTS weather_data (
id INT AUTO_INCREMENT PRIMARY KEY,
city VARCHAR(50) NOT NULL COMMENT '城市名称',
fx_date DATE NOT NULL COMMENT '预报日期',
sunrise TIME COMMENT '日出时间',
sunset TIME COMMENT '日落时间',
moonrise TIME COMMENT '月升时间',
moonset TIME COMMENT '月落时间',
moon_phase VARCHAR(20) COMMENT '月相名称',
moon_phase_icon VARCHAR(10) COMMENT '月相图标代码',
temp_max INT COMMENT '最高温度',
temp_min INT COMMENT '最低温度',
icon_day VARCHAR(10) COMMENT '白天天气图标代码',
text_day VARCHAR(20) COMMENT '白天天气描述',
icon_night VARCHAR(10) COMMENT '夜间天气图标代码',
text_night VARCHAR(20) COMMENT '夜间天气描述',
wind360_day INT COMMENT '白天风向360角度',
wind_dir_day VARCHAR(20) COMMENT '白天风向',
wind_scale_day VARCHAR(10) COMMENT '白天风力等级',
wind_speed_day INT COMMENT '白天风速 (km/h)',
wind360_night INT COMMENT '夜间风向360角度',
wind_dir_night VARCHAR(20) COMMENT '夜间风向',
wind_scale_night VARCHAR(10) COMMENT '夜间风力等级',
wind_speed_night INT COMMENT '夜间风速 (km/h)',
precip DECIMAL(5,1) COMMENT '降水量 (mm)',
uv_index INT COMMENT '紫外线指数',
humidity INT COMMENT '相对湿度 (%)',
pressure INT COMMENT '大气压强 (hPa)',
vis INT COMMENT '能见度 (km)',
cloud INT COMMENT '云量 (%)',
update_time DATETIME COMMENT '数据更新时间',
UNIQUE KEY unique_city_date (city, fx_date)
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='天气数据表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的天气SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于weather_data表生成SELECT语句。
- 如果用户需要查天气，则至少需要城市和时间信息。如果对话历史中缺乏必要的信息，可以向其追问，输出格式为json格式，如示例所示；如果对话历史中信息齐全，则输出纯SQL即可。
- 如果用户问与天气无关的问题，则模仿最后2个示例回复即可。


示例：
- 对话: user: 北京 2025-07-30
输出: SELECT city, fx_date, temp_max, temp_min, text_day, text_night, humidity, wind_dir_day, precip FROM weather_data WHERE city = '北京' AND fx_date = '2025-07-30'
- 对话: user: 上海未来3天的天气
输出: SELECT city, fx_date, temp_max, temp_min, text_day, text_night, humidity, wind_dir_day, precip FROM weather_data WHERE city = '上海' AND fx_date BETWEEN '2025-07-30' AND '2025-08-01' ORDER BY fx_date

- 对话: user: 北京的天气
输出: {{"status": "input_required", "message": "请提供具体的需要查询的日期，例如 '2025-07-30'。"}}
- 对话: user: 今天
assistant: 请提供城市。
user: 北京
输出: SELECT city, fx_date, temp_max, temp_min, text_day, text_night, humidity, wind_dir_day, precip FROM weather_data WHERE city = '北京' AND fx_date = '2025-07-30'
- 对话: user: 北京明天的天气\nassistant: 多云。\nuser: 后天呢
输出: SELECT city, fx_date, temp_max, temp_min, text_day, text_night, humidity, wind_dir_day, precip FROM weather_data WHERE city = '北京' AND fx_date = '2025-08-01'

- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供城市和日期，例如 '北京 2025-07-30'。"}}
- 对话: user: 今天有什么好吃的
输出: {{"status": "input_required", "message": "请提供天气相关查询，包括城市和日期。"}}

weather_data表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)



# 定义查询函数
async def get_weather(sql):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8002/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("query_weather", {"sql": sql})
                    result_data = json.loads(result) if isinstance(result, str) else result
                    logger.info(f"天气查询结果：{result_data}")
                    return result_data.content[0].text
                except Exception as e:
                    logger.error(f"天气 MCP 测试出错：{str(e)}")
                    return {"status": "error", "message": f"天气 MCP 查询出错：{str(e)}"}
    except Exception as e:
        logger.error(f"连接或会话初始化时发生错误: {e}")
        return {"status": "error", "message": "连接或会话初始化时发生错误"}


async def get_amap_weather(conversation: str):
    """优先通过高德官方 MCP 获取实时天气，失败时返回 None 触发本地兜底。"""
    if not conf.amap_maps_api_key:
        return None

    # 高德 Streamable HTTP 将 Key 放在查询参数中，禁止底层客户端记录完整 URL。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)

    server_url = f"https://mcp.amap.com/mcp?key={conf.amap_maps_api_key}"
    try:
        async with streamablehttp_client(server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await load_mcp_tools(session)
                weather_tools = [tool for tool in tools if tool.name == "maps_weather"]
                if not weather_tools:
                    logger.warning("高德 MCP 未提供 maps_weather 工具，回退本地天气库")
                    return None

                current_date = datetime.now(
                    pytz.timezone("Asia/Shanghai")
                ).strftime("%Y-%m-%d")
                agent = create_agent(
                    model=llm,
                    tools=weather_tools,
                    system_prompt=(
                        f"你是旅行天气助手，当前日期是 {current_date}。"
                        "必须调用 maps_weather 查询用户指定城市，再根据用户要求的日期"
                        "从预报中选择对应结果。使用简洁中文回答；不要编造工具未返回的数据。"
                    ),
                )
                response = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": conversation}]}
                )
                content = response["messages"][-1].content
                if isinstance(content, str):
                    return content
                return json.dumps(content, ensure_ascii=False)
    except Exception as exc:
        logger.warning(
            "高德 MCP 天气查询失败，回退本地天气库: %s",
            type(exc).__name__,
        )
        return None

# Agent卡片定义
agent_card = AgentCard(
    name="WeatherQueryAssistant",
    description="基于LangChain提供天气查询服务的助手",
    url="http://localhost:5005",
    version="1.0.0",
    capabilities={"streaming": True, "memory": True},  # 设置能力：支持流式和内存
    skills=[  # 定义技能列表
        AgentSkill(
            name="execute weather query",
            description="执行天气查询，返回天气数据库结果，支持自然语言输入",
            examples=["北京 2025-07-30 天气", "上海未来5天", "今天天气如何"]
        )
    ]
)

# 天气查询服务器类
class WeatherQueryServer(A2AServer):
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
            if output.startswith('{'):  # 检查输出是否以JSON开头
                return json.loads(output)
            return {"status": "sql", "sql": output}
        except Exception as e:
            logger.error(f"SQL生成失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供城市和日期。"}  # 返回追问JSON

    # 处理任务：提取输入，生成SQL，调用MCP，格式化结果
    def handle_task(self, task):
        # 1 提取输入
        content = (task.message or {}).get("content", {})  # 从消息中获取内容
        # 提取conversation，即客户端发起的任务中的query语句
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        try:
            # 2 优先调用高德官方 MCP 查询实时天气。
            amap_result = asyncio.run(get_amap_weather(conversation))
            if amap_result:
                task.artifacts = [{"parts": [{"type": "text", "text": amap_result}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
                return task

            # 3 高德不可用时，执行原有 SQL + 本地 MySQL 天气兜底。
            gen_result = self.generate_sql_query(conversation)
            # 检查是否需要追问，如果是则添加追问消息后返回任务
            if gen_result["status"] == "input_required":
                # 追问逻辑，这里是指在无法正常生成sql时，设置任务状态为输入所需，添加追问消息
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": gen_result["message"]}})
                return task

            # 否则则提取SQL查询，并进行MCP调用
            sql_query = gen_result["sql"]  #
            logger.info(f"生成的SQL查询: {sql_query}")

            # 4 调用本地 MCP
            weather_result = asyncio.run(get_weather(sql_query))

            # 5 格式化结果
            response = json.loads(weather_result) if isinstance(weather_result, str) else weather_result
            logger.info(f"MCP 返回: {response}")
            # 检查响应状态
            if response.get("status") == "success":
                data = response.get("data", [])  # 提取数据列表
                response_text = "\n".join([
                                              f"{d['city']} {d['fx_date']}: {d['text_day']}（夜间 {d['text_night']}），温度 {d['temp_min']}-{d['temp_max']}°C，湿度 {d['humidity']}%，风向 {d['wind_dir_day']}，降水 {d['precip']}mm"
                                              for d in data])  # 格式化每个数据项为友好文本，连接成多行

                # 设置任务产物为文本部分，并设置任务状态为完成
                task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            elif response.get("status") == "no_data":
                response_text = response.get("message", "请重新输入查询的城市和日期。")

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
    # 实例化天气查询服务器
    weather_server = WeatherQueryServer()
    # 打印服务器信息
    print("\n=== 服务器信息 ===")
    print(f"名称: {weather_server.agent_card.name}")
    print(f"描述: {weather_server.agent_card.description}")
    print("\n技能:")
    for skill in weather_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(weather_server, host="127.0.0.1", port=5005)
