import unittest
from unittest.mock import MagicMock, patch

from SmartVoyage.query_data.query1 import TicketService


class TicketServiceConnectionTest(unittest.TestCase):
    def test_connection_uses_autocommit_for_fresh_query_visibility(self):
        connection = MagicMock()

        with patch(
            "SmartVoyage.query_data.query1.mysql.connector.connect",
            return_value=connection,
        ) as connect:
            TicketService()

        self.assertTrue(connect.call_args.kwargs["autocommit"])


if __name__ == "__main__":
    unittest.main()
