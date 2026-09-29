#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import uuid

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import mysql.connector
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from SmartVoyage.config import Config
from SmartVoyage.coordinator.clients import LazyAgentNetwork
from SmartVoyage.coordinator.graph import create_production_coordinator
from SmartVoyage.coordinator.ui import (
    build_thread_id,
    format_confirmation,
    interpret_graph_result,
    trace_rows,
)
from SmartVoyage.create_logger import logger
from SmartVoyage.memory.mysql_repository import MySqlPreferenceRepository


conf = Config()

st.set_page_config(
    page_title="SmartVoyage LangGraph Supervisor",
    layout="wide",
    page_icon="🧭",
)

st.markdown(
    """
<style>
.stChatMessage {
    background-color: #2c3e50 !important;
    border-radius: 12px !important;
    padding: 15px !important;
    margin-bottom: 15px !important;
}
.stChatMessage .stMarkdown,
.stChatMessage .stMarkdown p,
.stChatMessage .stMarkdown span,
.stChatMessage .stMarkdown div,
.stChatMessage .stMarkdown strong {
    color: #ffffff !important;
}
</style>
""",
    unsafe_allow_html=True,
)


def initialize_session():
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "agent_network" not in st.session_state:
        urls = {
            "WeatherQueryAssistant": "http://localhost:5005",
            "TicketQueryAssistant": "http://localhost:5006",
            "TicketOrderAssistant": "http://localhost:5007",
        }
        network = LazyAgentNetwork(urls)
        st.session_state.agent_urls = urls
        st.session_state.agent_network = network

    if "llm" not in st.session_state:
        st.session_state.llm = ChatOpenAI(
            model=conf.model_name,
            api_key=conf.api_key,
            base_url=conf.base_url,
            temperature=0.1,
        )

    if "coordinator" not in st.session_state:
        def create_memory_connection():
            return mysql.connector.connect(
                host=conf.host,
                user=conf.user,
                password=conf.password,
                database=conf.database,
                charset="utf8mb4",
                use_unicode=True,
            )

        st.session_state.preference_repository = MySqlPreferenceRepository(
            create_memory_connection
        )
        st.session_state.coordinator = create_production_coordinator(
            st.session_state.agent_network,
            st.session_state.llm,
            preference_repository=st.session_state.preference_repository,
        )
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.pending_confirmation = None
        st.session_state.latest_trace = []


def graph_config():
    return {
        "configurable": {
            "thread_id": build_thread_id(
                st.session_state.user_id,
                st.session_state.session_id,
            ),
        }
    }


def consume_graph_result(result):
    interpreted = interpret_graph_result(result)
    st.session_state.latest_trace = interpreted["trace"]
    st.session_state.pending_confirmation = interpreted["pending_confirmation"]
    response = interpreted["response"]
    if response:
        st.session_state.messages.append({"role": "assistant", "content": response})
    return response


def invoke_user_turn(prompt):
    return st.session_state.coordinator.invoke(
        {
            "user_id": st.session_state.user_id,
            "session_id": st.session_state.session_id,
            "user_query": prompt,
            "messages": st.session_state.messages[-6:],
        },
        config=graph_config(),
    )


def resume_booking(confirmed):
    return st.session_state.coordinator.invoke(
        Command(resume=confirmed),
        config=graph_config(),
    )


if "user_id" not in st.session_state:
    st.session_state.user_id = "demo-user"

with st.sidebar:
    st.subheader("本地演示身份")
    entered_user_id = st.text_input(
        "本地演示用户 ID",
        value=st.session_state.user_id,
        help="仅用于演示多用户记忆隔离，不代表已经实现登录认证。",
    ).strip()
    if entered_user_id:
        st.session_state.user_id = entered_user_id

initialize_session()

with st.sidebar:
    st.caption(f"当前 Session：{st.session_state.session_id}")
    if st.button("新建会话", width="stretch"):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.pending_confirmation = None
        st.session_state.latest_trace = []
        st.rerun()

st.title("🧭 SmartVoyage LangGraph Supervisor 多智能体旅行助手")
st.caption("Planner 拆解任务 · Supervisor 动态调度 · A2A Agent 协作 · 下单前人工确认")

chat_column, card_column = st.columns([2, 1])

with chat_column:
    st.subheader("💬 对话")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input(
        "请输入旅行问题，例如：价格低于1000元就选择最便宜的航班",
        disabled=st.session_state.pending_confirmation is not None,
    )
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        try:
            with st.spinner("Coordinator 正在规划并调度 Agent..."):
                response = consume_graph_result(invoke_user_turn(prompt))
            if response:
                with st.chat_message("assistant"):
                    st.markdown(response)
        except Exception as exc:
            logger.exception("Coordinator 处理失败")
            message = f"处理失败：{exc}"
            st.session_state.messages.append({"role": "assistant", "content": message})
            with st.chat_message("assistant"):
                st.error(message)

    if st.session_state.pending_confirmation:
        payload = st.session_state.pending_confirmation
        with st.chat_message("assistant"):
            st.markdown(format_confirmation(payload))
            confirm_column, cancel_column = st.columns(2)
            if confirm_column.button("确认预订", type="primary", width="stretch"):
                try:
                    with st.spinner("正在调用 Order Agent..."):
                        consume_graph_result(resume_booking(True))
                except Exception as exc:
                    logger.exception("恢复预订流程失败")
                    st.session_state.messages.append(
                        {"role": "assistant", "content": f"预订失败：{exc}"}
                    )
                    st.session_state.pending_confirmation = None
                st.rerun()
            if cancel_column.button("取消", width="stretch"):
                try:
                    consume_graph_result(resume_booking(False))
                except Exception as exc:
                    logger.exception("取消预订流程失败")
                    st.session_state.messages.append(
                        {"role": "assistant", "content": f"取消流程失败：{exc}"}
                    )
                    st.session_state.pending_confirmation = None
                st.rerun()

    if st.session_state.latest_trace:
        with st.expander("🔎 多智能体协作轨迹", expanded=True):
            st.dataframe(
                trace_rows(st.session_state.latest_trace),
                width="stretch",
                hide_index=True,
            )

with card_column:
    st.subheader("🛠️ Agent Card")
    st.info("Coordinator 在当前 Streamlit 进程内运行，不新增端口。")
    for agent_name in st.session_state.agent_network.agents.keys():
        agent_url = st.session_state.agent_urls.get(agent_name, "未知地址")
        with st.expander(f"Agent: {agent_name}", expanded=False):
            st.markdown(f"**地址**：{agent_url}")
            st.caption("Agent Card 状态按需加载，避免未启动服务阻塞页面。")
            if st.button(f"加载 {agent_name} Agent Card", key=f"card-{agent_name}"):
                try:
                    card = st.session_state.agent_network.get_agent_card(agent_name)
                    st.markdown(f"**技能**：{card.skills}")
                    st.markdown(f"**描述**：{card.description}")
                except Exception as exc:
                    st.warning(f"Agent Card 暂时不可用：{exc}")

st.markdown("---")
st.caption("SmartVoyage v3.0 · LangGraph Supervisor + A2A + MCP")
