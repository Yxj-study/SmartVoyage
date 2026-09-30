import asyncio
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from SmartVoyage.coordinator.clients import CoordinatorClients
from SmartVoyage.coordinator.nodes import (
    CoordinatorDependencies,
    attraction_worker_node,
    clarification_node,
    confirmation_node,
    finalizer_node,
    memory_load_node,
    memory_persist_node,
    order_worker_node,
    planner_node,
    supervisor_node,
    ticket_policy_node,
    ticket_worker_node,
    weather_policy_node,
    weather_worker_node,
)
from SmartVoyage.coordinator.schemas import (
    AttractionList,
    OrderResult,
    SupervisorDecision,
    TravelPlan,
    TravelState,
)
from SmartVoyage.memory.extractor import create_llm_preference_extractor
from SmartVoyage.travel_knowledge import TRAVEL_PROFILES


def _route_after_planner(state: TravelState) -> str:
    return "clarification" if state.get("clarification") else "supervisor"


def _route_supervisor(state: TravelState) -> str:
    return state.get("next_action", "finalizer")


def create_memory_checkpointer() -> InMemorySaver:
    serializer = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("SmartVoyage.coordinator.schemas", "TravelPlan"),
            ("SmartVoyage.coordinator.schemas", "TraceEvent"),
            ("SmartVoyage.coordinator.schemas", "TicketCandidate"),
            ("SmartVoyage.coordinator.schemas", "WeatherResult"),
            ("SmartVoyage.coordinator.schemas", "OrderResult"),
            ("SmartVoyage.memory.models", "PreferenceRecord"),
            ("SmartVoyage.memory.models", "PreferenceCandidate"),
        ]
    )
    return InMemorySaver(serde=serializer)


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def sanitize_plan(user_query: str, raw_plan: TravelPlan) -> TravelPlan:
    plan = raw_plan.model_copy(deep=True)
    weather_terms = ("天气", "气温", "气象", "下雨", "下雪", "晴天", "风力")
    ticket_terms = (
        "航班",
        "机票",
        "飞机票",
        "火车票",
        "高铁票",
        "动车票",
        "交通票",
        "演唱会票",
        "演出票",
    )
    booking_terms = ("预订", "订票", "买票", "买一张", "购买", "下单")
    attraction_terms = (
        "景点",
        "游玩",
        "好玩",
        "值得逛",
        "逛逛",
        "旅游推荐",
    )

    normalized_query = re.sub(
        r"^(?:(?:请|麻烦|帮我|帮忙)\s*)?(?:查询|查一下|查查|查看|看看|查)\s*",
        "",
        user_query.strip(),
    )

    if plan.ticket_type is None:
        if any(term in user_query for term in ("航班", "机票", "飞机")):
            plan.ticket_type = "flight"
        elif any(term in user_query for term in ("火车", "高铁", "动车")):
            plan.ticket_type = "train"
        elif any(term in user_query for term in ("演唱会", "演出票")):
            plan.ticket_type = "concert"

    if plan.date is None:
        date_match = re.search(
            r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})日?", user_query
        )
        if date_match:
            plan.date = datetime.strptime(
                "-".join(date_match.groups()), "%Y-%m-%d"
            ).date()
        else:
            relative_days = {"今天": 0, "明天": 1, "后天": 2}
            relative = next((term for term in relative_days if term in user_query), None)
            if relative:
                plan.date = _today() + timedelta(days=relative_days[relative])

    range_match = re.search(r"未来\s*([2-7])\s*天", user_query)
    chinese_range_match = re.search(r"未来\s*([二三四五六七])\s*天", user_query)
    chinese_days = {"二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
    if re.search(r"未来\s*(?:一周|7天|七天)|一周天气", user_query):
        plan.weather_days = 7
    elif range_match:
        plan.weather_days = int(range_match.group(1))
    elif chinese_range_match:
        plan.weather_days = chinese_days[chinese_range_match.group(1)]
    if plan.weather_days > 1 and plan.date is None:
        plan.date = _today()

    if not plan.departure or not plan.destination:
        route_match = re.search(
            r"(?P<departure>[\u4e00-\u9fff]{2,8})到"
            r"(?P<destination>[\u4e00-\u9fff]{2,8}?)(?=\d{4}|的?(?:航班|机票|飞机|火车|高铁|动车))",
            normalized_query,
        )
        if route_match:
            plan.departure = plan.departure or route_match.group("departure")
            plan.destination = plan.destination or route_match.group("destination")

    has_weather_request = any(term in user_query for term in weather_terms)
    has_ticket_request = bool(plan.ticket_type) or any(
        term in user_query for term in ticket_terms
    )
    has_booking_term = any(term in user_query for term in booking_terms) or bool(
        re.search(
            r"(?:预订|订|购买|买)\s*(?:一|1)?\s*张?\s*"
            r"(?:机票|飞机票|火车票|高铁票|动车票|演出票|票)",
            user_query,
        )
    )
    has_negated_booking = bool(
        re.search(
            r"(?:不|别|不要|无需|禁止|千万别).{0,6}"
            r"(?:预订|订(?:一|1)?张?票|买票|买一张|购买|下单)",
            user_query,
        )
    )
    has_booking_request = has_booking_term and not has_negated_booking
    has_attraction_request = any(term in user_query for term in attraction_terms)

    if has_attraction_request and not plan.destination and not plan.departure:
        known_cities = {profile["city"] for profile in TRAVEL_PROFILES.values()}
        plan.destination = next((city for city in known_cities if city in user_query), None)

    if has_weather_request:
        if "weather" not in plan.tasks:
            plan.tasks.insert(0, "weather")
        if not plan.destination and not plan.departure:
            city_match = re.match(
                r"(?P<city>[\u4e00-\u9fff]{2,10}?)(?:市)?"
                r"(?=今天|明天|后天|\d{4}|的?天气)",
                normalized_query,
            )
            if city_match:
                plan.destination = city_match.group("city")
    else:
        plan.tasks = [task for task in plan.tasks if task != "weather"]
        plan.weather_required_for_ticket = False

    if has_ticket_request and "ticket" not in plan.tasks:
        plan.tasks.append("ticket")

    if has_booking_request:
        plan.action = "book_if_available"
        if "ticket" not in plan.tasks:
            plan.tasks.append("ticket")
        if "order" not in plan.tasks:
            plan.tasks.append("order")
    else:
        plan.tasks = [task for task in plan.tasks if task != "order"]
        plan.action = "query"

    if has_attraction_request and "attraction" not in plan.tasks:
        plan.tasks.append("attraction")
    if not has_attraction_request:
        plan.tasks = [task for task in plan.tasks if task != "attraction"]

    if has_weather_request:
        plan.weather_required_for_ticket = any(
            phrase in user_query
            for phrase in ("天气好", "天气合适", "如果天气", "若天气")
        )

    if plan.date:
        for condition in plan.filters:
            if condition.field == "ticket_type":
                type_aliases = {
                    "flight": "flight",
                    "航班": "flight",
                    "机票": "flight",
                    "飞机票": "flight",
                    "train": "train",
                    "火车": "train",
                    "火车票": "train",
                    "高铁": "train",
                    "高铁票": "train",
                    "concert": "concert",
                    "演唱会": "concert",
                    "演唱会票": "concert",
                    "演出票": "concert",
                }
                if isinstance(condition.value, list):
                    condition.value = [
                        type_aliases.get(str(value), value)
                        for value in condition.value
                    ]
                else:
                    condition.value = type_aliases.get(
                        str(condition.value), condition.value
                    )
            if condition.field not in {"departure_time", "arrival_time"}:
                continue
            if isinstance(condition.value, str) and re.fullmatch(
                r"\d{1,2}:\d{2}(?::\d{2})?", condition.value
            ):
                time_value = condition.value
                if time_value.count(":") == 1:
                    time_value += ":00"
                condition.value = f"{plan.date.isoformat()}T{time_value}"

    needs_ticket = "ticket" in plan.tasks or "order" in plan.tasks
    ticket_ready = not needs_ticket or bool(
        plan.ticket_type and plan.departure and plan.destination and plan.date
    )
    weather_ready = "weather" not in plan.tasks or bool(
        plan.destination or plan.departure
    )
    attraction_ready = "attraction" not in plan.tasks or bool(
        plan.destination or plan.departure
    )
    if not ticket_ready:
        missing: list[str] = []
        if not plan.ticket_type:
            missing.append("票种（机票或火车票）")
        if not plan.departure:
            missing.append("出发地")
        if not plan.destination:
            missing.append("目的地")
        if not plan.date:
            missing.append("日期")
        plan.clarification = f"已识别到订票需求，请补充{'、'.join(missing)}。"
    elif weather_ready and attraction_ready:
        plan.clarification = None
    return plan


def build_coordinator(dependencies: CoordinatorDependencies, checkpointer):
    graph = StateGraph(TravelState)
    graph.add_node("memory_load", memory_load_node(dependencies))
    graph.add_node("planner", planner_node(dependencies))
    graph.add_node("supervisor", supervisor_node(dependencies))
    graph.add_node("weather", weather_worker_node(dependencies))
    graph.add_node("weather_policy", weather_policy_node)
    graph.add_node("ticket", ticket_worker_node(dependencies))
    graph.add_node("ticket_policy", ticket_policy_node)
    graph.add_node("attraction", attraction_worker_node(dependencies))
    graph.add_node("order", order_worker_node(dependencies))
    graph.add_node("confirmation", confirmation_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("finalizer", finalizer_node)
    graph.add_node("memory_persist", memory_persist_node(dependencies))

    graph.add_edge(START, "memory_load")
    graph.add_edge("memory_load", "planner")
    graph.add_conditional_edges(
        "planner",
        _route_after_planner,
        {"clarification": "clarification", "supervisor": "supervisor"},
    )
    graph.add_edge("clarification", "memory_persist")

    graph.add_conditional_edges(
        "supervisor",
        _route_supervisor,
        {
            "supervisor": "supervisor",
            "weather": "weather",
            "ticket": "ticket",
            "attraction": "attraction",
            "order": "order",
            "confirmation": "confirmation",
            "finalizer": "finalizer",
        },
    )
    graph.add_edge("weather", "weather_policy")
    graph.add_edge("weather_policy", "supervisor")
    graph.add_edge("ticket", "ticket_policy")
    graph.add_edge("ticket_policy", "supervisor")
    graph.add_edge("attraction", "supervisor")
    graph.add_edge("order", "supervisor")
    graph.add_edge("confirmation", "supervisor")
    graph.add_edge("finalizer", "memory_persist")
    graph.add_edge("memory_persist", END)
    return graph.compile(checkpointer=checkpointer)


def create_production_dependencies(
    network,
    llm,
    clients=None,
    preference_repository=None,
) -> CoordinatorDependencies:
    clients = clients or CoordinatorClients(network=network, llm=llm)
    planner = llm.with_structured_output(TravelPlan)
    supervisor = llm.with_structured_output(SupervisorDecision)
    attraction_parser = llm.with_structured_output(AttractionList)

    def plan(user_query: str, messages: list[dict]) -> TravelPlan:
        current_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        recent_history = json.dumps(messages[-6:], ensure_ascii=False, default=str)
        prompt = f"""
你是旅行任务 Planner。当前日期是 {current_date}。
把用户目标拆解为 weather、ticket、attraction、order 任务，并输出 TravelPlan。
你必须理解价格上限、出发时间、舱位、余票、行程时长、数量和排序偏好。
条件只能使用 TravelPlan schema 允许的字段和操作符，不能生成代码。
“天气好才订票”设置 weather_required_for_ticket=true。
“最便宜”生成 price 升序排序；“晚上八点以后”生成 departure_time >= 当日20:00。
需要预订时 action=book_if_available，且 requires_confirmation=true。
缺少执行票务查询所需的出发地、目的地或日期时填写 clarification，不得编造。
最近对话：{recent_history}
用户问题：{user_query}
""".strip()
        return sanitize_plan(user_query, planner.invoke(prompt))

    def choose_next(state: TravelState) -> str:
        plan_data = state["plan"].model_dump(mode="json")
        snapshot = {
            "plan": plan_data,
            "completed_tasks": state.get("completed_tasks", []),
            "skipped_tasks": state.get("skipped_tasks", []),
            "weather_good": state.get("weather_good"),
            "candidate_count": len(state.get("eligible_tickets", [])),
            "confirmed": state.get("confirmed", False),
            "step_count": state.get("step_count", 0),
        }
        prompt = (
            "你是旅行多智能体 Supervisor。根据共享状态选择下一动作。"
            "优先完成尚未完成且未跳过的计划任务；所有任务结束后选择 finalizer。"
            "不要重复已完成任务，也不能绕过确认直接下单。\n"
            f"共享状态：{json.dumps(snapshot, ensure_ascii=False)}"
        )
        return supervisor.invoke(prompt).next_action

    def query_weather(travel_plan: TravelPlan):
        city = travel_plan.destination or travel_plan.departure
        query = f"查询{city}"
        if travel_plan.date:
            query += f" {travel_plan.date.isoformat()}"
        query += "的天气"
        raw = asyncio.run(clients.call_agent("WeatherQueryAssistant", query))
        return clients.normalize_weather(raw)

    def query_tickets(travel_plan: TravelPlan):
        ticket_label = {
            "flight": "机票",
            "train": "火车票",
            "concert": "演唱会票",
        }.get(travel_plan.ticket_type, "票")
        query = (
            f"查询{travel_plan.date.isoformat() if travel_plan.date else ''}"
            f"从{travel_plan.departure or ''}到{travel_plan.destination or ''}的"
            f"{ticket_label}，返回所有候选结果、时间、价格、舱位和余票"
        )
        raw = asyncio.run(clients.call_agent("TicketQueryAssistant", query))
        return clients.normalize_tickets(raw)

    def recommend_attractions(travel_plan: TravelPlan) -> list[dict[str, str]]:
        city = travel_plan.destination or travel_plan.departure or "目的地"
        result = attraction_parser.invoke(
            f"推荐{city}三个有代表性的景点，每个景点给出简短理由。"
        )
        return [item.model_dump() for item in result.attractions]

    def place_order(ticket, quantity: int) -> OrderResult:
        payload = {
            "action": "order_selected_ticket",
            "selected_ticket": ticket.model_dump(mode="json"),
            "quantity": quantity,
        }
        raw = asyncio.run(
            clients.call_agent(
                "TicketOrderAssistant", json.dumps(payload, ensure_ascii=False)
            )
        )
        succeeded = raw.startswith("已按用户确认信息预订") and "预定成功" in raw
        return OrderResult(
            status="success" if succeeded else "failed",
            message=raw,
            selected_ticket=ticket,
        )

    memory_dependencies = {}
    if preference_repository is not None:
        extractor = create_llm_preference_extractor(llm)

        def persist_preferences(user_id, session_id, candidates):
            updates = []
            for candidate in candidates:
                if candidate.operation == "delete":
                    preference_repository.delete(
                        user_id,
                        session_id,
                        candidate.preference_key,
                        candidate.source_text,
                    )
                    updates.append(candidate)
                elif candidate.operation == "upsert":
                    updates.append(
                        preference_repository.upsert(user_id, session_id, candidate)
                    )
            return updates

        memory_dependencies = {
            "load_preferences": preference_repository.list_active,
            "extract_preferences": extractor,
            "persist_preferences": persist_preferences,
        }

    return CoordinatorDependencies(
        plan=plan,
        choose_next=choose_next,
        query_weather=query_weather,
        query_tickets=query_tickets,
        recommend_attractions=recommend_attractions,
        place_order=place_order,
        **memory_dependencies,
    )


def create_production_coordinator(
    network,
    llm,
    checkpointer=None,
    preference_repository=None,
):
    dependencies = create_production_dependencies(
        network=network,
        llm=llm,
        preference_repository=preference_repository,
    )
    return build_coordinator(dependencies, checkpointer or create_memory_checkpointer())
