import json
import unittest

from SmartVoyage.mcp_server.mcp_weather_server import WeatherService
from SmartVoyage.query_data.query1 import TicketService
from SmartVoyage.query_data.sql_guard import validate_read_only_query


class RecordingCursor:
    def __init__(self, statements):
        self.statements = statements

    def execute(self, sql):
        self.statements.append(sql)

    def fetchall(self):
        return []

    def close(self):
        return None


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def cursor(self, **_kwargs):
        return RecordingCursor(self.statements)


class SqlGuardTest(unittest.TestCase):
    def test_accepts_single_select_for_allowed_table(self):
        sql = validate_read_only_query(
            "SELECT price FROM train_tickets WHERE id = 1",
            frozenset({"train_tickets"}),
        )

        self.assertEqual(sql, "SELECT price FROM train_tickets WHERE id = 1")

    def test_accepts_terminal_semicolon_and_removes_it(self):
        sql = validate_read_only_query(
            " SELECT city FROM weather_data; ",
            frozenset({"weather_data"}),
        )

        self.assertEqual(sql, "SELECT city FROM weather_data")

    def test_rejects_stacked_delete(self):
        with self.assertRaisesRegex(ValueError, "只允许单条只读 SELECT"):
            validate_read_only_query(
                "SELECT * FROM train_tickets; DELETE FROM train_tickets",
                frozenset({"train_tickets"}),
            )

    def test_rejects_drop_hidden_after_select(self):
        with self.assertRaisesRegex(ValueError, "只允许单条只读 SELECT"):
            validate_read_only_query(
                "SELECT * FROM train_tickets DROP TABLE train_tickets",
                frozenset({"train_tickets"}),
            )

    def test_rejects_sql_comments(self):
        for sql in (
            "SELECT * FROM train_tickets -- ignore guard",
            "SELECT * FROM train_tickets /* ignore guard */",
            "SELECT * FROM train_tickets # ignore guard",
        ):
            with self.subTest(sql=sql):
                with self.assertRaisesRegex(ValueError, "不允许 SQL 注释"):
                    validate_read_only_query(
                        sql,
                        frozenset({"train_tickets"}),
                    )

    def test_rejects_disallowed_table(self):
        with self.assertRaisesRegex(ValueError, "不允许访问数据表"):
            validate_read_only_query(
                "SELECT * FROM mysql.user",
                frozenset({"train_tickets"}),
            )

    def test_rejects_allowed_table_name_from_another_schema(self):
        with self.assertRaisesRegex(ValueError, "不允许访问数据表"):
            validate_read_only_query(
                "SELECT * FROM mysql.train_tickets",
                frozenset({"train_tickets"}),
            )

    def test_rejects_select_into_outfile(self):
        with self.assertRaisesRegex(ValueError, "禁止文件或变量输出"):
            validate_read_only_query(
                "SELECT * FROM train_tickets INTO OUTFILE 'tickets.txt'",
                frozenset({"train_tickets"}),
            )

    def test_rejects_query_without_table(self):
        with self.assertRaisesRegex(ValueError, "查询必须访问允许的数据表"):
            validate_read_only_query("SELECT 1", frozenset({"train_tickets"}))

    def test_ticket_service_rejects_mutation_before_cursor_execution(self):
        service = TicketService.__new__(TicketService)
        service.conn = RecordingConnection()

        result = json.loads(service.execute_query("DROP TABLE train_tickets"))

        self.assertEqual(result["status"], "error")
        self.assertEqual(service.conn.statements, [])

    def test_weather_service_rejects_mutation_before_cursor_execution(self):
        service = WeatherService.__new__(WeatherService)
        service.conn = RecordingConnection()

        result = json.loads(service.execute_query("DELETE FROM weather_data"))

        self.assertEqual(result["status"], "error")
        self.assertEqual(service.conn.statements, [])


if __name__ == "__main__":
    unittest.main()
