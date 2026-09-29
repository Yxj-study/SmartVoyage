#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_weather_agent_server.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/4
描述: 
"""
import asyncio
import uuid

from python_a2a import A2AClient, Message, TextContent, MessageRole, Task
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from SmartVoyage.config import Config
from SmartVoyage.create_logger import logger

conf = Config()

# 初始化 LLM
llm = ChatOpenAI(
            model=conf.model_name,
            api_key=conf.api_key,
            base_url=conf.base_url,
            temperature=0.1
        )

# 天气总结提示模板
weather_prompt = ChatPromptTemplate.from_template(
    """
    您是一位天气解说员，以生动、引人入胜的风格为用户介绍天气查询结果。基于以下查询结果，生成一段总结：
    - 突出城市、日期、温度、天气描述和湿度，提及关键亮点如适宜活动。
    - 使用解说员的语气，例如“欢迎来到天气宝库！今天我们为您带来...”。
    - 如果结果为空，建议用户尝试其他查询条件。
    - 保持中文叙述，字数控制在 100-150 字。

    查询结果：
    {weather}

    总结：
    """
)

def main():
    # 初始化天气客户端
    weather_client = A2AClient("http://localhost:5005")

    # 获取天气代理信息
    try:
        logger.info("获取天气助手信息")
        logger.info(f"名称: {weather_client.agent_card.name}")
        logger.info(f"描述: {weather_client.agent_card.description}")
        logger.info(f"版本: {weather_client.agent_card.version}")
        if weather_client.agent_card.skills:
            logger.info("支持技能:")
            for skill in weather_client.agent_card.skills:
                logger.info(f"- {skill.name}: {skill.description}")
                if skill.examples:
                    logger.info(f"  示例: {', '.join(skill.examples)}")
    except Exception as e:
        logger.error(f"无法获取天气助手信息: {str(e)}")

    # 交互循环
    while True:
        user_input = input("输入您的天气查询（输入 'exit' 退出）：")
        if user_input.lower() == 'exit':
            break

        try:
            query = user_input.strip()
            logger.info(f"用户查询 (天气): {query}")

            # 发送查询
            logger.info("正在查询数据...")
            message_weather = Message(content=TextContent(text=query), role=MessageRole.USER)
            task_weather = Task(id="task-" + str(uuid.uuid4()), message=message_weather.to_dict())

            weather_result_task = asyncio.run(weather_client.send_task_async(task_weather))
            logger.info(f"原始响应: {weather_result_task}")

            # 生成 LLM 总结
            if weather_result_task.status.state == 'completed':
                try:
                    summary_chain = weather_prompt | llm
                    weather_result = weather_result_task.artifacts[0]["parts"][0]["text"]
                    summary = summary_chain.invoke({"weather": weather_result}).content.strip()
                    logger.info(f"**天气解说员总结**:\n{summary}")
                except Exception as e:
                    error_message = f"生成总结失败: {str(e)}"
                    logger.error(error_message)
            else:
                logger.info(weather_result_task.status.message['content']['text'])
        except Exception as e:
            error_message = f"查询失败: {str(e)}"
            logger.error(error_message)


if __name__ == "__main__":
    print("天气agent server查询客户端测试脚本")
    main()