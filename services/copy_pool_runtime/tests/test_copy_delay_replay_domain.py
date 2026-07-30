from __future__ import annotations

import unittest

from copy_delay_replay_domain import (
    ACTION_BUY,
    ACTION_SELL,
    ENTRY_IN,
    ENTRY_INOUT,
    ENTRY_OUT,
    PositionExecutionEvent,
    PositionLifecycle,
    QuoteTick,
    evaluate_delay_portfolio,
    evaluate_delay_scenarios,
    reconstruct_lifecycle,
    reconcile_source_lifecycle,
    replay_lifecycle,
)


def event(
    event_id: str | int,
    time_msc: int,
    entry: int,
    action: int,
    lots: float,
    *,
    source_price: float,
    source_profit: float = 0.0,
    source_sequence: int = 0,
    volume_closed_lots: float | None = None,
    commission: float = 0.0,
) -> PositionExecutionEvent:
    return PositionExecutionEvent(
        event_id,
        time_msc,
        entry,
        action,
        lots,
        commission=commission,
        source_profit=source_profit,
        source_sequence=source_sequence,
        source_price=source_price,
        volume_closed_lots=volume_closed_lots,
    )


def lifecycle(events: tuple[PositionExecutionEvent, ...]) -> PositionLifecycle:
    return PositionLifecycle("route:1", "XAUUSD", "p1", 1.0, 1.0, events)


def position(position_id: str, events: tuple[PositionExecutionEvent, ...]) -> PositionLifecycle:
    return PositionLifecycle("route:1", "XAUUSD", position_id, 1.0, 1.0, events)


class DelayReplayTests(unittest.TestCase):
    def test_bid_ask_sides_and_adverse_slippage_without_double_counting_spread(self) -> None:
        quotes = (QuoteTick(0, 100.0, 101.0), QuoteTick(1000, 104.0, 105.0), QuoteTick(2000, 110.0, 111.0), QuoteTick(3000, 105.0, 106.0))
        long_trade = lifecycle((event("o", 0, ENTRY_IN, ACTION_BUY, 1.0, source_price=101.0), event("c", 1000, ENTRY_OUT, ACTION_SELL, 1.0, source_price=104.0, source_profit=3.0)))
        short_trade = lifecycle((event("o", 2000, ENTRY_IN, ACTION_SELL, 1.0, source_price=110.0), event("c", 3000, ENTRY_OUT, ACTION_BUY, 1.0, source_price=106.0, source_profit=4.0)))
        self.assertEqual(replay_lifecycle(long_trade, quotes, slippage_price=0.5).net_profit, 2.0)
        self.assertEqual(replay_lifecycle(short_trade, quotes, slippage_price=0.5).net_profit, 3.0)
        self.assertTrue(reconcile_source_lifecycle(long_trade).reconciled)

    def test_entry_and_exit_p95_are_independent(self) -> None:
        quotes = (QuoteTick(0, 100, 101), QuoteTick(500, 100, 102), QuoteTick(1000, 105, 106), QuoteTick(1500, 103, 104))
        trade = lifecycle((event("o", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101), event("c", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=105, source_profit=4)))
        self.assertEqual(replay_lifecycle(trade, quotes, entry_delay_ms=500).net_profit, 3.0)
        self.assertEqual(replay_lifecycle(trade, quotes, exit_delay_ms=500).net_profit, 2.0)
        report = evaluate_delay_scenarios(trade, quotes, (500,), hold_p25_ms=6000, actual_entry_p95_ms=500, actual_exit_p95_ms=0, max_quote_wait_ms=10)
        self.assertEqual(report.actual_entry.net_profit, 3.0)
        self.assertEqual(report.actual_exit.net_profit, 4.0)
        self.assertEqual(report.actual_combined.net_profit, 3.0)

    def test_partial_close_reversal_and_costs_are_fifo_reconciled(self) -> None:
        partial = lifecycle((
            event("o", 0, ENTRY_IN, ACTION_BUY, 2, source_price=101, commission=-2),
            event("p", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=103, source_profit=2),
            event("c", 2000, ENTRY_OUT, ACTION_SELL, 1, source_price=104, source_profit=3),
        ))
        quotes = (QuoteTick(0, 100, 101), QuoteTick(1000, 103, 104), QuoteTick(2000, 104, 105), QuoteTick(3000, 100, 101))
        result = replay_lifecycle(partial, quotes)
        self.assertEqual(result.completed_trades, 2)
        self.assertEqual(result.net_profit, 3.0)
        self.assertTrue(reconcile_source_lifecycle(partial).reconciled)
        reverse = lifecycle((
            event("a", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101),
            event("b", 1000, ENTRY_INOUT, ACTION_SELL, 2, source_price=103, source_profit=2, volume_closed_lots=1),
            event("c", 3000, ENTRY_OUT, ACTION_BUY, 1, source_price=100, source_profit=3),
        ))
        rebuilt = reconstruct_lifecycle(reverse)
        self.assertTrue(rebuilt.valid)
        self.assertEqual([(item.kind, item.side, item.lots) for item in rebuilt.actions], [("entry", 1, 1), ("exit", -1, 1), ("entry", -1, 1), ("exit", 1, 1)])
        self.assertTrue(reconcile_source_lifecycle(reverse).reconciled)

    def test_source_sequence_not_event_id_controls_same_millisecond_order(self) -> None:
        trade = lifecycle((
            event("close-first-in-input", 0, ENTRY_OUT, ACTION_SELL, 1, source_price=104, source_profit=3, source_sequence=9),
            event("open-second-in-input", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101, source_sequence=2),
        ))
        rebuilt = reconstruct_lifecycle(trade)
        self.assertTrue(rebuilt.valid)
        self.assertEqual([item.event.event_id for item in rebuilt.actions], ["open-second-in-input", "close-first-in-input"])
        invalid = reconstruct_lifecycle(lifecycle((event("bad", 0, ENTRY_INOUT, ACTION_SELL, 1, source_price=100, volume_closed_lots=2),)))
        self.assertFalse(invalid.valid)
        self.assertIn("bad:invalid_volume_closed_lots", invalid.invalid_reasons)

    def test_quote_gap_closed_market_and_event_level_executability(self) -> None:
        trade = lifecycle((
            event("o", 0, ENTRY_IN, ACTION_BUY, 2, source_price=101),
            event("c", 1000, ENTRY_OUT, ACTION_SELL, 2, source_price=103, source_profit=4),
        ))
        gap = replay_lifecycle(trade, (QuoteTick(0, 100, 101), QuoteTick(1000, 102, 103)), entry_delay_ms=500, max_quote_wait_ms=200)
        closed = replay_lifecycle(trade, (), max_quote_wait_ms=200)
        self.assertEqual(gap.entry_executable_ratio, 0.0)
        self.assertEqual(gap.combined_executable_ratio, 0.0)
        self.assertEqual(closed.completed_source_events, 1)
        self.assertEqual(closed.combined_executable_ratio, 0.0)

    def test_reconciliation_failure_pf_zero_and_break_even_interpolation(self) -> None:
        quotes = (
            QuoteTick(0, 100, 101), QuoteTick(1000, 101, 102), QuoteTick(2000, 103, 104),
            QuoteTick(3000, 102, 103), QuoteTick(4000, 101, 102),
        )
        profitable = lifecycle((event("o", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101), event("c", 2000, ENTRY_OUT, ACTION_SELL, 1, source_price=103, source_profit=2)))
        report = evaluate_delay_scenarios(profitable, quotes, (1000, 2000), hold_p25_ms=9000, actual_entry_p95_ms=1000, actual_exit_p95_ms=1000, max_quote_wait_ms=10)
        self.assertTrue(report.reconciled)
        self.assertGreater(report.delay_score, 0.0)
        self.assertAlmostEqual(report.entry_break_even.delay_ms, 1500.0)
        self.assertLessEqual(report.conservative_break_even.delay_ms, report.entry_break_even.delay_ms)
        loss = lifecycle((event("o", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101), event("c", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=99, source_profit=-2)))
        zero_pf = evaluate_delay_scenarios(loss, (QuoteTick(0, 100, 101), QuoteTick(1000, 99, 100)), (0,), hold_p25_ms=3000, actual_entry_p95_ms=0, actual_exit_p95_ms=0)
        self.assertEqual(zero_pf.baseline.profit_factor, 0.0)
        self.assertEqual(zero_pf.actual_combined.profit_factor, 0.0)
        self.assertFalse(zero_pf.hard_gate_passed)
        mismatch = lifecycle((event("o", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101), event("c", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=104, source_profit=99)))
        failed = evaluate_delay_scenarios(mismatch, (QuoteTick(0, 100, 101), QuoteTick(1000, 104, 105)), (500,), hold_p25_ms=3000, actual_entry_p95_ms=500, actual_exit_p95_ms=500)
        self.assertFalse(failed.reconciled)
        self.assertIn("source_profit_reconciliation_mismatch", failed.hard_gate_reasons)

    def test_portfolio_aggregates_complete_positions_without_dropping_losses(self) -> None:
        quotes = (
            QuoteTick(0, 100, 101), QuoteTick(1000, 105, 106),
            QuoteTick(2000, 100, 101), QuoteTick(3000, 99, 100),
        )
        profitable_partial = position("p1", (
            event("o", 0, ENTRY_IN, ACTION_BUY, 2, source_price=101),
            event("p", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=105, source_profit=4),
            event("c", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=105, source_profit=4, source_sequence=1),
        ))
        losing = position("p2", (
            event("o", 2000, ENTRY_IN, ACTION_BUY, 1, source_price=101),
            event("c", 3000, ENTRY_OUT, ACTION_SELL, 1, source_price=99, source_profit=-2),
        ))
        report = evaluate_delay_portfolio(
            (profitable_partial, losing), quotes, (0,), hold_p25_ms=9000,
            actual_entry_p95_ms=0, actual_exit_p95_ms=0,
        )
        self.assertTrue(report.reconciled)
        self.assertEqual(report.baseline.completed_trades, 2)
        self.assertEqual(report.baseline.net_profit, 6.0)
        self.assertEqual(report.baseline.gross_profit, 8.0)
        self.assertEqual(report.baseline.gross_loss, 2.0)
        self.assertEqual(report.baseline.profit_factor, 4.0)
        self.assertEqual(report.baseline.win_rate, 0.5)
        self.assertEqual(report.baseline.average_net_profit, 3.0)

    def test_portfolio_uses_source_events_for_execution_and_separate_p95_gates(self) -> None:
        quotes = (QuoteTick(0, 100, 101), QuoteTick(1000, 105, 106))
        trade = position("p1", (
            event("o", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101),
            event("c", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=105, source_profit=4),
        ))
        report = evaluate_delay_portfolio(
            (trade,), quotes, (500,), hold_p25_ms=6000,
            actual_entry_p95_ms=500, actual_exit_p95_ms=0, max_quote_wait_ms=10,
        )
        self.assertEqual(report.actual_entry.entry_signals, 1)
        self.assertEqual(report.actual_entry.exit_signals, 1)
        self.assertEqual(report.actual_entry.completed_source_events, 1)
        self.assertEqual(report.actual_entry.executed_source_events, 0)
        self.assertEqual(report.actual_entry.entry_executable_ratio, 0.0)
        self.assertEqual(report.actual_exit.net_profit, 4.0)
        self.assertIn("entry_delay_net_not_positive", report.hard_gate_reasons)
        self.assertIn("entry_executable_below_80pct", report.hard_gate_reasons)
        self.assertNotIn("exit_delay_net_not_positive", report.hard_gate_reasons)

    def test_portfolio_requires_one_customer_product_sleeve(self) -> None:
        one = position("p1", (event("o", 0, ENTRY_IN, ACTION_BUY, 1, source_price=101), event("c", 1000, ENTRY_OUT, ACTION_SELL, 1, source_price=104, source_profit=3)))
        other_product = PositionLifecycle("route:1", "EURUSD", "p2", 1.0, 1.0, one.events)
        with self.assertRaisesRegex(ValueError, "one account_key and product"):
            evaluate_delay_portfolio((one, other_product), (QuoteTick(0, 100, 101), QuoteTick(1000, 104, 105)), (0,), actual_p95_delay_ms=0)


if __name__ == "__main__":
    unittest.main()
