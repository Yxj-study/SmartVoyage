#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import uuid

from langchain_openai import ChatOpenAI
from langgraph.types import Command
from python_a2a import AgentNetwork

from SmartVoyage.config import Config
from SmartVoyage.coordinator.graph import create_production_coordinator
from SmartVoyage.coordinator.ui import format_confirmation, interpret_graph_result


def parse_confirmation(value):
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "确认", "确定", "是"}:
        return True
    if normalized in {"no", "n", "取消", "否"}:
        return False
    return None


def build_agent_network():
    urls = {
        "WeatherQueryAssistant": "http://localhost:5005",
        "TicketQueryAssistant": "http://localhost:5006",
        "TicketOrderAssistant": "http://localhost:5007",
    }
    network = AgentNetwork(name="Travel Assistant Network")
    for name, url in urls.items():
        network.add(name, url)
    return network, urls


def display_agent_cards(network, urls):
    print("\nAgent Cards:")
    for name in network.agents.keys():
        print(f"\n--- {name} ---")
        try:
            card = network.get_agent_card(name)
            print(f"技能: {card.skills}")
            print(f"描述: {card.description}")
        except Exception as exc:
            print(f"Agent Card 暂时不可用: {exc}")
        print(f"地址: {urls[name]}")


def display_trace(trace):
    if not trace:
        return
    print("\n协作轨迹:")
    for event in trace:
        item = event.model_dump() if hasattr(event, "model_dump") else event
        print(f"- [{item.get('status', '')}] {item.get('label', '')}: {item.get('summary', '')}")


def build_runtime():
    config = Config()
    network, urls = build_agent_network()
    llm = ChatOpenAI(
        model=config.model_name,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=0.1,
    )
    coordinator = create_production_coordinator(network, llm)
    return coordinator, network, urls


def run_cli():
    coordinator, network, urls = build_runtime()
    thread_id = str(uuid.uuid4())
    graph_config = {"configurable": {"thread_id": thread_id}}
    messages = []

    print("SmartVoyage LangGraph Supervisor 多智能体旅行助手")
    print("输入旅行问题；输入 cards 查看 Agent；输入 quit 退出。")
    display_agent_cards(network, urls)

    while True:
        prompt = input("\n请输入您的问题: ").strip()
        if not prompt:
            continue
        if prompt.lower() == "quit":
            print("感谢使用 SmartVoyage，再见！")
            break
        if prompt.lower() == "cards":
            display_agent_cards(network, urls)
            continue

        messages.append({"role": "user", "content": prompt})
        try:
            result = coordinator.invoke(
                {"user_query": prompt, "messages": messages[-6:]},
                config=graph_config,
            )
            interpreted = interpret_graph_result(result)
            display_trace(interpreted["trace"])

            while interpreted["pending_confirmation"]:
                print("\n" + format_confirmation(interpreted["pending_confirmation"]))
                decision = None
                while decision is None:
                    value = input("确认预订吗？(yes/no): ")
                    decision = parse_confirmation(value)
                    if decision is None:
                        print("请输入 yes/确认 或 no/取消。")
                result = coordinator.invoke(Command(resume=decision), config=graph_config)
                interpreted = interpret_graph_result(result)
                display_trace(interpreted["trace"])

            response = interpreted["response"] or "任务已完成。"
            messages.append({"role": "assistant", "content": response})
            print(f"\n助手回复：\n{response}")
        except Exception as exc:
            print(f"\n处理失败：{exc}")


if __name__ == "__main__":
    run_cli()
