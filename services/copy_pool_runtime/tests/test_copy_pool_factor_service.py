from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from copy_delay_replay_domain import PositionExecutionEvent, PositionLifecycle
from copy_pool_equity_reconstruction import ReconstructedEquity
from copy_pool_factor_domain import AdjustedEquityPoint, TradeHoldingObservation
from copy_pool_factor_service import CopyPoolFactorService, apply_cost_factor_model
from copy_pool_history_repository import (
    AccountHistoryBundle,
    SleeveHistoryBundle,
    SourceHistoryBundle,
)


class FakeRange:
    def __init__(self, ticks, complete=True):
        self.ticks = ticks
        self.complete = complete
        self.missing_dates = ()
        self.incomplete_dates = ()
        self.closed = False

    def close(self):
        self.closed = True


class FakeCache:
    def __init__(self, quote_range):
        self.quote_range = quote_range
        self.load_calls = 0

    def load_range(self, *_args, **_kwargs):
        self.load_calls += 1
        return self.quote_range


class FakeRepository:
    def __init__(self, bundle):
        self.bundle = bundle

    def load_source(self, _source, _frame, _as_of):
        return self.bundle


def lifecycle(position_id: str, opened_ms: int, closed_ms: int) -> PositionLifecycle:
    return PositionLifecycle(
        "route:7", "XAUUSD", position_id, 100.0, 1.0,
        (
            PositionExecutionEvent(f"{position_id}:o", opened_ms, 0, 0, 0.01,
                                   source_sequence=1, source_price=100.0),
            PositionExecutionEvent(f"{position_id}:c", closed_ms, 1, 1, 0.01,
                                   source_profit=3.0, source_sequence=2, source_price=103.0),
        ),
    )


class FactorServiceTests(unittest.TestCase):
    def test_cost_model_uses_product_volume_minimum_for_non_micro_products(self) -> None:
        frame = pd.DataFrame([{
            "sleeve_key": "route:apple|Apple", "product": "Apple",
            "closes_5d": 2, "closes_20d": 10, "lots_20d": 100.0,
            "net_5d_usd": 300.0, "net_20d_usd": 500.0,
            "factor_ready": True, "factor_gate_reasons": "",
        }])

        result = apply_cost_factor_model(frame).iloc[0]

        # Apple has a 10-share minimum. Ten source closes totalling 100
        # shares therefore copy at 10 shares per close, not 0.01 lots.
        self.assertAlmostEqual(result["factor_copy_net_20d_usd"], 500.0)
        self.assertAlmostEqual(result["factor_estimated_copy_cost_20d_usd"], 250.0)
        self.assertAlmostEqual(result["factor_cost_adjusted_net_20d_usd"], 250.0)
        self.assertAlmostEqual(result["factor_cost_coverage"], 2.0)
        self.assertTrue(bool(result["factor_ready"]))

    def test_missing_or_nan_cost_evidence_fails_closed_without_legacy_fallback(self) -> None:
        complete = pd.DataFrame([{
            "sleeve_key": "route:1|XAUUSD", "product": "XAUUSD",
            "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
            "net_5d_usd": 20.0, "net_20d_usd": 300.0,
            "factor_ready": True, "factor_gate_reasons": "",
        }])
        missing = complete.drop(columns=["lots_20d"])
        nan_value = complete.copy()
        nan_value.loc[0, "lots_20d"] = float("nan")

        for frame in (missing, nan_value):
            result = apply_cost_factor_model(frame).iloc[0]
            self.assertFalse(bool(result["factor_ready"]))
            self.assertIn("missing_copy_cost_evidence", result["factor_gate_reasons"])
            self.assertEqual(result["factor_model"], "cost_profit_recent_coverage_v1")

    def test_cost_factor_model_uses_copy_lot_costs_weighted_50_30_20_and_hard_gates(self) -> None:
        frame = pd.DataFrame([
            {
                "sleeve_key": "route:1|XAUUSD", "product": "XAUUSD",
                "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
                "net_5d_usd": 20.0, "net_20d_usd": 300.0,
                "factor_ready": True, "factor_gate_reasons": "",
            },
            {
                "sleeve_key": "route:2|XAUUSD", "product": "XAUUSD",
                "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
                "net_5d_usd": 50.0, "net_20d_usd": 200.0,
                "factor_ready": False, "factor_gate_reasons": "legacy_hard_gate",
            },
            {
                "sleeve_key": "route:3|XAUUSD", "product": "XAUUSD",
                "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
                "net_5d_usd": 20.0, "net_20d_usd": 100.0,
                "factor_ready": True, "factor_gate_reasons": "",
            },
            {
                "sleeve_key": "route:4|XAUUSD", "product": "XAUUSD",
                "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
                "net_5d_usd": 1.0, "net_20d_usd": 20.0,
                "factor_ready": True, "factor_gate_reasons": "",
            },
        ])

        result = apply_cost_factor_model(frame).set_index("sleeve_key")
        strongest = result.loc["route:1|XAUUSD"]
        rejected = result.loc["route:4|XAUUSD"]

        # Ten source closes totalling one lot imply 0.10 average lots, so the
        # 0.01 Demo copy scale is 10%. XAUUSD's reserved round-trip cost is
        # 0.75 USD per copied close (0.01 lot x 1.25 reserve).
        self.assertAlmostEqual(strongest["factor_copy_net_20d_usd"], 30.0)
        self.assertAlmostEqual(strongest["factor_estimated_copy_cost_20d_usd"], 7.5)
        self.assertAlmostEqual(strongest["factor_cost_adjusted_net_20d_usd"], 22.5)
        # Percentiles are calculated only after every hard gate, so the
        # legacy-hard-failed and after-cost-failed rows cannot move the score.
        self.assertAlmostEqual(strongest["factor_base_score"], 0.925)
        self.assertAlmostEqual(
            strongest["factor_base_score"],
            0.50 * strongest["factor_rank_cost_profit"]
            + 0.30 * strongest["factor_rank_recent_strength"]
            + 0.20 * strongest["factor_rank_cost_coverage"],
        )
        self.assertFalse(bool(result.loc["route:2|XAUUSD", "factor_ready"]))
        self.assertIn("legacy_hard_gate", result.loc["route:2|XAUUSD", "factor_gate_reasons"])
        self.assertFalse(bool(rejected["factor_ready"]))
        self.assertIn("cost_adjusted_net_5d_not_positive", rejected["factor_gate_reasons"])
        self.assertIn("cost_adjusted_net_20d_not_positive", rejected["factor_gate_reasons"])
        self.assertIn("cost_coverage_below_1", rejected["factor_gate_reasons"])

    def setUp(self) -> None:
        self.as_of = datetime(2026, 7, 29, tzinfo=timezone.utc)
        opened = int((self.as_of - timedelta(hours=2)).timestamp() * 1000)
        closed = int((self.as_of - timedelta(hours=1)).timestamp() * 1000)
        self.lifecycle = lifecycle("p1", opened, closed)
        equity = ReconstructedEquity(
            points=(
                AdjustedEquityPoint(self.as_of - timedelta(days=61), 10_000),
                AdjustedEquityPoint(self.as_of - timedelta(days=20), 10_100),
                AdjustedEquityPoint(self.as_of - timedelta(days=1), 10_200),
                AdjustedEquityPoint(self.as_of, 10_300),
            ),
            intraday_complete=True, reasons=(), emitted_intraday_points=2,
            skipped_incomplete_snapshots=0,
        )
        account = AccountHistoryBundle("route:7", equity, False)
        holding = TradeHoldingObservation(
            self.as_of - timedelta(hours=2), self.as_of - timedelta(hours=1),
            0.0, 3.0, long_loss_seconds=60,
        )
        sleeve = SleeveHistoryBundle("route:7", "XAUUSD", (self.lifecycle,), (holding,), True)
        self.bundle = SourceHistoryBundle({"route:7": account}, {"route:7|XAUUSD": sleeve})
        rows = []
        for base, bid, ask in ((opened, 100.0, 100.1), (closed, 103.9, 104.0)):
            for offset in (0, 500, 1_000, 1_500, 2_000, 3_000, 5_000):
                rows.append((base + offset, bid, ask))
        self.ticks = np.array(sorted(rows), dtype=[("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8")])
        self.frame = pd.DataFrame([{
            "physical_key": "source", "account_key": "route:7", "sleeve_key": "route:7|XAUUSD",
            "product": "XAUUSD", "ret_5d": 0.05, "ret_20d": 0.10,
            "stress_ret_20d": 0.08, "pf_20d": 2.0, "hold_p25_seconds": 3600,
            "closes_5d": 1, "closes_20d": 1, "lots_20d": 0.10,
            "net_5d_usd": 20.0, "net_20d_usd": 40.0,
        }])

    def test_complete_evidence_produces_traceable_factor_row(self) -> None:
        quote_range = FakeRange(self.ticks)
        service = CopyPoolFactorService(
            FakeCache(quote_range), historical_delay_enabled=True,
            history_repository=FakeRepository(self.bundle),
        )
        result = service.evaluate({"source": object()}, self.frame, self.as_of)
        self.assertTrue(bool(result.iloc[0]["factor_ready"]))
        self.assertGreater(result.iloc[0]["delay_score"], 0)
        self.assertEqual(result.iloc[0]["entry_p95_ms"], 1500)
        self.assertEqual(result.iloc[0]["mdd_60d"], 0)
        self.assertTrue(quote_range.closed)

    def test_missing_quote_partition_fails_closed(self) -> None:
        quote_range = FakeRange(np.empty(0, dtype=self.ticks.dtype), complete=False)
        service = CopyPoolFactorService(
            FakeCache(quote_range), historical_delay_enabled=True,
            history_repository=FakeRepository(self.bundle),
        )
        result = service.evaluate({"source": object()}, self.frame, self.as_of)
        self.assertFalse(bool(result.iloc[0]["factor_ready"]))
        self.assertIn("missing_or_incomplete_quote_range", result.iloc[0]["factor_gate_reasons"])

    def test_deferred_delay_factor_does_not_load_ticks_or_reject_missing_quotes(self) -> None:
        quote_range = FakeRange(np.empty(0, dtype=self.ticks.dtype), complete=False)
        cache = FakeCache(quote_range)
        service = CopyPoolFactorService(
            cache, historical_delay_enabled=False,
            history_repository=FakeRepository(self.bundle),
        )

        result = service.evaluate({"source": object()}, self.frame, self.as_of)

        self.assertEqual(cache.load_calls, 0)
        self.assertTrue(bool(result.iloc[0]["factor_ready"]))
        self.assertFalse(bool(result.iloc[0]["historical_delay_enabled"]))
        self.assertEqual(result.iloc[0]["delay_factor_status"], "deferred_v0_1")
        self.assertNotIn("missing_or_incomplete_quote_range", result.iloc[0]["factor_gate_reasons"])

    def test_cost_model_scales_source_profit_to_demo_lot_before_cost(self) -> None:
        frame = self.frame.assign(
            closes_5d=2,
            closes_20d=10,
            lots_20d=1.0,
            net_5d_usd=10.0,
            net_20d_usd=50.0,
            money_scale=1.0,
        )
        service = CopyPoolFactorService(
            FakeCache(FakeRange(np.empty(0, dtype=self.ticks.dtype), complete=False)),
            historical_delay_enabled=False,
            history_repository=FakeRepository(self.bundle),
        )

        result = service.evaluate({"source": object()}, frame, self.as_of).iloc[0]

        self.assertEqual(result["factor_model"], "cost_profit_recent_coverage_v1")
        self.assertAlmostEqual(result["factor_copy_net_20d_usd"], 5.0)
        self.assertAlmostEqual(result["factor_estimated_copy_cost_20d_usd"], 7.5)
        self.assertAlmostEqual(result["factor_cost_adjusted_net_20d_usd"], -2.5)
        self.assertAlmostEqual(result["factor_cost_coverage"], 5.0 / 7.5)
        self.assertFalse(bool(result["factor_ready"]))
        self.assertIn("cost_adjusted_net_20d_not_positive", result["factor_gate_reasons"])

    def test_incomplete_intraday_paths_are_disclosed_and_penalized_not_hard_clean(self) -> None:
        account = self.bundle.accounts["route:7"]
        incomplete_account = AccountHistoryBundle(
            account.account_key,
            ReconstructedEquity(
                points=account.equity.points,
                intraday_complete=False,
                reasons=("missing_position_snapshot_coverage",),
                emitted_intraday_points=0,
                skipped_incomplete_snapshots=1,
            ),
            False,
        )
        sleeve = self.bundle.sleeves["route:7|XAUUSD"]
        incomplete_sleeve = SleeveHistoryBundle(
            sleeve.account_key, sleeve.product, sleeve.lifecycles,
            sleeve.holdings, False,
        )
        bundle = SourceHistoryBundle(
            {"route:7": incomplete_account},
            {"route:7|XAUUSD": incomplete_sleeve},
        )
        service = CopyPoolFactorService(
            FakeCache(FakeRange(np.empty(0, dtype=self.ticks.dtype), complete=False)),
            historical_delay_enabled=False,
            history_repository=FakeRepository(bundle),
        )

        result = service.evaluate({"source": object()}, self.frame, self.as_of).iloc[0]

        self.assertTrue(bool(result["factor_ready"]))
        self.assertFalse(bool(result["holding_path_complete"]))
        self.assertFalse(bool(result["intraday_equity_complete"]))
        self.assertLess(result["factor_holding_quality"], 1.0)
        self.assertNotIn("missing_holding_snapshot_path", result["factor_gate_reasons"])


if __name__ == "__main__":
    unittest.main()
