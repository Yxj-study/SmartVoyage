#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_order_agent_server.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/6
描述: 
"""
import asyncio
import uuid

from python_a2a import A2AClient, Message, TextContent, MessageRole, Task

from SmartVoyage.config import Config
from SmartVoyage.create_logger import logger

conf = Config()


def main():
    # 初始化票务客户端
    ticket_client = A2AClient("http://localhost:5007")

    # 获取票务代理信息
    try:
        logger.info("获取票务预定助手信息")
        logger.info(f"名称: {ticket_client.agent_card.name}")
        logger.info(f"描述: {ticket_client.agent_card.description}")
        logger.info(f"版本: {ticket_client.agent_card.version}")
        if ticket_client.agent_card.skills:
            logger.info("支持技能:")
            for skill in ticket_client.agent_card.skills:
                logger.info(f"- {skill.name}: {skill.description}")
                if skill.examples:
                    logger.info(f"  示例: {', '.join(skill.examples)}")
    except Exception as e:
        logger.error(f"无法获取票务助手信息: {str(e)}")

    # 交互循环
    while True:
        user_input = input("输入您的票务预定需求（输入 'exit' 退出）：")
        if user_input.lower() == 'exit':
            break

        try:
            query = user_input.strip()
            logger.info(f"用户查询 (票务): {query}")

            # 发送查询
            logger.info("正在查询数据...")
            message_ticket = Message(content=TextContent(text=query), role=MessageRole.USER)
            task_ticket = Task(id="task-" + str(uuid.uuid4()), message=message_ticket.to_dict())

            # 发送任务并获取最终结果
            ticket_result_task = asyncio.run(ticket_client.send_task_async(task_ticket))
            logger.info(f"原始响应: {ticket_result_task}")

            # 打印输出
            if ticket_result_task.status.state == 'completed':
                print(ticket_result_task.artifacts[0]["parts"][0]["text"])
            else:
                print(ticket_result_task.status.message['content']['text'])
        except Exception as e:
            error_message = f"查询失败: {str(e)}"
            logger.error(error_message)


if __name__ == "__main__":
    print("票务预定agent server查询客户端测试脚本")
    main()