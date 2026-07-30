from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from copy_delay_replay_domain import PositionExecutionEvent, PositionLifecycle
from copy_pool_equity_reconstruction import ReconstructedEquity
from copy_pool_factor_domain import AdjustedEquityPoint, TradeHoldingObservation
from copy_pool_factor_service import CopyPoolFactorService
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
