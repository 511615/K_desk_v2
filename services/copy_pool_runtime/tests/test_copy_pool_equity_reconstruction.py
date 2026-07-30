from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from copy_pool_equity_reconstruction import (
    AccountMoneyEvent,
    DailyEquityAnchor,
    PositionFloatingSnapshot,
    PositionInterval,
    reconstruct_intraday_equity,
)


UTC = timezone.utc


class IntradayEquityReconstructionTests(unittest.TestCase):
    def test_two_positions_emit_only_after_both_have_snapshot(self) -> None:
        start = datetime(2026, 7, 1, tzinfo=UTC)
        result = reconstruct_intraday_equity(
            [DailyEquityAnchor(start, 10_000, 10_000)],
            [],
            [
                PositionInterval("a", start + timedelta(hours=1), start + timedelta(hours=4)),
                PositionInterval("b", start + timedelta(hours=1), start + timedelta(hours=4)),
            ],
            [
                PositionFloatingSnapshot(start + timedelta(hours=2), "a", -100),
                PositionFloatingSnapshot(start + timedelta(hours=2, seconds=1), "b", -50),
            ],
        )
        self.assertEqual(result.emitted_intraday_points, 1)
        self.assertEqual(result.points[-1].equity_usd, 9_850)
        self.assertTrue(result.intraday_complete)

    def test_snapshot_sync_gap_over_two_seconds_fails_closed(self) -> None:
        start = datetime(2026, 7, 1, tzinfo=UTC)
        result = reconstruct_intraday_equity(
            [DailyEquityAnchor(start, 10_000, 10_000)], [],
            [
                PositionInterval("a", start + timedelta(hours=1), start + timedelta(hours=4)),
                PositionInterval("b", start + timedelta(hours=1), start + timedelta(hours=4)),
            ],
            [
                PositionFloatingSnapshot(start + timedelta(hours=2), "a", -100),
                PositionFloatingSnapshot(start + timedelta(hours=2, seconds=3), "b", -50),
            ],
        )
        self.assertFalse(result.intraday_complete)
        self.assertIn("unsynchronized_position_snapshot_coverage", result.reasons)

    def test_money_delta_and_external_cashflow_are_separate(self) -> None:
        start = datetime(2026, 7, 1, tzinfo=UTC)
        result = reconstruct_intraday_equity(
            [DailyEquityAnchor(start, 10_000, 10_000)],
            [AccountMoneyEvent(start + timedelta(hours=1), 1, 100, 100)],
            [],
            [],
        )
        self.assertEqual(result.points[-1].equity_usd, 10_100)
        self.assertEqual(result.points[-1].external_cashflow_usd, 100)
        self.assertTrue(result.intraday_complete)

    def test_missing_position_snapshots_fail_closed(self) -> None:
        start = datetime(2026, 7, 1, tzinfo=UTC)
        result = reconstruct_intraday_equity(
            [DailyEquityAnchor(start, 10_000, 10_000)],
            [],
            [PositionInterval("a", start, start + timedelta(hours=2))],
            [],
        )
        self.assertFalse(result.intraday_complete)
        self.assertIn("missing_position_snapshot_coverage", result.reasons)
        self.assertIn("missing_intraday_equity_points", result.reasons)


if __name__ == "__main__":
    unittest.main()
