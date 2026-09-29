#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: order_server.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/6
描述: 订票agent服务器
"""
import asyncio
import json
import uuid

from langchain_openai import ChatOpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_agent
from python_a2a import AgentCard, AgentSkill, run_server, TaskStatus, TaskState, A2AServer, A2AClient, Message, \
    TextContent, MessageRole, Task

from SmartVoyage.create_logger import logger
from SmartVoyage.config import Config

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=conf.temperature
)

# 定义订票函数
async def order_tickets(query):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8003/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()

                    # 从 session 自动获取 MCP server 提供的工具列表。
                    tools = await load_mcp_tools(session)
                    # print(f"tools-->{tools}")

                    # LangChain 1.x 使用 create_agent 创建内置工具调用循环。
                    system_prompt = (
                        "你是一个票务预定助手，能够调用工具来完成火车票、飞机票或演出票的预定。"
                        "你需要仔细分析工具需要的参数，然后从用户提供的信息中提取信息。"
                        "如果用户提供的信息不足以提取到调用工具所有必要参数，则向用户追问，"
                        "以获取该信息。不能自己编撰参数。"
                    )
                    agent = create_agent(
                        model=llm,
                        tools=tools,
                        system_prompt=system_prompt,
                    )

                    # 新版 Agent 以 messages 作为输入，并将最终回答放在最后一条消息中。
                    response = await agent.ainvoke(
                        {"messages": [{"role": "user", "content": query}]}
                    )
                    output = response["messages"][-1].content

                    return {"status": "success", "message": str(output)}
                except Exception as e:
                    logger.error(f"票务 MCP 测试出错：{str(e)}")
                    return {"status": "error", "message": f"票务 MCP 查询出错：{str(e)}"}
    except Exception as e:
        logger.error(f"连接或会话初始化时发生错误: {e}")
        return {"status": "error", "message": "连接或会话初始化时发生错误"}


async def call_order_tool(tool_name, arguments):
    """Call an order MCP tool with already validated structured arguments."""
    try:
        async with streamablehttp_client("http://127.0.0.1:8003/mcp") as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if getattr(result, "isError", False):
                    message = result.content[0].text if result.content else "订单工具执行失败"
                    return {"status": "error", "message": message}
                message = result.content[0].text if result.content else "订单工具执行成功"
                return {"status": "success", "message": message}
    except Exception as exc:
        logger.error(f"直接调用订单工具失败：{exc}")
        return {"status": "error", "message": f"订单工具调用失败：{exc}"}


def parse_selected_order_payload(text):
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("action") != "order_selected_ticket":
        return None
    return payload


async def execute_selected_order(payload):
    ticket = payload.get("selected_ticket")
    if not isinstance(ticket, dict):
        return {"status": "error", "message": "selected_ticket 必须是对象"}

    required_fields = ("ticket_type", "departure_time", "number", "seat_class")
    missing = [field for field in required_fields if not ticket.get(field)]
    if missing:
        return {
            "status": "error",
            "message": f"selected_ticket 缺少字段: {', '.join(missing)}",
        }

    try:
        quantity = int(payload.get("quantity", 1))
    except (TypeError, ValueError):
        return {"status": "error", "message": "quantity 必须是整数"}
    if not 1 <= quantity <= 9:
        return {"status": "error", "message": "quantity 必须在 1 到 9 之间"}

    departure_date = str(ticket["departure_time"]).split("T", 1)[0].split(" ", 1)[0]
    tool_specs = {
        "flight": (
            "order_flight",
            {
                "departure_date": departure_date,
                "flight_number": ticket["number"],
                "seat_type": ticket["seat_class"],
                "number": quantity,
            },
        ),
        "train": (
            "order_train",
            {
                "departure_date": departure_date,
                "train_number": ticket["number"],
                "seat_type": ticket["seat_class"],
                "number": quantity,
            },
        ),
        "concert": (
            "order_concert",
            {
                "start_date": departure_date,
                "aritist": ticket["number"],
                "venue": ticket.get("destination", ""),
                "seat_type": ticket["seat_class"],
                "number": quantity,
            },
        ),
    }
    tool_spec = tool_specs.get(ticket["ticket_type"])
    if tool_spec is None:
        return {"status": "error", "message": "不支持的 ticket_type"}
    result = await call_order_tool(*tool_spec)
    return {
        "status": result.get("status", "error"),
        "message": result.get("message", "订单工具未返回消息"),
        "selected_ticket": ticket,
        "quantity": quantity,
    }


# Agent 卡片定义
agent_card = AgentCard(
    name="TicketOrderAssistant",
    description="通过MCP提供票务预定服务的助手",
    url="http://localhost:5007",
    version="1.0.4",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute ticket order",
            description="根据客户端提供的输入执行票务预定，返回执行结果",
            examples=["北京 到 上海 2025-11-15 火车票 二等座 1张",
                      "上海 到 北京 2025-12-11 飞机票 公务舱 2张"]
        )
    ]
)


# 票务预定服务器类
class TicketOrderServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        # 初始化一个大模型
        self.llm = llm
        # 初始化一个agent客户端
        self.ticket_client = A2AClient("http://localhost:5006")

    # 处理任务：提取输入，查询余票，调用MCP，结果输出
    def handle_task(self, task):
        # 1 提取输入

        # 收到A2A任务的task:=>
        # Task(
        #   id='1b39feef-bc01-4c95-90c6-5572eb1ac850',
        #   session_id='13f0ea7a-9bce-4d89-8ce1-b57fcc73c2aa',
        #   status=TaskStatus(state=<TaskState.SUBMITTED: 'submitted'>, message=None, timestamp='2026-02-01T17:58:32.589797'),
        #   message={'content': {'text': '预订一张从北京到上海的火车票', 'type': 'text'}, 'role': 'user', 'message_id': 'fea16639-23ab-49c4-921e-a9b7566d2c34'},
        #   history=[],
        #   artifacts=[],
        #   metadata={}
        # )

        # 输出结果task:
        # Task(
        #   id='1b39feef-bc01-4c95-90c6-5572eb1ac850',
        #   session_id='13f0ea7a-9bce-4d89-8ce1-b57fcc73c2aa',
        #   status=TaskStatus(state=<TaskState.COMPLETED: 'completed'>, message=None, timestamp='2026-02-01T17:58:32.605771'),
        #   message={'content': {'text': '预订一张从北京到上海的火车票', 'type': 'text'}, 'role': 'user', 'message_id': 'fea16639-23ab-49c4-921e-a9b7566d2c34'},
        #   history=[],
        #   artifacts=[{'parts': [{'type': 'text', 'text': '上海到北京的火车票已经预订成功！  G1001,10车1A '}]}],
        #   metadata={}
        # )

        content = (task.message or {}).get("content", {})  # 从消息中获取内容
        # 提取conversation，即客户端发起的任务中的query语句
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")



        try:
            selected_payload = parse_selected_order_payload(conversation)
            if selected_payload is not None:
                order_result = asyncio.run(execute_selected_order(selected_payload))
                data = order_result.get("message", "")
                if order_result.get("status") == "success":
                    selected = order_result["selected_ticket"]
                    result = (
                        f"已按用户确认信息预订：{selected['number']}，"
                        f"{selected['seat_class']}，{order_result['quantity']}张。\n"
                        f"订票结果：{data}"
                    )
                    task.artifacts = [{"parts": [{"type": "text", "text": result}]}]
                    task.status = TaskStatus(state=TaskState.COMPLETED)
                else:
                    task.status = TaskStatus(
                        state=TaskState.FAILED,
                        message={"role": "agent", "content": {"text": data}},
                    )
                return task

            # 2 调用票务查询agent查询余票
            message_ticket = Message(content=TextContent(text=conversation), role=MessageRole.USER)
            task_ticket = Task(id="task-" + str(uuid.uuid4()), message=message_ticket.to_dict())

            # 发送任务并获取最终结果
            ticket_result_task = asyncio.run(self.ticket_client.send_task_async(task_ticket))
            logger.info(f"原始响应: {ticket_result_task}")

            # 处理结果：未查到余票信息时，则返回提示信息
            if ticket_result_task.status.state != 'completed':
                required_message = ticket_result_task.status.message['content']['text']
                logger.info(f'余票未查到：{required_message}')
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": required_message}})
                return task
            # 处理结果：查到余票信息时，进行订票
            ticket_result = ticket_result_task.artifacts[0]["parts"][0]["text"]
            logger.info(f"余票信息: {ticket_result}")

            # 3 调用MCP订票  用户问题 + \n余票信息： + 调用票查询agent的结果（剩余票务情况）
            order_result = asyncio.run(order_tickets(conversation + '\n余票信息：' + ticket_result))
            logger.info(f"MCP 返回: {order_result}")

            # 4 结果输出
            data = order_result.get("message", '')
            logger.info(f"订票结果: {data}")
            # 检查响应状态
            if order_result.get("status") == "success":
                result = '余票信息：' + ticket_result + '\n订票结果：' + data
                # 设置任务产物为文本部分，并设置任务状态为完成
                task.artifacts = [{"parts": [{"type": "text", "text": result}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            else:
                # 设置任务状态为失败，添加错误信息
                task.status = TaskStatus(state=TaskState.FAILED,
                                         message={"role": "agent", "content": {"text": data}})
            return task
        except Exception as e:  # 捕获异常
            logger.error(f"查询失败: {str(e)}")

            # 设置任务状态为失败，添加错误信息
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent", "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}})
            return task



if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化票务查询服务器
    ticket_server = TicketOrderServer()
    # 打印服务器信息
    print("\n=== 服务器信息 ===")
    print(f"名称: {ticket_server.agent_card.name}")
    print(f"描述: {ticket_server.agent_card.description}")
    print("\n技能:")
    for skill in ticket_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(ticket_server, host="127.0.0.1", port=5007)
