from __future__ import annotations

import unittest
from datetime import datetime, timezone

from copy_pool_history_adapter import (
    build_mt4_equity_points,
    build_mt4_lifecycles,
    build_mt5_equity_points,
    build_mt5_lifecycles,
    coverage_from_flags,
    holding_observations_from_lifecycles,
    holding_observations_from_snapshot_paths,
)
from copy_trading_live_core import datetime_to_filetime


def product(value: object) -> str | None:
    return "XAUUSD" if str(value).upper().startswith("XAUUSD") else None


class HistoryAdapterTests(unittest.TestCase):
    def test_mt5_groups_complete_positions_and_keeps_losses(self) -> None:
        rows = []
        for position_id, profit, offset in ((10, 12.0, 0), (11, -7.0, 10_000)):
            rows.extend([
                {"Deal": position_id * 10, "PositionID": position_id, "TimeMscEpoch": 1_000 + offset,
                 "Action": 0, "Entry": 0, "Symbol": "XAUUSD.a", "VolumeExt": 1_000_000,
                 "Price": 3300.0, "ContractSize": 100.0, "RateProfit": 1.0},
                {"Deal": position_id * 10 + 1, "PositionID": position_id, "TimeMscEpoch": 2_000 + offset,
                 "Action": 1, "Entry": 1, "Symbol": "XAUUSD.a", "VolumeExt": 1_000_000,
                 "Price": 3301.0, "ContractSize": 100.0, "RateProfit": 1.0,
                 "Profit": profit, "Commission": -1.0},
            ])
        result = build_mt5_lifecycles(rows, account_key="a", product_resolver=product)
        self.assertEqual([item.position_id for item in result], ["10", "11"])
        self.assertEqual(sum(event.source_profit for item in result for event in item.events), 5.0)

    def test_mt5_excludes_open_positions_from_delay_sample(self) -> None:
        rows = [{"Deal": 1, "PositionID": 10, "TimeMscEpoch": 1_000, "Action": 0, "Entry": 0,
                 "Symbol": "XAUUSD", "VolumeExt": 1_000_000, "Price": 3300.0,
                 "ContractSize": 100.0, "RateProfit": 1.0}]
        self.assertEqual(build_mt5_lifecycles(rows, account_key="a", product_resolver=product), ())

    def test_mt4_builds_two_event_lifecycle_and_holding(self) -> None:
        rows = [{"TICKET": 5, "CMD": 1, "SYMBOL": "XAUUSD", "VOLUME": 2,
                 "OPEN_TIME": "2026-07-20T00:00:00+00:00", "CLOSE_TIME": "2026-07-20T01:00:00+00:00",
                 "OPEN_PRICE": 3300.0, "CLOSE_PRICE": 3290.0, "PROFIT": 20.0,
                 "COMMISSION": -1.0, "SWAPS": -0.5, "TAXES": 0.0}]
        result = build_mt4_lifecycles(rows, account_key="a", product_resolver=product,
                                      contract_size_resolver=lambda _value: 100.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].events[0].action, 1)
        self.assertEqual(result[0].events[1].action, 0)
        holding = holding_observations_from_lifecycles(result)
        self.assertEqual(holding[0].swap_usd, -0.5)
        self.assertEqual((holding[0].closed_at - holding[0].opened_at).total_seconds(), 3600)

        enriched, complete = holding_observations_from_snapshot_paths(
            result,
            {"5": [
                (datetime(2026, 7, 20, 0, 10, tzinfo=timezone.utc), -2.0),
                (datetime(2026, 7, 20, 0, 40, tzinfo=timezone.utc), 3.0),
            ]},
        )
        self.assertTrue(complete)
        self.assertEqual(enriched[0].long_loss_seconds, 1800)

    def test_equity_mapping_excludes_agent_and_so_from_mt5(self) -> None:
        timestamp = datetime(2026, 7, 28, tzinfo=timezone.utc)
        points = build_mt5_equity_points([{
            "Timestamp": datetime_to_filetime(timestamp), "ProfitEquity": 10_100,
            "DailyBalance": 100, "DailyCredit": 10, "DailyCharge": -2,
            "DailyCorrection": 1, "DailyBonus": 3, "DailyAgent": 4,
            "DailySOCompensation": 5, "DailySOCompensationCredit": 6,
            "DailyProfit": 50, "DailyStorage": -1,
        }])
        self.assertEqual(points[0].equity_usd, 10_100)
        self.assertEqual(points[0].external_cashflow_usd, 127)
        self.assertEqual(points[0].timestamp, timestamp)

    def test_mt4_equity_and_coverage_fail_closed(self) -> None:
        points = build_mt4_equity_points([
            {"TIME": "2026-07-27T00:00:00+00:00", "EQUITY": 9_900,
             "DEPOSIT": 0, "CREDIT": 20},
            {"TIME": "2026-07-28T00:00:00+00:00", "EQUITY": 10_000,
             "DEPOSIT": 100, "CREDIT": 10},
        ], money_scale=0.01)
        self.assertEqual(points[1].equity_usd, 100)
        self.assertEqual(points[0].external_cashflow_usd, 0.0)
        self.assertEqual(points[1].external_cashflow_usd, 0.9)
        coverage = coverage_from_flags(
            lifecycle_complete=True, daily_equity_complete=True,
            intraday_equity_complete=False, holding_path_complete=False,
            tick_complete=True,
        )
        self.assertFalse(coverage.factor_ready)
        self.assertEqual(coverage.reasons, ("missing_intraday_equity_complete", "missing_holding_path_complete"))


if __name__ == "__main__":
    unittest.main()
