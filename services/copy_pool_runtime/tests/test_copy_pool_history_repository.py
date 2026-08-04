from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd
from copy_pool_history_repository import ReadOnlyPoolHistoryRepository
from copy_trading_live_core import datetime_to_filetime
from pymysql.err import OperationalError


class FakeSource:
    platform = "MT5"
    schema = "safe_schema"

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def query(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        self.assert_read_only(sql)
        if "mt5_daily_view" in sql:
            return [{
                "Login": 7, "Timestamp": datetime_to_filetime(self.now - timedelta(days=61)),
                "Balance": 10_000, "Credit": 0, "ProfitEquity": 10_000,
                "DailyBalance": 0, "DailyCredit": 0, "DailyCharge": 0,
                "DailyCorrection": 0, "DailyBonus": 0, "DailyAgent": 0,
                "DailySOCompensation": 0, "DailySOCompensationCredit": 0,
            }]
        if "mt5_deals" in sql:
            return [
                {"Login": 7, "Deal": 10, "PositionID": 99,
                 "TimeMsc": (self.now - timedelta(hours=2)).astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None),
                 "Action": 0, "Entry": 0, "Symbol": "XAUUSD", "Volume": 100,
                 "VolumeExt": 1_000_000, "Price": 3300.0, "Profit": 0,
                 "Commission": 0, "Storage": 0, "Fee": 0, "ContractSize": 100,
                 "RateProfit": 1},
                {"Login": 7, "Deal": 11, "PositionID": 99,
                 "TimeMsc": (self.now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None),
                 "Action": 1, "Entry": 1, "Symbol": "XAUUSD", "Volume": 100,
                 "VolumeExt": 1_000_000, "Price": 3301.0, "Profit": 1,
                 "Commission": -0.1, "Storage": 0, "Fee": 0, "ContractSize": 100,
                 "RateProfit": 1},
            ]
        if "mt5_positions_snap" in sql:
            return [{"Position": 99,
                     "TimeModify": (self.now - timedelta(hours=1, minutes=30)).astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None),
                     "Profit": -2, "Storage": 0}]
        if "mt5_accounts" in sql:
            return [{"Login": 7, "Balance": 10_001, "Credit": 0, "Equity": 10_001}]
        raise AssertionError(sql)

    @staticmethod
    def assert_read_only(sql: str) -> None:
        assert sql.lstrip().upper().startswith("SELECT")
        assert "ApiData" not in sql


class OutOfWindowAnchorSource(FakeSource):
    """Exposes old data only if the repository incorrectly reads beyond 61 days."""

    def query(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        self.assert_read_only(sql)
        if "mt5_daily_view" in sql:
            timestamp = (
                self.now - timedelta(days=90)
                if "mt5_daily_view history" in sql
                else self.now - timedelta(days=59)
            )
            if "mt5_daily_view history" in sql:
                lower, upper = (int(params[-2]), int(params[-1]))
                value = int(timestamp.timestamp())
                if not lower <= value < upper:
                    return []
            return [{
                "Login": 7, "Timestamp": datetime_to_filetime(timestamp),
                "Balance": 10_000, "Credit": 0, "ProfitEquity": 10_000,
                "DailyBalance": 0, "DailyCredit": 0, "DailyCharge": 0,
                "DailyCorrection": 0, "DailyBonus": 0, "DailyAgent": 0,
                "DailySOCompensation": 0, "DailySOCompensationCredit": 0,
            }]
        return super().query(sql, params)


class Mt4OutOfWindowAnchorSource(FakeSource):
    platform = "MT4"

    def query(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        self.assert_read_only(sql)
        if "mt4_daily" in sql:
            timestamp = (
                self.now - timedelta(days=90)
                if "mt4_daily history" in sql
                else self.now - timedelta(days=59)
            )
            if "mt4_daily history" in sql:
                lower, upper = params[-2], params[-1]
                if not lower <= timestamp.replace(tzinfo=None) < upper:
                    return []
            return [{
                "LOGIN": 7, "TIME": timestamp, "BALANCE": 10_000,
                "CREDIT": 0, "DEPOSIT": 0, "EQUITY": 10_000,
            }]
        if "mt4_trades " in sql or "mt4_trades_snap" in sql:
            return []
        if "mt4_users_view" in sql:
            return [{"LOGIN": 7, "BALANCE": 10_000, "CREDIT": 0, "EQUITY": 10_000}]
        raise AssertionError(sql)


class SplittingHistorySource:
    """Fake source which forces the repository to split oversized Login lists."""

    platform = "MT5"
    schema = "safe_schema"

    def __init__(
        self,
        now: datetime,
        *,
        failure: Exception | None = None,
        max_batch: int = 5,
    ) -> None:
        self.now = now
        self.failure = failure
        self.max_batch = max_batch
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.successful_batches: dict[str, list[tuple[int, ...]]] = {}
        self.reset_calls = 0

    def reset_connection(self) -> None:
        self.reset_calls += 1

    def query(self, sql: str, params=()):
        values = tuple(params)
        self.calls.append((sql, values))
        FakeSource.assert_read_only(sql)
        logins = tuple(int(value) for value in values if isinstance(value, int) and value < 1_000_000)
        stream = self._stream(sql)
        if self.failure is not None:
            raise self.failure
        if len(logins) > self.max_batch:
            raise OperationalError(2013, "Lost connection to MySQL server during query")
        self.successful_batches.setdefault(stream, []).append(logins)
        if "mt5_daily_view" in sql:
            return [self._daily(login) for login in logins]
        if "mt5_deals" in sql:
            return []
        if "mt5_accounts" in sql:
            return [{"Login": login, "Balance": 10_000, "Credit": 0, "Equity": 10_000} for login in logins]
        if "mt5_positions_snap" in sql:
            return []
        raise AssertionError(sql)

    def _daily(self, login: int) -> dict[str, object]:
        return {
            "Login": login,
            "Timestamp": datetime_to_filetime(self.now - timedelta(days=61)),
            "Balance": 10_000,
            "Credit": 0,
            "ProfitEquity": 10_000,
            "DailyBalance": 0,
            "DailyCredit": 0,
            "DailyCharge": 0,
            "DailyCorrection": 0,
            "DailyBonus": 0,
            "DailyAgent": 0,
            "DailySOCompensation": 0,
            "DailySOCompensationCredit": 0,
        }

    @staticmethod
    def _stream(sql: str) -> str:
        if "mt5_daily_view" in sql:
            return "daily_anchor" if "mt5_daily_view history" in sql else "daily"
        if "mt5_deals" in sql:
            return "deals"
        if "mt5_accounts" in sql:
            return "current"
        if "mt5_positions_snap" in sql:
            return "snapshots"
        raise AssertionError(sql)


class HistoryRepositoryTests(unittest.TestCase):
    @staticmethod
    def _candidates(logins: range | list[int]) -> pd.DataFrame:
        return pd.DataFrame([
            {
                "Login": login,
                "account_key": f"route:{login}",
                "money_scale": 1.0,
                "product": "XAUUSD",
            }
            for login in logins
        ])

    def test_mt5_history_is_bounded_and_position_snapshots_use_position_index(self) -> None:
        now = datetime(2026, 7, 29, 4, tzinfo=timezone.utc)
        source = FakeSource(now)
        frame = pd.DataFrame([{
            "Login": 7, "account_key": "route:7", "money_scale": 1.0,
            "product": "XAUUSD",
        }])
        result = ReadOnlyPoolHistoryRepository().load_source(source, frame, now)
        sleeve = result.sleeves["route:7|XAUUSD"]
        self.assertEqual(len(sleeve.lifecycles), 1)
        self.assertEqual(len(sleeve.holdings), 1)
        self.assertTrue(result.accounts["route:7"].equity.intraday_complete)
        snapshot_sql, snapshot_params = next(
            (sql, params) for sql, params in source.calls if "mt5_positions_snap" in sql
        )
        daily_sql, daily_params = next(
            (sql, params) for sql, params in source.calls if "mt5_daily_view" in sql
            and "mt5_daily_view history" not in sql
        )
        self.assertIn("Datetime >= %s", daily_sql)
        self.assertNotIn("Timestamp >= %s", daily_sql)
        self.assertEqual(daily_params[-2], int((now - timedelta(days=61)).timestamp()))
        self.assertEqual(daily_params[-1], int(now.timestamp()))
        self.assertFalse(any(
            "mt5_daily_view history" in sql for sql, _params in source.calls
        ))
        self.assertIn("WHERE Position IN", snapshot_sql)
        self.assertEqual(snapshot_params[0], 99)
        self.assertTrue(all("%s" in sql for sql, _params in source.calls))

    def test_mt5_daily_history_never_reads_beyond_the_bounded_61_day_window(self) -> None:
        now = datetime(2026, 7, 29, 4, tzinfo=timezone.utc)
        source = OutOfWindowAnchorSource(now)
        frame = pd.DataFrame([{
            "Login": 7, "account_key": "route:7", "money_scale": 1.0,
            "product": "XAUUSD",
        }])

        result = ReadOnlyPoolHistoryRepository().load_source(source, frame, now)

        timestamps = [point.timestamp for point in result.accounts["route:7"].equity.points]
        self.assertNotIn(now - timedelta(days=90), timestamps)
        self.assertIn(now - timedelta(days=59), timestamps)
        self.assertFalse(any(
            "mt5_daily_view history" in sql for sql, _params in source.calls
        ))

    def test_mt4_daily_history_never_reads_beyond_the_bounded_61_day_window(self) -> None:
        now = datetime(2026, 7, 29, 4, tzinfo=timezone.utc)
        source = Mt4OutOfWindowAnchorSource(now)

        result = ReadOnlyPoolHistoryRepository().load_source(
            source, self._candidates([7]), now
        )

        timestamps = [point.timestamp for point in result.accounts["route:7"].equity.points]
        self.assertNotIn(now - timedelta(days=90), timestamps)
        self.assertIn(now - timedelta(days=59), timestamps)
        self.assertFalse(any(
            "mt4_daily history" in sql for sql, _params in source.calls
        ))

    def test_transient_large_batches_split_per_history_stream_without_duplicate_or_missing_accounts(self) -> None:
        now = datetime(2026, 7, 29, 4, tzinfo=timezone.utc)
        logins = list(range(1, 52))
        source = SplittingHistorySource(now)

        result = ReadOnlyPoolHistoryRepository().load_source(source, self._candidates(logins), now)

        expected = set(logins)
        self.assertEqual(set(result.accounts), {f"route:{login}" for login in expected})
        self.assertEqual(set(result.sleeves), {f"route:{login}|XAUUSD" for login in expected})
        for stream in ("daily", "deals", "current"):
            successful = source.successful_batches[stream]
            flattened = [login for batch in successful for login in batch]
            self.assertEqual(set(flattened), expected, stream)
            self.assertEqual(len(flattened), len(expected), stream)
            self.assertTrue(all(len(batch) <= source.max_batch for batch in successful), stream)
            self.assertTrue(any(
                len(batch) > source.max_batch
                for batch in self._attempted_batches(source, stream)
            ), stream)
        self.assertNotIn("daily_anchor", source.successful_batches)
        self.assertGreater(source.reset_calls, 0)

    def test_transient_timeout_for_one_login_is_propagated_after_split_floor(self) -> None:
        now = datetime(2026, 7, 29, 4, tzinfo=timezone.utc)
        source = SplittingHistorySource(
            now,
            failure=OperationalError(1205, "Lock wait timeout exceeded"),
        )

        with self.assertRaisesRegex(OperationalError, "Lock wait timeout"):
            ReadOnlyPoolHistoryRepository().load_source(source, self._candidates([7]), now)

        self.assertEqual(len(source.calls), 1)
        self.assertEqual(source.reset_calls, 0)

    def test_non_transient_sql_error_is_not_retried_or_split(self) -> None:
        now = datetime(2026, 7, 29, 4, tzinfo=timezone.utc)
        source = SplittingHistorySource(
            now,
            failure=OperationalError(1064, "You have an error in your SQL syntax"),
        )

        with self.assertRaisesRegex(OperationalError, "SQL syntax"):
            ReadOnlyPoolHistoryRepository().load_source(source, self._candidates([7, 8]), now)

        self.assertEqual(len(source.calls), 1)
        self.assertEqual(source.reset_calls, 0)
        self.assertEqual(self._attempted_batches(source, "daily"), [(7, 8)])

    @staticmethod
    def _attempted_batches(source: SplittingHistorySource, stream: str) -> list[tuple[int, ...]]:
        return [
            tuple(int(value) for value in params if isinstance(value, int) and value < 1_000_000)
            for sql, params in source.calls
            if source._stream(sql) == stream
        ]


if __name__ == "__main__":
    unittest.main()
