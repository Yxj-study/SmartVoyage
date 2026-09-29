import unittest

from SmartVoyage.memory.models import PreferenceCandidate
from SmartVoyage.memory.mysql_repository import MySqlPreferenceRepository
from SmartVoyage.memory.repository import InMemoryPreferenceRepository


class MemoryRepositoryContractTest(unittest.TestCase):
    def test_preferences_are_isolated_by_user_and_upserted_by_key(self):
        repository = InMemoryPreferenceRepository()
        repository.upsert(
            "u1",
            "s1",
            PreferenceCandidate(
                preference_key="preferred_transport",
                value="train",
                source_text="以后优先高铁",
            ),
        )
        repository.upsert(
            "u2",
            "s2",
            PreferenceCandidate(
                preference_key="preferred_transport",
                value="flight",
                source_text="我偏好飞机",
            ),
        )
        repository.upsert(
            "u1",
            "s3",
            PreferenceCandidate(
                preference_key="preferred_transport",
                value="flight",
                source_text="以后改成飞机",
            ),
        )

        self.assertEqual(repository.list_active("u1")[0].value, "flight")
        self.assertEqual(repository.list_active("u2")[0].value, "flight")
        self.assertEqual(len(repository.events), 3)
        self.assertEqual(repository.events[-1]["old_value"], "train")
        self.assertEqual(repository.events[-1]["new_value"], "flight")
        self.assertEqual(repository.events[-1]["session_id"], "s3")

    def test_delete_hides_active_value_and_keeps_event(self):
        repository = InMemoryPreferenceRepository()
        repository.upsert(
            "u1",
            "s1",
            PreferenceCandidate(
                preference_key="preferred_seat_class",
                value="二等座",
            ),
        )

        repository.delete("u1", "s2", "preferred_seat_class", "忘掉座位偏好")

        self.assertEqual(repository.list_active("u1"), [])
        self.assertEqual(repository.events[-1]["operation"], "delete")
        self.assertEqual(repository.events[-1]["old_value"], "二等座")
        self.assertIsNone(repository.events[-1]["new_value"])

    def test_blank_identity_is_rejected(self):
        repository = InMemoryPreferenceRepository()
        with self.assertRaisesRegex(ValueError, "user_id 不能为空"):
            repository.list_active("")
        with self.assertRaisesRegex(ValueError, "session_id 不能为空"):
            repository.upsert(
                "u1",
                "",
                PreferenceCandidate(
                    preference_key="preferred_transport",
                    value="train",
                ),
            )


class FakeCursor:
    def __init__(self, old_row=None, active_rows=None, fail_on_execute=None):
        self.old_row = old_row
        self.active_rows = active_rows or []
        self.fail_on_execute = fail_on_execute
        self.statements = []

    def execute(self, sql, params):
        self.statements.append((sql, params))
        if self.fail_on_execute and self.fail_on_execute in sql:
            raise RuntimeError("database failure")

    def fetchone(self):
        return self.old_row

    def fetchall(self):
        return self.active_rows

    def close(self):
        return None


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self, **_kwargs):
        return self._cursor

    def start_transaction(self):
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


class MySqlPreferenceRepositoryTest(unittest.TestCase):
    def test_upsert_uses_parameters_and_commits_preference_with_event(self):
        malicious_user = "u1'; DROP TABLE travel_user_preferences; --"
        cursor = FakeCursor(old_row={"value_json": '"train"'})
        connection = FakeConnection(cursor)
        repository = MySqlPreferenceRepository(lambda: connection)

        record = repository.upsert(
            malicious_user,
            "s1",
            PreferenceCandidate(
                preference_key="preferred_transport",
                value="flight",
                source_text="以后坐飞机",
            ),
        )

        self.assertEqual(record.user_id, malicious_user)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(len(cursor.statements), 3)
        for sql, _params in cursor.statements:
            self.assertNotIn(malicious_user, sql)
            self.assertIn("%s", sql)
        self.assertIn(malicious_user, cursor.statements[0][1])

    def test_upsert_rolls_back_when_event_insert_fails(self):
        cursor = FakeCursor(fail_on_execute="INSERT INTO travel_preference_events")
        connection = FakeConnection(cursor)
        repository = MySqlPreferenceRepository(lambda: connection)

        with self.assertRaisesRegex(RuntimeError, "database failure"):
            repository.upsert(
                "u1",
                "s1",
                PreferenceCandidate(
                    preference_key="preferred_transport",
                    value="train",
                ),
            )

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.closed, 1)


if __name__ == "__main__":
    unittest.main()
