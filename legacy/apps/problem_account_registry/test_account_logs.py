import unittest
from datetime import datetime
from unittest.mock import patch

from account_logs import query_account_logs


class AccountLogTests(unittest.TestCase):
    def test_queries_mt5_and_mt4_rows_and_sorts_newest_first(self):
        sources = [
            {"name": "AC GB MT5", "kind": "mt5_deals", "schema": "mt5_schema", "table": "mt5_deals"},
            {"name": "AC MT4", "kind": "mt4_trades", "schema": "mt4_schema", "table": "mt4_trades"},
        ]

        class Cursor:
            def __init__(self, source):
                self.source = source
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, args):
                if self.source["kind"] == "mt5_deals":
                    self.rows = [{"Deal": 10, "TimeMsc": datetime(2026, 7, 15, 3, 8, 11), "Symbol": "XAUUSD.CS", "Login": 616901}]
                else:
                    self.rows = [{"TICKET": 20, "OPEN_TIME": datetime(2026, 7, 15, 3, 8, 9), "SYMBOL": "EURUSD", "LOGIN": 616901}]

            def fetchall(self):
                return self.rows

        class Connection:
            def __init__(self, source):
                self.source = source

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return Cursor(self.source)

        def connect(source):
            return Connection(source)

        result = query_account_logs("616901", "2026-07-15 03:00:00", "2026-07-15 03:20:00", sources, connect)
        self.assertEqual(result["matchedCount"], 2)
        self.assertEqual([row["ticket"] for row in result["rows"]], [10, 20])
        self.assertEqual(result["source"], "MySQL trade export")

    def test_rejects_invalid_range(self):
        with self.assertRaisesRegex(ValueError, "结束时间"):
            query_account_logs("616901", "2026-07-15 04:00:00", "2026-07-15 03:00:00", [], lambda source: None)

    def test_returns_warning_when_a_source_is_unavailable(self):
        sources = [{"name": "AC GB MT5", "kind": "mt5_deals", "schema": "s", "table": "t"}]
        result = query_account_logs("616901", "2026-07-15 03:00:00", "2026-07-15 03:20:00", sources, lambda source: (_ for _ in ()).throw(RuntimeError("offline")))
        self.assertEqual(result["matchedCount"], 0)
        self.assertIn("offline", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()
