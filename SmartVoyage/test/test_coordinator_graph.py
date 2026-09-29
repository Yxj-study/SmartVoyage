import unittest
from datetime import date
from unittest.mock import patch

from langgraph.types import Command

from SmartVoyage.coordinator.graph import (
    build_coordinator,
    create_memory_checkpointer,
    create_production_dependencies,
    sanitize_plan,
)
from SmartVoyage.coordinator.nodes import CoordinatorDependencies
from SmartVoyage.coordinator.schemas import (
    FilterCondition,
    OrderResult,
    SortRule,
    TicketCandidate,
    TravelPlan,
    WeatherResult,
)
from SmartVoyage.memory.models import PreferenceCandidate
from SmartVoyage.memory.repository import InMemoryPreferenceRepository


class FakeStructuredRunnable:
    def __init__(self, result):
        self.result = result

    def invoke(self, _prompt):
        return self.result


class FakeCoordinatorLlm:
    def __init__(self, results):
        self.results = results

    def with_structured_output(self, schema):
        return FakeStructuredRunnable(self.results[schema.__name__])


class FakeProductionClients:
    async def call_agent(self, _agent_name, _query):
        return "unused"


class RecordingProductionClients:
    def __init__(self):
        self.query = ""

    async def call_agent(self, _agent_name, query):
        self.query = query
        return "raw"

    def normalize_tickets(self, _raw):
        return []


class CoordinatorGraphTest(unittest.TestCase):
    @staticmethod
    def choose_first_unfinished_task(state):
        done = set(state.get("completed_tasks", [])) | set(
            state.get("skipped_tasks", [])
        )
        for task in state["plan"].tasks:
            if task not in done:
                return task
        return "finalizer"

    def make_dependencies(
        self,
        *,
        plan,
        calls,
        weather=None,
        tickets=None,
        attractions=None,
        choose_next=None,
    ):
        def query_weather(_plan):
            calls.append("weather")
            return weather

        def query_tickets(_plan):
            calls.append("ticket")
            return tickets or []

        def recommend_attractions(_plan):
            calls.append("attraction")
            return attractions or []

        def place_order(ticket, quantity):
            calls.append("order")
            return OrderResult(
                status="success",
                message=f"ordered {ticket.number} x{quantity}",
                selected_ticket=ticket,
            )

        return CoordinatorDependencies(
            plan=lambda _query, _messages: plan,
            choose_next=choose_next or self.choose_first_unfinished_task,
            query_weather=query_weather,
            query_tickets=query_tickets,
            recommend_attractions=recommend_attractions,
            place_order=place_order,
        )

    def invoke(self, dependencies, thread_id):
        graph = build_coordinator(dependencies, create_memory_checkpointer())
        return graph.invoke(
            {"user_query": "测试旅行任务", "messages": []},
            config={"configurable": {"thread_id": thread_id}},
        )

    def test_long_term_preference_applies_across_sessions_without_cross_user_leakage(self):
        repository = InMemoryPreferenceRepository()

        def plan(query, _messages):
            if "记住" in query:
                return TravelPlan(tasks=[])
            return TravelPlan(
                departure="南京",
                destination="上海",
                date="2026-09-10",
                tasks=["ticket"],
            )

        def extract(_user_id, _session_id, query):
            if "记住" not in query:
                return []
            return [
                PreferenceCandidate(
                    preference_key="preferred_transport",
                    value="train",
                    source_text=query,
                )
            ]

        def persist(user_id, session_id, candidates):
            return [
                repository.upsert(user_id, session_id, candidate)
                for candidate in candidates
            ]

        dependencies = CoordinatorDependencies(
            plan=plan,
            choose_next=self.choose_first_unfinished_task,
            query_weather=lambda _plan: None,
            query_tickets=lambda _plan: [],
            recommend_attractions=lambda _plan: [],
            place_order=lambda _ticket, _quantity: None,
            load_preferences=repository.list_active,
            extract_preferences=extract,
            persist_preferences=persist,
        )
        graph = build_coordinator(dependencies, create_memory_checkpointer())

        graph.invoke(
            {
                "user_id": "user-a",
                "session_id": "session-a-1",
                "user_query": "请记住我以后优先坐高铁",
                "messages": [],
            },
            config={"configurable": {"thread_id": "user-a:session-a-1"}},
        )
        same_user = graph.invoke(
            {
                "user_id": "user-a",
                "session_id": "session-a-2",
                "user_query": "帮我查南京到上海的票",
                "messages": [],
            },
            config={"configurable": {"thread_id": "user-a:session-a-2"}},
        )
        other_user = graph.invoke(
            {
                "user_id": "user-b",
                "session_id": "session-b-1",
                "user_query": "帮我查南京到上海的票",
                "messages": [],
            },
            config={"configurable": {"thread_id": "user-b:session-b-1"}},
        )

        self.assertEqual(same_user["plan"].ticket_type, "train")
        self.assertEqual(
            same_user["loaded_preferences"][0].preference_key,
            "preferred_transport",
        )
        self.assertEqual(same_user["applied_preferences"], {"preferred_transport": "train"})
        self.assertIsNone(other_user["plan"].ticket_type)
        self.assertEqual(other_user["loaded_preferences"], [])

    def test_memory_read_failure_does_not_block_travel_task(self):
        calls = []

        def fail_load(_user_id):
            raise RuntimeError("memory unavailable")

        dependencies = self.make_dependencies(
            plan=TravelPlan(destination="北京", tasks=["weather"]),
            weather=WeatherResult(
                city="北京", weather="晴", wind_scale=2, precipitation=0
            ),
            calls=calls,
        )
        dependencies.load_preferences = fail_load
        graph = build_coordinator(dependencies, create_memory_checkpointer())

        result = graph.invoke(
            {
                "user_id": "u1",
                "session_id": "s1",
                "user_query": "查北京天气",
                "messages": [],
            },
            config={"configurable": {"thread_id": "u1:s1"}},
        )

        self.assertEqual(calls, ["weather"])
        self.assertIn("天气：北京 晴", result["final_answer"])
        self.assertEqual(result["memory_errors"][0]["stage"], "memory_load")
        self.assertEqual(result["trace"][0].status, "failed")

    def test_memory_write_failure_preserves_final_answer(self):
        dependencies = self.make_dependencies(
            plan=TravelPlan(tasks=[]),
            calls=[],
        )
        dependencies.extract_preferences = lambda *_args: [
            PreferenceCandidate(
                preference_key="preferred_transport",
                value="train",
            )
        ]

        def fail_persist(_user_id, _session_id, _candidates):
            raise RuntimeError("memory write unavailable")

        dependencies.persist_preferences = fail_persist
        graph = build_coordinator(dependencies, create_memory_checkpointer())

        result = graph.invoke(
            {
                "user_id": "u1",
                "session_id": "s1",
                "user_query": "以后优先高铁",
                "messages": [],
            },
            config={"configurable": {"thread_id": "u1:s1-write"}},
        )

        self.assertEqual(result["final_answer"], "任务已完成。")
        self.assertEqual(result["memory_errors"][0]["stage"], "memory_persist")
        self.assertEqual(result["trace"][-1].status, "failed")

    def test_bad_weather_skips_ticket_but_keeps_attraction(self):
        calls = []
        plan = TravelPlan(
            departure="长沙",
            destination="北京",
            date="2026-08-19",
            tasks=["weather", "ticket", "attraction", "order"],
            weather_required_for_ticket=True,
            action="book_if_available",
        )
        dependencies = self.make_dependencies(
            plan=plan,
            weather=WeatherResult(
                city="北京", weather="暴雨", wind_scale=3, precipitation=20
            ),
            attractions=[{"name": "故宫", "reason": "历史文化"}],
            calls=calls,
        )

        result = self.invoke(dependencies, "bad-weather")

        self.assertNotIn("ticket", calls)
        self.assertNotIn("order", calls)
        self.assertIn("attraction", calls)
        self.assertIn("ticket", result["skipped_tasks"])
        self.assertEqual(result["attractions"][0]["name"], "故宫")

    def test_supervisor_cannot_finalize_before_pending_tasks_finish(self):
        calls = []
        plan = TravelPlan(
            departure="长沙",
            destination="北京",
            date="2026-08-19",
            tasks=["weather", "ticket", "attraction", "order"],
            weather_required_for_ticket=True,
            action="book_if_available",
        )
        dependencies = self.make_dependencies(
            plan=plan,
            weather=WeatherResult(
                city="北京", weather="暴雨", wind_scale=3, precipitation=20
            ),
            attractions=[{"name": "故宫", "reason": "历史文化"}],
            calls=calls,
            choose_next=lambda _state: "finalizer",
        )

        result = self.invoke(dependencies, "early-finalizer")

        self.assertEqual(calls, ["weather", "attraction"])
        self.assertIn("ticket", result["skipped_tasks"])
        self.assertIn("order", result["skipped_tasks"])
        self.assertEqual(result["attractions"][0]["name"], "故宫")

    def test_weather_only_does_not_call_ticket(self):
        calls = []
        dependencies = self.make_dependencies(
            plan=TravelPlan(destination="北京", tasks=["weather"]),
            weather=WeatherResult(
                city="北京", weather="晴", wind_scale=3, precipitation=0
            ),
            calls=calls,
        )

        result = self.invoke(dependencies, "weather-only")

        self.assertEqual(calls, ["weather"])
        self.assertIn("weather", result["completed_tasks"])
        self.assertTrue(result["weather_good"])

    def test_ticket_policy_selects_lowest_eligible_price(self):
        calls = []
        tickets = [
            TicketCandidate(
                ticket_type="flight",
                departure="长沙",
                destination="北京",
                departure_time="2026-08-19T20:10:00",
                arrival_time="2026-08-19T22:30:00",
                number="CZ3127",
                seat_class="经济舱",
                price="880.00",
                remaining_tickets=12,
            ),
            TicketCandidate(
                ticket_type="flight",
                departure="长沙",
                destination="北京",
                departure_time="2026-08-19T21:00:00",
                arrival_time="2026-08-19T23:20:00",
                number="HU7636",
                seat_class="经济舱",
                price="760.00",
                remaining_tickets=4,
            ),
        ]
        plan = TravelPlan(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            date="2026-08-19",
            tasks=["ticket"],
            filters=[FilterCondition(field="price", operator="lt", value=1000)],
            sorts=[SortRule(field="price", order="asc")],
        )
        dependencies = self.make_dependencies(plan=plan, tickets=tickets, calls=calls)

        result = self.invoke(dependencies, "ticket-policy")

        self.assertEqual(calls, ["ticket"])
        self.assertEqual(result["selected_ticket"].number, "HU7636")

    def test_missing_information_returns_clarification_without_agents(self):
        calls = []
        dependencies = self.make_dependencies(
            plan=TravelPlan(
                tasks=["ticket"],
                clarification="请提供出发日期。",
            ),
            calls=calls,
        )

        result = self.invoke(dependencies, "clarification")

        self.assertEqual(calls, [])
        self.assertEqual(result["final_answer"], "请提供出发日期。")

    def test_supervisor_stops_after_eight_steps(self):
        calls = []
        dependencies = self.make_dependencies(
            plan=TravelPlan(tasks=["weather"]),
            weather=WeatherResult(
                city="北京", weather="晴", wind_scale=3, precipitation=0
            ),
            calls=calls,
            choose_next=lambda _state: "supervisor",
        )

        result = self.invoke(dependencies, "step-limit")

        self.assertEqual(result["step_count"], 8)
        self.assertIn("最大执行步数", result["final_answer"])

    def test_supervisor_cannot_dispatch_unrequested_agent(self):
        calls = []
        choices = iter(["weather", "ticket", "finalizer"])
        ticket = TicketCandidate(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            departure_time="2026-08-19T21:00:00",
            arrival_time="2026-08-19T23:20:00",
            number="HU7636",
            seat_class="经济舱",
            price="760.00",
            remaining_tickets=4,
        )
        dependencies = self.make_dependencies(
            plan=TravelPlan(
                ticket_type="flight",
                departure="长沙",
                destination="北京",
                date="2026-08-19",
                tasks=["ticket"],
            ),
            tickets=[ticket],
            weather=WeatherResult(
                city="北京", weather="晴", wind_scale=3, precipitation=0
            ),
            calls=calls,
            choose_next=lambda _state: next(choices),
        )

        result = self.invoke(dependencies, "reject-unrequested-weather")

        self.assertNotIn("weather", calls)
        self.assertEqual(calls, ["ticket"])
        self.assertEqual(result["selected_ticket"].number, "HU7636")

    def test_production_dependencies_use_llm_planner_and_supervisor(self):
        from SmartVoyage.coordinator.schemas import (
            AttractionList,
            SupervisorDecision,
        )

        expected_plan = TravelPlan(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            date="2026-08-19",
            tasks=["ticket", "order"],
            filters=[FilterCondition(field="price", operator="lt", value=1000)],
            sorts=[SortRule(field="price", order="asc")],
            action="book_if_available",
        )
        llm = FakeCoordinatorLlm(
            {
                "TravelPlan": expected_plan,
                "SupervisorDecision": SupervisorDecision(next_action="ticket"),
                "AttractionList": AttractionList(attractions=[]),
            }
        )
        dependencies = create_production_dependencies(
            network=None,
            llm=llm,
            clients=FakeProductionClients(),
        )

        actual_plan = dependencies.plan(
            "价格低于1000元就买一张最便宜的",
            [],
        )
        action = dependencies.choose_next(
            {
                "user_query": "价格低于1000元就买一张最便宜的",
                "plan": actual_plan,
                "completed_tasks": [],
                "skipped_tasks": [],
                "step_count": 0,
            }
        )

        self.assertEqual(actual_plan.filters[0].field, "price")
        self.assertEqual(actual_plan.sorts[0].order, "asc")
        self.assertEqual(action, "ticket")

    def test_ticket_worker_uses_chinese_ticket_type_for_existing_agent(self):
        from SmartVoyage.coordinator.schemas import (
            AttractionList,
            SupervisorDecision,
        )

        clients = RecordingProductionClients()
        llm = FakeCoordinatorLlm(
            {
                "TravelPlan": TravelPlan(),
                "SupervisorDecision": SupervisorDecision(next_action="finalizer"),
                "AttractionList": AttractionList(attractions=[]),
            }
        )
        dependencies = create_production_dependencies(
            network=None,
            llm=llm,
            clients=clients,
        )

        dependencies.query_tickets(
            TravelPlan(
                ticket_type="train",
                departure="北京",
                destination="上海",
                date="2026-02-06",
                tasks=["ticket"],
            )
        )

        self.assertIn("火车票", clients.query)
        self.assertNotIn("train票", clients.query)

    def test_plan_sanitizer_removes_unrequested_weather_and_normalizes_booking(self):
        query = (
            "查询2026年8月19日长沙到北京的航班，如果价格低于1000元，"
            "并且晚上8点以后有航班，就选择最便宜的一张并预订"
        )
        raw_plan = TravelPlan(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            date="2026-08-19",
            tasks=["weather", "ticket", "order"],
            weather_required_for_ticket=True,
            filters=[
                FilterCondition(field="price", operator="lt", value=1000),
                FilterCondition(
                    field="departure_time", operator="gte", value="20:00"
                ),
            ],
            sorts=[SortRule(field="price", order="asc")],
            action="query",
        )

        plan = sanitize_plan(query, raw_plan)

        self.assertEqual(plan.tasks, ["ticket", "order"])
        self.assertFalse(plan.weather_required_for_ticket)
        self.assertEqual(plan.action, "book_if_available")
        self.assertEqual(plan.filters[1].value, "2026-08-19T20:00:00")

    def test_plan_sanitizer_fills_weather_city_and_removes_false_clarification(self):
        with patch("SmartVoyage.coordinator.graph._today", return_value=date(2026, 9, 29)):
            plan = sanitize_plan(
                "查询北京今天的天气",
                TravelPlan(tasks=["weather"], clarification="请提供城市"),
            )

        self.assertEqual(plan.destination, "北京")
        self.assertEqual(plan.date, date(2026, 9, 29))
        self.assertIsNone(plan.clarification)

    def test_plan_sanitizer_resolves_relative_weather_dates(self):
        with patch("SmartVoyage.coordinator.graph._today", return_value=date(2026, 9, 29)):
            tomorrow = sanitize_plan("查询北京明天天气", TravelPlan(tasks=["weather"]))
            day_after = sanitize_plan("查询长沙后天天气", TravelPlan(tasks=["weather"]))

        self.assertEqual(tomorrow.date, date(2026, 9, 30))
        self.assertEqual(day_after.date, date(2026, 10, 1))

    def test_plan_sanitizer_requests_seven_day_forecast(self):
        with patch("SmartVoyage.coordinator.graph._today", return_value=date(2026, 9, 29)):
            plan = sanitize_plan("查询北京未来一周天气", TravelPlan(tasks=["weather"]))

        self.assertEqual(plan.date, date(2026, 9, 29))
        self.assertEqual(plan.weather_days, 7)

    def test_plan_sanitizer_keeps_complete_ticket_query_executable(self):
        plan = sanitize_plan(
            "查询北京到上海2026年2月6日的火车票",
            TravelPlan(
                filters=[
                    FilterCondition(
                        field="ticket_type", operator="eq", value="火车票"
                    )
                ],
                clarification="请确认席位或价格偏好",
            ),
        )

        self.assertEqual(plan.tasks, ["ticket"])
        self.assertEqual(plan.ticket_type, "train")
        self.assertEqual(plan.departure, "北京")
        self.assertEqual(plan.destination, "上海")
        self.assertEqual(plan.date.isoformat(), "2026-02-06")
        self.assertEqual(plan.filters[0].value, "train")
        self.assertIsNone(plan.clarification)

    def test_plan_sanitizer_does_not_book_when_order_term_is_negated(self):
        plan = sanitize_plan(
            "只比较南京到上海的高铁票，千万别替我下单",
            TravelPlan(
                ticket_type="train",
                departure="南京",
                destination="上海",
                date="2026-10-01",
                tasks=["ticket"],
            ),
        )

        self.assertEqual(plan.tasks, ["ticket"])
        self.assertEqual(plan.action, "query")

    def test_plan_sanitizer_recognizes_colloquial_ticket_and_attraction_terms(self):
        plan = sanitize_plan(
            "除了交通票，也想知道苏州有什么值得逛",
            TravelPlan(
                ticket_type="train",
                departure="南京",
                destination="苏州",
                date="2026-10-02",
                tasks=["ticket", "attraction"],
            ),
        )

        self.assertEqual(plan.tasks, ["ticket", "attraction"])

    def test_booking_interrupt_can_cancel_without_ordering(self):
        calls = []
        plan = TravelPlan(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            date="2026-08-19",
            tasks=["ticket", "order"],
            action="book_if_available",
        )
        ticket = TicketCandidate(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            departure_time="2026-08-19T21:00:00",
            arrival_time="2026-08-19T23:20:00",
            number="HU7636",
            seat_class="经济舱",
            price="760.00",
            remaining_tickets=4,
        )
        dependencies = self.make_dependencies(
            plan=plan,
            tickets=[ticket],
            calls=calls,
        )
        graph = build_coordinator(dependencies, create_memory_checkpointer())
        config = {"configurable": {"thread_id": "cancel-booking"}}

        paused = graph.invoke(
            {"user_query": "有票就买一张", "messages": []}, config=config
        )
        resumed = graph.invoke(Command(resume=False), config=config)

        self.assertIn("__interrupt__", paused)
        self.assertEqual(paused["selected_ticket"].number, "HU7636")
        self.assertNotIn("order", calls)
        self.assertFalse(resumed["confirmed"])
        self.assertIn("order", resumed["skipped_tasks"])

    def test_booking_interrupt_orders_same_ticket_after_confirmation(self):
        calls = []
        plan = TravelPlan(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            date="2026-08-19",
            quantity=1,
            tasks=["ticket", "order"],
            action="book_if_available",
        )
        ticket = TicketCandidate(
            ticket_type="flight",
            departure="长沙",
            destination="北京",
            departure_time="2026-08-19T21:00:00",
            arrival_time="2026-08-19T23:20:00",
            number="HU7636",
            seat_class="经济舱",
            price="760.00",
            remaining_tickets=4,
        )
        dependencies = self.make_dependencies(
            plan=plan,
            tickets=[ticket],
            calls=calls,
        )
        graph = build_coordinator(dependencies, create_memory_checkpointer())
        config = {"configurable": {"thread_id": "confirm-booking"}}

        paused = graph.invoke(
            {"user_query": "有票就买一张", "messages": []}, config=config
        )
        resumed = graph.invoke(Command(resume=True), config=config)

        self.assertIn("__interrupt__", paused)
        self.assertEqual(calls, ["ticket", "order"])
        self.assertTrue(resumed["confirmed"])
        self.assertEqual(resumed["order_result"].selected_ticket.number, "HU7636")


if __name__ == "__main__":
    unittest.main()
