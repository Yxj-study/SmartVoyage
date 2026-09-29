import unittest

from SmartVoyage.coordinator.graph import build_coordinator, create_memory_checkpointer
from SmartVoyage.coordinator.nodes import CoordinatorDependencies
from SmartVoyage.coordinator.schemas import TravelPlan
from SmartVoyage.evaluation.adapters import execute_memory_case
from SmartVoyage.evaluation.metrics import score_cases
from SmartVoyage.evaluation.schemas import EvaluationCase, EvaluationTurn
from SmartVoyage.memory.models import PreferenceCandidate
from SmartVoyage.memory.repository import InMemoryPreferenceRepository


class MemoryEvaluationTest(unittest.TestCase):
    def test_cross_session_application_and_user_isolation_are_scored(self):
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

        def choose_next(state):
            done = set(state.get("completed_tasks", [])) | set(
                state.get("skipped_tasks", [])
            )
            return next(
                (task for task in state["plan"].tasks if task not in done),
                "finalizer",
            )

        graph = build_coordinator(
            CoordinatorDependencies(
                plan=plan,
                choose_next=choose_next,
                query_weather=lambda _plan: None,
                query_tickets=lambda _plan: [],
                recommend_attractions=lambda _plan: [],
                place_order=lambda _ticket, _quantity: None,
                load_preferences=repository.list_active,
                extract_preferences=extract,
                persist_preferences=persist,
            ),
            create_memory_checkpointer(),
        )

        def invoke(user_id, session_id, query):
            return graph.invoke(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "user_query": query,
                    "messages": [],
                },
                config={"configurable": {"thread_id": f"{user_id}:{session_id}"}},
            )

        case = EvaluationCase(
            id="memory-cross-session",
            user_id="user-a",
            query="跨会话偏好",
            expected_preferences={"preferred_transport": "train"},
            expected_applied_preferences={"preferred_transport": "train"},
            turns=[
                EvaluationTurn(
                    user_id="user-a",
                    session_id="a-1",
                    query="请记住我以后优先坐高铁",
                    expected_response_contains=["任务已完成"],
                ),
                EvaluationTurn(
                    user_id="user-a",
                    session_id="a-2",
                    query="帮我查南京到上海的票",
                    expected_response_contains=["任务已完成"],
                ),
                EvaluationTurn(
                    user_id="user-b",
                    session_id="b-1",
                    query="帮我查南京到上海的票",
                    expected_response_contains=["任务已完成"],
                ),
            ],
        )

        prediction = execute_memory_case(case, invoke)
        summary = score_cases([case], [prediction])

        self.assertTrue(prediction.multi_turn_success)
        self.assertEqual(
            prediction.retrieved_preferences,
            {"preferred_transport": "train"},
        )
        self.assertEqual(
            prediction.applied_preferences,
            {"preferred_transport": "train"},
        )
        self.assertEqual(summary.memory_retrieval_accuracy, 1.0)
        self.assertEqual(summary.preference_application_accuracy, 1.0)
        self.assertEqual(summary.cross_user_leakage_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
