from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from copy_independent_execution import (
    ClientCopyRisk,
    DemoChildTicket,
    IndependentCopyBook,
    copy_comment,
    loss_budget_multiplier,
    quantize_lots,
    slow_weight_increase,
)
from copy_trading_live_demo import RISK_PROFILES, trading_day_key, utc_now
from copy_trading_multi_demo import (
    OPEN_REQUEST_LIMIT,
    MultiSourceLiveService,
    event_reason_code,
    parse_args,
)
from copy_pool_multisource import TOTAL_CLIENT_BUDGET, sleeve_key
from copy_dynamic_pool_domain import PoolTier, SchedulerState, SleeveDynamicState, mark_scheduler_run


NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)


class EventReasonCodeTests(unittest.TestCase):
    def test_monitor_event_preserves_exact_bounded_rejection(self) -> None:
        position = SimpleNamespace(
            status="monitor", reject_reason="below_minimum_risk_lot"
        )
        self.assertEqual(
            event_reason_code("open", position, signal_expired=False),
            "below_minimum_risk_lot",
        )

    def test_unknown_internal_reason_is_not_published(self) -> None:
        position = SimpleNamespace(status="monitor", reject_reason="secret free text")
        self.assertEqual(
            event_reason_code("open", position, signal_expired=False),
            "event_detail_unavailable",
        )

    def test_expired_and_successful_events_have_stable_codes(self) -> None:
        self.assertEqual(
            event_reason_code("open", None, signal_expired=True),
            "signal_expired_no_copy",
        )
        active = SimpleNamespace(status="active", reject_reason="")
        self.assertEqual(
            event_reason_code("open", active, signal_expired=False),
            "risk_allowed",
        )

    def test_structural_monitor_reason_wins_over_latency_annotation(self) -> None:
        for reason in ("old_or_shadow_position", "zero_effective_weight"):
            with self.subTest(reason=reason):
                position = SimpleNamespace(status="monitor", reject_reason=reason)
                self.assertEqual(
                    event_reason_code("open", position, signal_expired=True),
                    reason,
                )

    def test_delayed_exit_is_not_reported_as_an_unfollowed_entry(self) -> None:
        reduced = SimpleNamespace(status="active", reject_reason="")
        closed = SimpleNamespace(status="closed", reject_reason="")

        self.assertEqual(
            event_reason_code("reduce", reduced, signal_expired=True),
            "risk_allowed",
        )
        self.assertEqual(
            event_reason_code("close", closed, signal_expired=True),
            "source_closed",
        )


class IndependentCopyBookTests(unittest.TestCase):
    def test_mt4_partial_close_rekeys_owned_position_without_losing_ticket(self) -> None:
        book = IndependentCopyBook()
        _action, position = book.observe_source_position(
            "route:1", "C001", "XAGUSD", 100, 0.0, 0.05, NOW
        )
        assert position is not None
        original_comment = position.comment
        position.copy_eligible = True
        position.children.append(
            DemoChildTicket(7001, 0.01, 1, NOW.isoformat(), 30.0)
        )

        migrated = book.migrate_source_position(
            "route:1", "C001", "XAGUSD", 100, 200
        )

        self.assertIs(migrated, position)
        self.assertNotIn("route:1|100|XAGUSD", book.positions)
        self.assertIs(book.positions["route:1|200|XAGUSD"], position)
        self.assertEqual(position.source_position_id, 200)
        self.assertEqual(position.source_key, "route:1|200|XAGUSD")
        self.assertEqual(position.comment, original_comment)
        self.assertEqual([child.ticket for child in position.children], [7001])

    def test_mt4_partial_close_rekeys_legacy_monitor_position(self) -> None:
        book = IndependentCopyBook()
        book.mark_bootstrap_positions([{
            "account_key": "route:1",
            "position_id": 100,
            "product": "XAGUSD",
            "lots": 0.05,
        }])

        migrated = book.migrate_source_position(
            "route:1", "C001", "XAGUSD", 100, 200
        )

        self.assertIsNone(migrated)
        self.assertNotIn("route:1|100|XAGUSD", book.legacy_source_positions)
        self.assertIn("route:1|200|XAGUSD", book.legacy_source_positions)

    def test_bootstrap_position_is_monitor_only_until_it_closes(self) -> None:
        book = IndependentCopyBook()
        row = {
            "account_key": "route:1",
            "position_id": 10,
            "product": "XAUUSD",
            "lots": 1.0,
        }
        book.mark_bootstrap_positions([row])

        action, position = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 10, 1.0, 1.5, NOW
        )
        self.assertEqual(action, "legacy_monitor_only")
        self.assertIsNone(position)

        action, _position = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 10, 1.5, 0.0, NOW
        )
        self.assertEqual(action, "legacy_monitor_only")
        self.assertFalse(book.legacy_source_positions)

    def test_restart_never_approves_missed_source_risk_increase(self) -> None:
        book = IndependentCopyBook()
        _action, increased = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 0.0, 1.0, NOW
        )
        _action, reduced = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 12, 0.0, 1.0, NOW
        )
        _action, reversed_position = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 13, 0.0, 1.0, NOW
        )
        _action, closed = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 14, 0.0, 1.0, NOW
        )
        assert increased and reduced and reversed_position and closed

        book.mark_bootstrap_positions([
            {"account_key": "route:1", "position_id": 11, "product": "XAUUSD", "lots": 1.5},
            {"account_key": "route:1", "position_id": 12, "product": "XAUUSD", "lots": 0.4},
            {"account_key": "route:1", "position_id": 13, "product": "XAUUSD", "lots": -0.7},
        ])

        self.assertEqual(increased.source_lots, 1.0)
        self.assertEqual(reduced.source_lots, 0.4)
        self.assertEqual(reversed_position.source_lots, 0.0)
        self.assertEqual(closed.source_lots, 0.0)

    def test_open_increase_reduce_reverse_and_close_are_position_scoped(self) -> None:
        book = IndependentCopyBook()
        action, first = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 0.0, 1.0, NOW
        )
        self.assertEqual(action, "open")
        self.assertIsNotNone(first)
        assert first is not None
        first.copy_eligible = True
        first.children.append(DemoChildTicket(101, 0.01, 1, NOW.isoformat(), 4000.0))

        action, _ = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 1.0, 1.5, NOW
        )
        self.assertEqual(action, "increase")
        action, _ = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 1.5, 0.5, NOW
        )
        self.assertEqual(action, "reduce")
        action, _ = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 0.5, -0.5, NOW
        )
        self.assertEqual(action, "reverse")

        _action, second = book.observe_source_position(
            "route:2", "C002", "XAUUSD", 22, 0.0, -1.0, NOW
        )
        assert second is not None
        second.children.append(DemoChildTicket(202, 0.01, -1, NOW.isoformat(), 4000.0))
        self.assertEqual(book.ticket_owners()[101], first.source_key)
        self.assertEqual(book.ticket_owners()[202], second.source_key)

        action, closed = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, -0.5, 0.0, NOW
        )
        self.assertEqual(action, "close")
        self.assertEqual(closed.children[0].ticket, 101)
        self.assertEqual(second.children[0].ticket, 202)

    def test_only_risk_increasing_events_refresh_the_entry_deadline(self) -> None:
        book = IndependentCopyBook()
        action, position = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 31, 0.0, 1.0, NOW
        )
        assert position is not None
        self.assertEqual(action, "open")
        self.assertEqual(position.risk_signal_at, NOW.isoformat())

        increased_at = NOW + timedelta(seconds=1)
        book.observe_source_position(
            "route:1", "C001", "XAUUSD", 31, 1.0, 2.0, increased_at
        )
        self.assertEqual(position.risk_signal_at, increased_at.isoformat())

        reduced_at = NOW + timedelta(seconds=2)
        book.observe_source_position(
            "route:1", "C001", "XAUUSD", 31, 2.0, 0.5, reduced_at
        )
        self.assertEqual(position.risk_signal_at, increased_at.isoformat())

        reversed_at = NOW + timedelta(seconds=3)
        book.observe_source_position(
            "route:1", "C001", "XAUUSD", 31, 0.5, -0.5, reversed_at
        )
        self.assertEqual(position.risk_signal_at, reversed_at.isoformat())

    def test_loss_curve_quantization_and_slow_recovery(self) -> None:
        self.assertEqual(loss_budget_multiplier(0.20), 1.0)
        self.assertAlmostEqual(loss_budget_multiplier(0.50), 0.70)
        self.assertAlmostEqual(loss_budget_multiplier(0.80), 0.25)
        self.assertEqual(loss_budget_multiplier(1.0), 0.0)
        self.assertEqual(quantize_lots(0.009, 0.01, 0.01), 0.0)
        self.assertEqual(quantize_lots(0.029, 0.01, 0.01), 0.02)
        self.assertAlmostEqual(slow_weight_increase(0.0, 1.0, 15.0), 0.025)
        self.assertAlmostEqual(slow_weight_increase(0.0, 1.0, 60.0), 0.10)

    def test_private_round_trip_preserves_ticket_ownership_and_client_pause(self) -> None:
        book = IndependentCopyBook()
        _action, position = book.observe_source_position(
            "route:1", "C001", "NAS100Roll", 33, 0.0, 2.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        position.source_open_price = 21010.0
        position.source_current_price = 21025.0
        position.source_floating_pnl_usd = 4.5
        position.demo_realized_pnl_usd = 1.0
        position.demo_floating_pnl_usd = 2.0
        position.demo_total_pnl_usd = 3.0
        position.children.append(DemoChildTicket(303, 0.02, 1, NOW.isoformat(), 21000.0))
        book.clients["route:1"] = ClientCopyRisk(
            account_key="route:1",
            client_alias="C001",
            base_weight=0.2,
            effective_weight=0.1,
            loss_budget_usd=30.0,
            realized_pnl_usd=-10.0,
            pause_until="2026-07-29T10:00:00+00:00",
            recovery_shadow_until="2026-07-29T10:15:00+00:00",
        )

        restored = IndependentCopyBook.from_private(book.to_private())
        self.assertEqual(restored.ticket_owners(), {303: position.source_key})
        restored_position = restored.positions[position.source_key]
        self.assertTrue(restored_position.copy_eligible)
        self.assertEqual(restored_position.risk_signal_at, NOW.isoformat())
        self.assertEqual(restored_position.source_open_price, 21010.0)
        self.assertEqual(restored_position.source_floating_pnl_usd, 4.5)
        self.assertEqual(restored_position.demo_total_pnl_usd, 3.0)
        self.assertAlmostEqual(restored.clients["route:1"].loss_usage, 1 / 3)
        self.assertTrue(restored.clients["route:1"].is_paused(NOW))

    def test_copy_comment_fits_broker_limit_and_migrates_legacy_value(self) -> None:
        expected = copy_comment("C006", "ac_cn_mt5:9003434", 743880404, "XAUUSD")
        self.assertEqual(expected, "CPV2:C006:CE2C63")
        self.assertEqual(len(expected), 16)
        book = IndependentCopyBook()
        _action, position = book.observe_source_position(
            "ac_cn_mt5:9003434", "C006", "XAUUSD", 743880404, 0.0, 0.01, NOW
        )
        assert position is not None
        payload = book.to_private()
        payload["positions"][position.source_key]["comment"] = expected + "0A"

        restored = IndependentCopyBook.from_private(payload)

        self.assertEqual(restored.positions[position.source_key].comment, expected)

    def test_closed_mapping_is_retained_for_cycle_pnl_and_pruned_next_day(self) -> None:
        book = IndependentCopyBook()
        _action, position = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 44, 0.0, 1.0, NOW
        )
        assert position is not None
        book.observe_source_position(
            "route:1", "C001", "XAUUSD", 44, 1.0, 0.0, NOW
        )
        book.remove_closed(position.source_key)

        self.assertIn(position, book.positions_for_client("route:1"))
        self.assertEqual(position.status, "closed")
        restored = IndependentCopyBook.from_private(book.to_private())
        self.assertIn(position.source_key, restored.positions)

        restored.prune_closed()
        self.assertNotIn(position.source_key, restored.positions)


class FakeHedgingMt:
    def __init__(self) -> None:
        self.positions: dict[int, SimpleNamespace] = {}
        self.next_ticket = 1000
        self.actions: list[tuple[str, int, float]] = []
        self.margin = 0.0
        self.pnl_rows: dict[str, dict[str, float]] = {}

    def add(self, ticket: int, comment: str, side: int, lots: float) -> None:
        self.positions[ticket] = SimpleNamespace(
            ticket=ticket,
            comment=comment,
            type=0 if side > 0 else 1,
            volume=lots,
            symbol="XAUUSD",
            time=NOW.timestamp(),
            price_open=4000.0,
        )

    def all_strategy_positions(self):
        return tuple(self.positions.values())

    def strategy_positions_by_comment(self, comment: str, symbol: str):
        return tuple(
            row for row in self.positions.values()
            if row.comment == comment and row.symbol == symbol
        )

    def position_by_ticket(self, ticket: int):
        return self.positions.get(ticket)

    def close_position(self, row, volume: float):
        self.actions.append(("close", int(row.ticket), float(volume)))
        if volume >= row.volume - 1e-9:
            self.positions.pop(int(row.ticket))
        else:
            row.volume -= volume
        return SimpleNamespace(retcode=10009, comment="done")

    def open_position(self, signed_lots: float, symbol: str, **kwargs):
        self.next_ticket += 1
        ticket = self.next_ticket
        self.add(ticket, kwargs["comment"], 1 if signed_lots > 0 else -1, abs(signed_lots))
        self.actions.append(("open", ticket, float(signed_lots)))
        return SimpleNamespace(retcode=10009, comment="done")

    def wait_for_comment_position(self, comment: str, symbol: str, expected: float):
        actual = sum(
            row.volume * (1 if row.type == 0 else -1)
            for row in self.strategy_positions_by_comment(comment, symbol)
        )
        if abs(actual - expected) > 1e-9:
            raise RuntimeError(f"expected {expected}, got {actual}")
        return self.strategy_positions_by_comment(comment, symbol)

    def close_all_symbols(self):
        results = []
        for row in list(self.positions.values()):
            results.append(self.close_position(row, row.volume))
        return results

    def wait_for_no_strategy_positions(self):
        if self.positions:
            raise RuntimeError("strategy tickets remain")

    def signed_positions(self):
        totals: dict[str, float] = {}
        for row in self.positions.values():
            totals[row.symbol] = totals.get(row.symbol, 0.0) + (
                row.volume if row.type == 0 else -row.volume
            )
        return {key: value for key, value in totals.items() if abs(value) > 1e-12}

    def account(self):
        return SimpleNamespace(
            equity=10_000.0,
            balance=10_000.0,
            margin=self.margin,
            server="ACCMGlobal-Demo",
        )

    @staticmethod
    def symbol(_product: str):
        return SimpleNamespace(volume_min=0.01, volume_step=0.01, volume_max=100.0)

    @staticmethod
    def stress_loss_per_lot(_product: str, _move: float):
        return 1_000.0

    @staticmethod
    def margin_per_lot(_side: float, _product: str):
        return 1_000.0

    @staticmethod
    def quote_state(_product: str):
        return 4000.0, 4000.5, 0.1

    def pnl_by_comment(self, _start):
        return self.pnl_rows


class IndependentExecutionServiceTests(unittest.TestCase):
    def test_spread_rejection_evidence_captures_account_currency_cost_and_quote(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.mt = SimpleNamespace(
            quote_state=lambda _product: (4000.0, 4000.8, 0.1),
            spread_cost_usd_per_lot=lambda _product, _bid, _ask: 100.0,
        )

        evidence = service._event_spread_evidence(
            "XAUUSD", "execution_gate_blocked:spread"
        )

        self.assertEqual(evidence["spread_cost_per_lot"], 100.0)
        self.assertEqual(evidence["spread_limit_per_lot"], 90.0)
        self.assertEqual(evidence["bid"], 4000.0)
        self.assertEqual(evidence["ask"], 4000.8)

    def test_live_operational_gate_stays_ready_during_one_normal_snapshot_drift(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.operational_ready_once = False
        service.reconcile_streak = 3
        service.pending_source_snapshot_count = 0
        service.portfolio = SimpleNamespace(duplicate_events=0)
        service.coverage = {
            "logical_routes_scanned": 11,
            "physical_sources_scanned": 9,
        }
        service.db = SimpleNamespace(
            sources={str(index): object() for index in range(9)},
            selected_source_staleness=lambda: 0.1,
        )
        service.poll_latencies = [0.1] * 20

        self.assertTrue(service.operational_gates_ready())
        self.assertTrue(service.operational_ready_once)

        service.reconcile_streak = 0
        service.pending_source_snapshot_count = 1
        service.poll_latencies.extend([4.0] * 120)

        self.assertTrue(service.operational_gates_ready())

    def test_missing_delay_evidence_uses_five_second_runtime_budget(self) -> None:
        self.assertEqual(MultiSourceLiveService._signal_delay_budget({}), 5.0)

    def test_non_usd_quote_spread_uses_account_currency_conversion(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.mt = SimpleNamespace(
            quote_state=lambda _product: (150.000, 150.036, 0.1),
            symbol=lambda _product: SimpleNamespace(trade_contract_size=100_000.0),
            spread_cost_usd_per_lot=lambda _product, _bid, _ask: 24.0,
        )
        service.db = SimpleNamespace(selected_source_staleness=lambda: 0.1)
        service.operational_gates_ready = lambda _account_key=None: True

        self.assertTrue(service.quote_allows_open("USDJPY"))

    def test_external_position_does_not_block_model_on_the_same_product(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.mt = SimpleNamespace(
            all_foreign_positions=lambda products: (
                (SimpleNamespace(symbol="XAUUSD"),)
                if "XAUUSD" in products else ()
            ),
            all_pending_orders=lambda _products: (),
        )

        self.assertEqual(service._product_conflict_reason("XAUUSD"), "")
        self.assertEqual(service._product_conflict_reason("USDJPY"), "")

    def test_external_position_is_observed_but_does_not_create_a_global_gate(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.current_targets = {"XAUUSD": 0.01}
        service.last_error = ""
        service.external_position_conflict = False
        service.external_position_count = 0
        service.pending_order_conflict = False
        service.mt = SimpleNamespace(
            all_foreign_positions=lambda _products: (
                SimpleNamespace(symbol="XAUUSD"),
                SimpleNamespace(symbol="XAUUSD"),
            ),
            all_pending_orders=lambda _products: (),
        )

        self.assertFalse(service.refresh_mt5_conflicts())
        self.assertFalse(service.external_position_conflict)
        self.assertEqual(service.external_position_count, 2)
        self.assertEqual(service.last_error, "")

    def test_pending_order_conflict_is_reported_separately(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.mt = SimpleNamespace(
            all_foreign_positions=lambda _products: (),
            all_pending_orders=lambda products: (
                (SimpleNamespace(symbol="USDJPY"),)
                if "USDJPY" in products else ()
            ),
        )

        self.assertEqual(
            service._product_conflict_reason("USDJPY"),
            "execution_gate_blocked:pending_order_conflict",
        )

    def test_deferred_historical_delay_uses_five_second_runtime_cap(self) -> None:
        deferred = {
            "historical_delay_enabled": False,
            "conservative_break_even_ms": 0,
            "hold_p25_seconds": 3_600,
        }
        short_hold = dict(deferred, hold_p25_seconds=9)
        enabled = {
            "historical_delay_enabled": True,
            "conservative_break_even_ms": 2_500,
            "hold_p25_seconds": 3_600,
        }

        self.assertEqual(MultiSourceLiveService._signal_delay_budget(deferred), 5.0)
        self.assertEqual(MultiSourceLiveService._signal_delay_budget(short_hold), 3.0)
        self.assertEqual(MultiSourceLiveService._signal_delay_budget(enabled), 2.5)

    def test_rank_refresh_uses_each_sleeves_own_target_weight(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.scheduler_state = mark_scheduler_run(
            SchedulerState(), NOW, risk=True, discovery=True
        )
        service.sleeve_rows = {
            "route:1|XAUUSD": {
                "account_key": "route:1", "product": "XAUUSD",
                "factor_ready": True, "hourly_score": 0.9,
                "daily_activity_eligible": True, "live_base_weight": 0.04,
            },
            "route:2|EURUSD": {
                "account_key": "route:2", "product": "EURUSD",
                "factor_ready": True, "hourly_score": 0.8,
                "daily_activity_eligible": True, "live_base_weight": 0.12,
            },
        }
        service.sleeve_states = {
            key: SleeveDynamicState(
                day_start_base_weight=0.20,
                effective_weight=0.08,
                tier=PoolTier.ACTIVE,
            )
            for key in service.sleeve_rows
        }
        service.routed_clients = {
            "route:1": SimpleNamespace(spec=SimpleNamespace(equity_usd=10_000.0)),
            "route:2": SimpleNamespace(spec=SimpleNamespace(equity_usd=10_000.0)),
        }
        service.portfolio = SimpleNamespace(
            product_comprehensive_pnl_usd={key: 1.0 for key in service.sleeve_rows},
            intraday_product_net_usd={},
            floating_product_pnl_usd={},
        )
        service._minimum_lot_feasible = lambda _account, _product: True

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service.refresh_dynamic_sleeves()

        self.assertAlmostEqual(
            service.sleeve_states["route:1|XAUUSD"].effective_weight, 0.04
        )
        self.assertAlmostEqual(
            service.sleeve_states["route:2|EURUSD"].effective_weight, 0.09
        )

    def test_first_rank_scales_all_active_weights_without_fast_activation_switch(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.args = SimpleNamespace(demo_fast_activation=False, mode="StagedLive")
        service.mt = FakeHedgingMt()
        service.scheduler_state = mark_scheduler_run(
            SchedulerState(), NOW, risk=True, discovery=True,
            daily_rebuild_run=True,
        )
        first_key = "route:1|XAUUSD"
        second_key = "route:2|EURUSD"
        service.sleeve_rows = {
            first_key: {
                "account_key": "route:1",
                "product": "XAUUSD",
                "factor_ready": True,
                "hourly_score": 0.9,
                "daily_activity_eligible": True,
                "live_base_weight": 0.20,
            },
            second_key: {
                "account_key": "route:2",
                "product": "EURUSD",
                "factor_ready": True,
                "hourly_score": 0.8,
                "daily_activity_eligible": True,
                "live_base_weight": 0.20,
            },
        }
        service.sleeve_states = {
            first_key: SleeveDynamicState(day_start_base_weight=0.20),
            second_key: SleeveDynamicState(day_start_base_weight=0.20),
        }
        service.routed_clients = {
            "route:1": SimpleNamespace(spec=SimpleNamespace(equity_usd=10_000.0)),
            "route:2": SimpleNamespace(spec=SimpleNamespace(equity_usd=10_000.0)),
        }
        service.portfolio = SimpleNamespace(
            product_comprehensive_pnl_usd={first_key: 1.0, second_key: 1.0},
            intraday_product_net_usd={},
            floating_product_pnl_usd={},
        )
        service._minimum_lot_feasible = lambda _account, _product: True

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service.refresh_dynamic_sleeves()

        for key in (first_key, second_key):
            active = service.sleeve_states[key]
            self.assertEqual(active.tier, PoolTier.ACTIVE)
            self.assertEqual(active.consecutive_active_qualifications, 1)
            self.assertAlmostEqual(active.effective_weight, 0.125)
            self.assertIsNone(active.shadow_started_at)
            self.assertIsNone(active.shadow_ends_at)
        self.assertAlmostEqual(
            sum(state.effective_weight for state in service.sleeve_states.values()),
            TOTAL_CLIENT_BUDGET,
        )

    def test_first_pending_reconcile_frame_restarts_entry_shadow_without_losing_rank(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.args = SimpleNamespace(
            demo_fast_activation=True,
            mode="StagedLive",
        )
        service.mt = FakeHedgingMt()
        service.scheduler_state = mark_scheduler_run(
            SchedulerState(), NOW, risk=True, rank=True, discovery=True,
            daily_rebuild_run=True,
        )
        key = "route:1|XAUUSD"
        service.sleeve_rows = {
            key: {
                "factor_ready": True,
                "daily_activity_eligible": True,
                "live_base_weight": 0.04,
            },
        }
        service.sleeve_states = {
            key: SleeveDynamicState(
                day_start_base_weight=0.04,
                tier=PoolTier.ENTRY_SHADOW,
                consecutive_active_qualifications=2,
                shadow_started_at=NOW - timedelta(minutes=10),
                shadow_ends_at=NOW,
                last_ranked_at=NOW,
            ),
        }
        service.reconcile_streak = 3
        service.pending_source_snapshot_count = 1
        service.portfolio = SimpleNamespace(
            duplicate_events=0,
            product_comprehensive_pnl_usd={key: 1.0},
        )
        service.coverage = {
            "logical_routes_scanned": 11,
            "physical_sources_scanned": 9,
        }
        service.db = SimpleNamespace(
            sources={index: object() for index in range(9)},
            selected_source_staleness=lambda: 0.0,
        )
        service.poll_latencies = [0.1] * 120

        pending_at = NOW + timedelta(seconds=10)
        with patch("copy_trading_multi_demo.utc_now", return_value=pending_at):
            service.refresh_dynamic_sleeves()

        pending = service.sleeve_states[key]
        self.assertEqual(pending.tier, PoolTier.ENTRY_SHADOW)
        self.assertEqual(pending.consecutive_active_qualifications, 2)
        self.assertEqual(pending.shadow_started_at, pending_at)
        self.assertEqual(
            pending.shadow_ends_at, pending_at + timedelta(milliseconds=1)
        )
        self.assertEqual(pending.effective_weight, 0)

        service.pending_source_snapshot_count = 0
        with patch(
            "copy_trading_multi_demo.utc_now",
            return_value=pending_at + timedelta(minutes=1),
        ):
            service.refresh_dynamic_sleeves()
        self.assertEqual(service.sleeve_states[key].tier, PoolTier.ACTIVE)

    def test_entry_shadow_losing_current_comprehensive_profit_returns_to_monitor(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.args = SimpleNamespace(demo_fast_activation=True, mode="StagedLive")
        service.mt = FakeHedgingMt()
        service.scheduler_state = mark_scheduler_run(
            SchedulerState(), NOW, rank=True, discovery=True,
            daily_rebuild_run=True,
        )
        key = "route:1|XAUUSD"
        service.sleeve_rows = {
            key: {
                "factor_ready": True,
                "daily_activity_eligible": True,
                "live_base_weight": 0.04,
            },
        }
        service.sleeve_states = {
            key: SleeveDynamicState(
                day_start_base_weight=0.04,
                tier=PoolTier.ENTRY_SHADOW,
                consecutive_active_qualifications=1,
                shadow_started_at=NOW - timedelta(minutes=1),
                shadow_ends_at=NOW + timedelta(minutes=1),
                last_ranked_at=NOW,
            ),
        }
        service.reconcile_streak = 3
        service.pending_source_snapshot_count = 0
        service.portfolio = SimpleNamespace(
            duplicate_events=0,
            product_comprehensive_pnl_usd={key: -0.01},
        )
        service.coverage = {
            "logical_routes_scanned": 11,
            "physical_sources_scanned": 9,
        }
        service.db = SimpleNamespace(
            sources={index: object() for index in range(9)},
            selected_source_staleness=lambda: 0.0,
        )
        service.poll_latencies = [0.1] * 120

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service.refresh_dynamic_sleeves()

        state = service.sleeve_states[key]
        self.assertEqual(state.tier, PoolTier.MONITOR)
        self.assertEqual(state.consecutive_active_qualifications, 0)
        self.assertEqual(state.effective_weight, 0.0)

    def test_demo_fast_activation_is_explicit_and_demo_staged_only(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.mt = FakeHedgingMt()
        service.args = SimpleNamespace(demo_fast_activation=True, mode="StagedLive")
        self.assertTrue(service._demo_fast_activation_enabled())
        self.assertFalse(
            service._demo_fast_activation_enabled(
                SimpleNamespace(server="Another-Demo")
            )
        )
        service.args.mode = "Live"
        self.assertFalse(service._demo_fast_activation_enabled())
        service.args.mode = "StagedLive"
        service.args.demo_fast_activation = False
        self.assertFalse(service._demo_fast_activation_enabled())

        with patch(
            "sys.argv",
            [
                "copy_trading_multi_demo.py",
                "--output-dir", "out",
                "--terminal", "terminal64.exe",
                "--demo-fast-activation",
            ],
        ):
            self.assertTrue(parse_args().demo_fast_activation)

    def test_service_consumes_hourly_discovery_schedule_once(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.scheduler_state = mark_scheduler_run(
            SchedulerState(), NOW, risk=True, rank=True
        )
        service.last_discovery_attempt = 0.0
        called: list[str] = []

        def discover() -> None:
            called.append("discovery")
            service.scheduler_state = mark_scheduler_run(
                service.scheduler_state, NOW, discovery=True
            )

        service.run_hourly_discovery = discover
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch(
            "copy_trading_multi_demo.time.monotonic", return_value=120.0
        ):
            service.refresh_dynamic_sleeves()
            service.refresh_dynamic_sleeves()

        self.assertEqual(called, ["discovery"])
        self.assertEqual(service.scheduler_state.last_discovery_at, NOW)

    @staticmethod
    def service(mt: FakeHedgingMt) -> MultiSourceLiveService:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.mt = mt
        service.copy_book = IndependentCopyBook()
        service._log_independent_order = lambda *_args, **_kwargs: None
        service.refresh_mt5_conflicts = lambda: False
        service.quote_allows_open = lambda _product, _account_key=None: True
        service.order_counter = 0
        service.log = lambda *_args, **_kwargs: None
        service.last_client_risk_refresh = 0.0
        service.sleeve_states = {}
        return service

    @staticmethod
    def sizing_service(mt: FakeHedgingMt) -> MultiSourceLiveService:
        service = IndependentExecutionServiceTests.service(mt)
        product = SimpleNamespace(
            activity_eligible=True,
            base_weight=0.20,
            source_contract_size=100.0,
            demo_contract_size=100.0,
        )
        routed = SimpleNamespace(
            spec=SimpleNamespace(alias="C001", equity_usd=10_000.0),
            products={"XAUUSD": product},
        )
        service.routed_clients = {"route:1": routed}
        service.copy_book.clients["route:1"] = ClientCopyRisk(
            account_key="route:1",
            client_alias="C001",
            base_weight=0.20,
            effective_weight=0.20,
            loss_budget_usd=30.0,
        )
        service.portfolio = SimpleNamespace(
            effective_product_weights={sleeve_key("route:1", "XAUUSD"): 0.20}
        )
        service.sleeve_states[sleeve_key("route:1", "XAUUSD")] = SleeveDynamicState(
            day_start_base_weight=0.20,
            effective_weight=0.20,
            tier=PoolTier.ACTIVE,
        )
        return service

    def test_expired_increase_is_not_chased_and_reduction_still_applies(self) -> None:
        service = self.service(FakeHedgingMt())
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 0.0, 1.0, NOW
        )
        assert position is not None
        self.assertEqual(
            service._approved_source_after(
                "route:1", 11, "XAUUSD", 1.0, 2.0, entry_timely=False
            ),
            1.0,
        )
        self.assertEqual(
            service._approved_source_after(
                "route:1", 11, "XAUUSD", 2.0, 0.5, entry_timely=True
            ),
            0.5,
        )
        position.source_lots = 0.5
        self.assertEqual(
            service._approved_source_after(
                "route:1", 11, "XAUUSD", 0.5, -0.5, entry_timely=False
            ),
            0.0,
        )

    def test_position_reconciliation_never_approves_missing_new_risk(self) -> None:
        class FakePortfolio:
            def __init__(self, positions: dict[tuple[str, int, str], float] | None = None):
                self.positions = dict(positions or {})

            def comparable_positions(self) -> dict[tuple[str, int, str], float]:
                return dict(self.positions)

            def replace_positions(self, rows: list[dict[str, object]]) -> None:
                self.positions = {
                    (
                        str(row["account_key"]),
                        int(row["position_id"]),
                        str(row["symbol"]),
                    ): float(row["lots"])
                    for row in rows
                }

        service = self.sizing_service(FakeHedgingMt())
        initial = {
            ("route:1", 81, "XAUUSD"): 1.0,
            ("route:1", 82, "XAUUSD"): 1.0,
        }
        service.portfolio = FakePortfolio(initial)
        for position_id in (81, 82):
            _action, position = service.copy_book.observe_source_position(
                "route:1", "C001", "XAUUSD", position_id, 0.0, 1.0, NOW
            )
            assert position is not None
            position.copy_eligible = True
        rows: list[dict[str, object]] = [
            {"account_key": "route:1", "position_id": 81, "symbol": "XAUUSD", "lots": 2.0},
            {"account_key": "route:1", "position_id": 82, "symbol": "XAUUSD", "lots": -1.0},
            {"account_key": "route:1", "position_id": 83, "symbol": "XAUUSD", "lots": 1.0},
        ]
        service.db = SimpleNamespace(all_positions=lambda: rows)
        service.reconcile_streak = 0
        service.pending_source_snapshot = None
        service.pending_source_snapshot_count = 0
        service.log = lambda *_args: None
        captured: list[tuple[int, float]] = []
        service._handle_source_position_change = lambda **values: captured.append(
            (int(values["position_id"]), float(values["after_lots"]))
        )

        with patch(
            "copy_trading_multi_demo.MultiSourcePortfolio",
            side_effect=lambda _clients: FakePortfolio(),
        ), patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service.reconcile_sources()
            service.reconcile_sources()
            service.reconcile_sources()

        self.assertEqual(captured, [(81, 1.0), (82, 0.0), (83, 0.0)])

    def test_closing_one_customer_never_touches_another_customer_ticket(self) -> None:
        mt = FakeHedgingMt()
        service = self.service(mt)
        _action, first = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 0.0, 1.0, NOW
        )
        _action, second = service.copy_book.observe_source_position(
            "route:2", "C002", "XAUUSD", 22, 0.0, -1.0, NOW
        )
        assert first is not None and second is not None
        mt.add(101, first.comment, 1, 0.01)
        mt.add(202, second.comment, -1, 0.01)
        service._sync_book_children(first)
        service._sync_book_children(second)

        service._close_position_to(first, 0.0, "source_closed")

        self.assertNotIn(101, mt.positions)
        self.assertIn(202, mt.positions)
        self.assertEqual(mt.actions, [("close", 101, 0.01)])
        self.assertEqual(second.copied_signed_lots, -0.01)

    def test_reversal_closes_owned_ticket_before_opening_new_direction(self) -> None:
        mt = FakeHedgingMt()
        service = self.service(mt)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 11, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        mt.add(101, position.comment, 1, 0.01)
        service._sync_book_children(position)
        position.source_lots = -1.0
        service._desired_copy_lots = lambda *_args, **_kwargs: (-0.01, "risk_allowed")

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service._sync_independent_position(
                position, "source_reverse", allow_increase=True
            )

        self.assertEqual(mt.actions[0], ("close", 101, 0.01))
        self.assertEqual(mt.actions[1][0], "open")
        self.assertEqual(mt.actions[1][2], -0.01)
        self.assertEqual(position.copied_signed_lots, -0.01)

    def test_mapping_validation_rejects_unknown_and_missing_demo_tickets(self) -> None:
        mt = FakeHedgingMt()
        service = self.service(mt)
        mt.add(999, "CPV2:C999:UNKNOWN", 1, 0.01)
        with self.assertRaisesRegex(RuntimeError, r"unknown_demo=\[999\]"):
            service._validate_copy_ticket_mapping()

        mt.positions.clear()
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 55, 0.0, 1.0, NOW
        )
        assert position is not None
        position.children.append(DemoChildTicket(555, 0.01, 1, NOW.isoformat(), 4000.0))
        with self.assertRaisesRegex(RuntimeError, r"missing_demo=\[555\]"):
            service._validate_copy_ticket_mapping()

    def test_mapping_validation_recovers_one_exact_comment_owner(self) -> None:
        mt = FakeHedgingMt()
        service = self.service(mt)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 55, 0.0, 1.0, NOW
        )
        assert position is not None
        mt.add(777, position.comment, 1, 0.01)

        service._validate_copy_ticket_mapping()

        self.assertEqual(service.copy_book.ticket_owners(), {777: position.source_key})

    def test_restart_without_demo_ticket_is_monitor_only_and_never_reopens(self) -> None:
        original = IndependentCopyBook()
        _action, position = original.observe_source_position(
            "route:1", "C001", "XAUUSD", 55, 0.0, 10.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        restored = IndependentCopyBook.from_private(original.to_private())
        service = self.sizing_service(FakeHedgingMt())
        service.copy_book = restored

        service._validate_copy_ticket_mapping()
        marked = service.copy_book.mark_restart_positions_monitor_only(
            set(service.copy_book.positions)
        )
        with patch.object(service, "_position_hold_seconds", return_value=0.0):
            service.reconcile_independent_copies(allow_increase=True)

        restored_position = service.copy_book.positions[position.source_key]
        self.assertEqual(marked, 1)
        self.assertFalse(restored_position.copy_eligible)
        self.assertTrue(restored_position.restart_monitor_only)
        self.assertEqual(restored_position.status, "monitor")
        self.assertEqual(
            restored_position.reject_reason, "restart_without_demo_ticket"
        )
        self.assertEqual(service.mt.actions, [])

    def test_restart_unique_actual_ticket_remains_owned_and_can_close(self) -> None:
        original = IndependentCopyBook()
        _action, position = original.observe_source_position(
            "route:1", "C001", "XAUUSD", 56, 0.0, 10.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        mt = FakeHedgingMt()
        mt.add(778, position.comment, 1, 0.01)
        service = self.sizing_service(mt)
        service.copy_book = IndependentCopyBook.from_private(original.to_private())

        service._validate_copy_ticket_mapping()
        marked = service.copy_book.mark_restart_positions_monitor_only(
            set(service.copy_book.positions)
        )
        recovered = service.copy_book.positions[position.source_key]
        recovered.source_lots = 0.0
        with patch.object(service, "_position_hold_seconds", return_value=0.0):
            service.reconcile_independent_copies(allow_increase=True)

        self.assertEqual(marked, 0)
        self.assertTrue(recovered.copy_eligible)
        self.assertFalse(recovered.restart_monitor_only)
        self.assertEqual(mt.actions, [("close", 778, 0.01)])
        self.assertEqual(recovered.status, "closed")

    def test_restart_monitor_only_mapping_is_removed_when_source_closes(self) -> None:
        book = IndependentCopyBook()
        _action, position = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 57, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        book.mark_restart_positions_monitor_only({position.source_key})

        action, closed = book.observe_source_position(
            "route:1", "C001", "XAUUSD", 57, 1.0, 0.0, NOW
        )
        assert closed is not None
        book.remove_closed(closed.source_key)

        self.assertEqual(action, "close")
        self.assertNotIn(position.source_key, book.positions)

    def test_source_change_persists_before_and_after_execution(self) -> None:
        service = self.service(FakeHedgingMt())
        service.phase = "live"
        service.routed_clients = {
            "route:1": SimpleNamespace(spec=SimpleNamespace(alias="C001"))
        }
        service.sleeve_states = {
            sleeve_key("route:1", "XAUUSD"): SleeveDynamicState(
                day_start_base_weight=0.2,
                effective_weight=0.2,
                tier=PoolTier.ACTIVE,
            )
        }
        calls: list[str] = []
        service.persist_private_state = lambda: calls.append("persist")
        service._sync_independent_position = (
            lambda *_args, **_kwargs: calls.append("execute")
        )

        service._handle_source_position_change(
            account_key="route:1",
            product="XAUUSD",
            position_id=55,
            before_lots=0.0,
            after_lots=1.0,
            signal_time=NOW,
            reason="test",
        )

        self.assertEqual(calls, ["persist", "execute", "persist"])

    def test_exact_offsetting_tickets_are_all_closed_by_flatten(self) -> None:
        mt = FakeHedgingMt()
        service = self.service(mt)
        service.current_targets = {"XAUUSD": 0.0}
        service.current_target = 0.0
        service.log_product_order = lambda *_args, **_kwargs: None
        mt.add(101, "CPV2:C001:BUY", 1, 0.01)
        mt.add(202, "CPV2:C002:SELL", -1, 0.01)
        self.assertEqual(mt.signed_positions(), {})

        service.flatten("outage")

        self.assertEqual(mt.positions, {})
        self.assertEqual(
            mt.actions,
            [("close", 101, 0.01), ("close", 202, 0.01)],
        )

    def test_closed_position_realized_pnl_exhausts_only_its_client_budget(self) -> None:
        mt = FakeHedgingMt()
        service = self.service(mt)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 66, 0.0, 1.0, NOW
        )
        assert position is not None
        service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 66, 1.0, 0.0, NOW
        )
        service.copy_book.remove_closed(position.source_key)
        service.copy_book.clients["route:1"] = ClientCopyRisk(
            account_key="route:1",
            client_alias="C001",
            base_weight=0.10,
            effective_weight=0.10,
            loss_budget_usd=10.0,
        )
        mt.pnl_rows[position.comment] = {"realized": -10.0, "floating": 0.0}

        service._refresh_independent_client_risk(force=True)

        risk = service.copy_book.clients["route:1"]
        self.assertEqual(risk.realized_pnl_usd, -10.0)
        self.assertEqual(risk.effective_weight, 0.0)
        self.assertEqual(risk.status, "paused")
        self.assertIsNotNone(risk.pause_until)
        self.assertEqual(position.demo_realized_pnl_usd, -10.0)
        self.assertEqual(position.demo_floating_pnl_usd, 0.0)
        self.assertEqual(position.demo_total_pnl_usd, -10.0)

    def test_minimum_risk_lot_margin_cluster_and_twelve_hour_caps(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 77, 0.0, 10.0, NOW
        )
        assert position is not None
        position.copy_eligible = True

        service.copy_book.clients["route:1"].loss_budget_usd = 5.0
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
        self.assertEqual((target, reason), (0.0, "below_minimum_risk_lot"))

        service.copy_book.clients["route:1"].loss_budget_usd = 30.0
        mt.margin = 1_500.0
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
        self.assertEqual((target, reason), (0.0, "below_minimum_risk_lot"))

        mt.margin = 0.0
        mt.add(201, "CPV2:C002:CLUSTER", 1, 0.06)
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
        self.assertEqual((target, reason), (0.0, "below_minimum_risk_lot"))
        mt.positions.clear()

        mt.add(301, position.comment, 1, 0.01)
        service._sync_book_children(position)
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=12 * 60 * 60
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
        self.assertEqual((target, reason), (0.01, "risk_allowed"))

    def test_expired_no_child_retry_never_opens(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.sleeve_rows = {
            sleeve_key("route:1", "XAUUSD"): {
                "historical_delay_enabled": False,
                "hold_p25_seconds": 30.0,
            },
        }
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 771, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        position.source_opened_at = (NOW - timedelta(seconds=40)).isoformat()
        position.risk_signal_at = position.source_opened_at

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service._sync_independent_position(
                position, "delayed_retry", allow_increase=True
            )
            service.reconcile_independent_copies(allow_increase=True)

        self.assertEqual(mt.actions, [])
        self.assertEqual(position.copied_signed_lots, 0.0)
        self.assertEqual(position.reject_reason, "signal_expired_no_copy")

    def test_expired_existing_child_cannot_retry_an_addition(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.sleeve_rows = {
            sleeve_key("route:1", "XAUUSD"): {
                "historical_delay_enabled": False,
                "hold_p25_seconds": 30.0,
            },
        }
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 773, 0.0, 2.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        position.risk_signal_at = (NOW - timedelta(seconds=40)).isoformat()
        mt.add(773, position.comment, 1, 0.01)
        service._sync_book_children(position)
        service._desired_copy_lots = lambda *_args, **_kwargs: (0.02, "risk_allowed")

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service._sync_independent_position(
                position, "delayed_add_retry", allow_increase=True
            )

        self.assertEqual(mt.actions, [])
        self.assertEqual(position.copied_signed_lots, 0.01)
        self.assertEqual(position.reject_reason, "signal_expired_no_copy")

    def test_expired_reversal_closes_old_side_without_opening_opposite(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.sleeve_rows = {
            sleeve_key("route:1", "XAUUSD"): {
                "historical_delay_enabled": False,
                "hold_p25_seconds": 30.0,
            },
        }
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 774, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        mt.add(774, position.comment, 1, 0.01)
        service._sync_book_children(position)
        position.source_lots = -1.0
        position.risk_signal_at = (NOW - timedelta(seconds=40)).isoformat()
        service._desired_copy_lots = lambda *_args, **_kwargs: (-0.01, "risk_allowed")

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service._sync_independent_position(
                position, "delayed_reverse_retry", allow_increase=True
            )

        self.assertEqual(mt.actions, [("close", 774, 0.01)])
        self.assertEqual(position.copied_signed_lots, 0.0)
        self.assertEqual(position.reject_reason, "signal_expired_no_copy")

    def test_entry_deadline_is_rechecked_immediately_before_broker_open(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 775, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        service._desired_copy_lots = lambda *_args, **_kwargs: (0.01, "risk_allowed")

        with patch.object(
            service, "_risk_signal_expired", side_effect=[False, True]
        ) as expiry:
            service._sync_independent_position(
                position, "deadline_boundary", allow_increase=True
            )

        self.assertEqual(expiry.call_count, 2)
        self.assertEqual(mt.actions, [])
        self.assertEqual(position.reject_reason, "signal_expired_no_copy")

    def test_expired_signal_with_child_remains_managed(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.sleeve_rows = {
            sleeve_key("route:1", "XAUUSD"): {
                "historical_delay_enabled": False,
                "hold_p25_seconds": 30.0,
            },
        }
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 772, 0.0, 0.01, NOW
        )
        assert position is not None
        position.copy_eligible = True
        position.source_opened_at = (NOW - timedelta(seconds=6)).isoformat()
        mt.add(772, position.comment, 1, 0.01)
        service._sync_book_children(position)

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
            service._sync_independent_position(
                position, "risk_reduction", allow_increase=True
            )

        self.assertEqual((target, reason), (0.0, "below_minimum_risk_lot"))
        self.assertEqual(mt.actions, [("close", 772, 0.01)])

    def test_explicit_demo_override_allows_independent_minimum_lots_within_cluster_budget(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=True,
            mode="StagedLive",
        )
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 78, 0.0, 10.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        service.copy_book.clients["route:1"].loss_budget_usd = 5.0

        self.assertTrue(service._minimum_lot_feasible("route:1", "XAUUSD"))
        service._stress_usage = lambda _excluded: (
            0.01,
            {("XAUUSD", 1): 0.01},
            {},
        )
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
        self.assertEqual((target, reason), (0.01, "risk_allowed_demo_minimum"))

        mt.add(202, "CPV2:C002:SAME-SIDE", 1, 0.01)
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
        self.assertEqual((target, reason), (0.01, "risk_allowed_demo_minimum"))

        # An existing same-direction minimum lot must not prevent another
        # active source from receiving its own minimum lot while the cluster
        # stress budget still has room.
        mt.add(203, "CPV2:C002:SAME-DIRECTION", 0, 0.01)
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)
        self.assertEqual((target, reason), (0.01, "risk_allowed_demo_minimum"))

    def test_demo_override_removes_same_direction_cluster_cap_but_keeps_portfolio_cap(self) -> None:
        mt = FakeHedgingMt()
        mt.stress_loss_per_lot = lambda _product, _move: 6_418.72
        service = self.sizing_service(mt)
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=True,
            mode="StagedLive",
        )
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 781, 0.0, 0.02, NOW
        )
        assert position is not None
        position.copy_eligible = True

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            target, reason = service._desired_copy_lots(position, allow_increase=True)

        self.assertEqual((target, reason), (0.01, "risk_allowed_demo_minimum"))

        mt.add(204, "CPV2:C002:XAU-MIN", 1, 0.01)
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            second_target, second_reason = service._desired_copy_lots(
                position, allow_increase=True
            )

        self.assertEqual(
            (second_target, second_reason), (0.01, "risk_allowed_demo_minimum")
        )

        mt.add(205, "CPV2:C003:XAU-MIN", 1, 0.01)
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            third_target, third_reason = service._desired_copy_lots(
                position, allow_increase=True
            )

        self.assertEqual(
            (third_target, third_reason), (0.0, "below_minimum_risk_lot")
        )

    def test_gate_rejection_keeps_specific_reason_in_position_state(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=True,
            mode="StagedLive",
        )
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 880, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        service.quote_allows_open = lambda _product, _account_key=None: False

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service._sync_independent_position(position, "gate_reason", allow_increase=True)

        self.assertEqual(position.status, "risk_rejected")
        self.assertTrue(position.reject_reason.startswith("execution_gate_blocked:"))

    def test_demo_minimum_override_keeps_independent_owners_without_reconcile_churn(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=True,
            mode="StagedLive",
        )
        service.copy_book.clients["route:1"].loss_budget_usd = 5.0
        _action, first = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 78, 0.0, 10.0, NOW
        )
        _action, second = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 79, 0.0, 10.0, NOW
        )
        assert first is not None and second is not None
        first.copy_eligible = True
        second.copy_eligible = True

        with patch("copy_trading_multi_demo.utc_now", return_value=NOW), patch.object(
            service, "_position_hold_seconds", return_value=0.0
        ):
            service._sync_independent_position(first, "first", allow_increase=True)
            service._sync_independent_position(second, "second", allow_increase=True)
            service.reconcile_independent_copies(allow_increase=True)
            service.reconcile_independent_copies(allow_increase=True)

        self.assertEqual([action[0] for action in mt.actions], ["open", "open"])
        self.assertEqual(first.copied_signed_lots, 0.01)
        self.assertEqual(second.copied_signed_lots, 0.01)

    def test_open_request_rate_limit_rejects_without_flattening_or_hard_stop(self) -> None:
        service = self.service(FakeHedgingMt())
        service.open_request_times = [100.0] * OPEN_REQUEST_LIMIT
        hard_stops: list[tuple[str, str]] = []
        service.execution_hard_stop = lambda reason, error: hard_stops.append(
            (reason, str(error))
        )

        with patch("copy_trading_multi_demo.time.monotonic", return_value=120.0):
            allowed = service._reserve_open_request()

        self.assertFalse(allowed)
        self.assertEqual(len(service.open_request_times), OPEN_REQUEST_LIMIT)
        self.assertEqual(hard_stops, [])

    def test_blocked_increase_keeps_the_exact_operational_reason(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 881, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True

        for reason in (
            "execution_gate_blocked:manual_control",
            "execution_gate_blocked:friday_reduce_only",
            "execution_gate_blocked:terminal_autotrading",
        ):
            with self.subTest(reason=reason), patch(
                "copy_trading_multi_demo.utc_now", return_value=NOW
            ), patch.object(service, "_position_hold_seconds", return_value=0.0):
                target, decision = service._desired_copy_lots(
                    position,
                    allow_increase=False,
                    increase_block_reason=reason,
                )
            self.assertEqual(target, 0.0)
            self.assertEqual(decision, reason)

    def test_rate_limited_position_is_retryable_without_global_hard_stop(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 882, 0.0, 1.0, NOW
        )
        assert position is not None
        position.copy_eligible = True
        service._desired_copy_lots = lambda *_args, **_kwargs: (0.01, "risk_allowed")
        service._reserve_open_request = lambda: False

        with patch.object(service, "_risk_signal_expired", return_value=False):
            service._sync_independent_position(
                position, "rate_limit", allow_increase=True
            )

        self.assertEqual(mt.actions, [])
        self.assertTrue(position.copy_eligible)
        self.assertEqual(position.status, "risk_rejected")
        self.assertEqual(
            position.reject_reason, "execution_gate_blocked:open_rate_limit"
        )

    def test_twenty_four_hour_position_closes_only_timed_out_client(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        _action, first = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 88, 0.0, 1.0, NOW
        )
        assert first is not None
        first.copy_eligible = True
        mt.add(401, first.comment, 1, 0.01)
        service._sync_book_children(first)
        service._validate_copy_ticket_mapping = lambda: None
        with patch.object(service, "_position_hold_seconds", return_value=24 * 60 * 60):
            service.reconcile_independent_copies(allow_increase=True)

        self.assertNotIn(401, mt.positions)
        risk = service.copy_book.clients["route:1"]
        self.assertEqual(risk.status, "paused")
        self.assertEqual(risk.effective_weight, 0.0)
        self.assertIsNotNone(risk.pause_until)

    def test_client_risk_budget_is_capped_at_twenty_percent(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.routed_clients["route:1"].products["XAUUSD"].base_weight = 0.30

        service._initialize_client_copy_risk(10_000.0)

        self.assertEqual(service.copy_book.clients["route:1"].base_weight, 0.30)
        self.assertEqual(service.copy_book.clients["route:1"].loss_budget_usd, 30.0)

    def test_demo_minimum_override_floors_tiny_active_client_budget_to_cap(self) -> None:
        service = self.sizing_service(FakeHedgingMt())
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=True,
            mode="StagedLive",
        )
        service.routed_clients["route:1"].products["XAUUSD"].base_weight = 0.0038258

        service._initialize_client_copy_risk(9_863.87)

        risk = service.copy_book.clients["route:1"]
        self.assertAlmostEqual(risk.loss_budget_usd, 9_863.87 * 0.015 * 0.20)

    def test_tiny_client_budget_remains_weight_proportional_without_override(self) -> None:
        service = self.sizing_service(FakeHedgingMt())
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=False,
            mode="StagedLive",
        )
        service.routed_clients["route:1"].products["XAUUSD"].base_weight = 0.0038258

        service._initialize_client_copy_risk(9_863.87)

        risk = service.copy_book.clients["route:1"]
        self.assertAlmostEqual(risk.loss_budget_usd, 9_863.87 * 0.015 * 0.0038258)

    def test_demo_override_budget_does_not_pause_after_point_69_loss(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=True,
            mode="StagedLive",
        )
        service.routed_clients["route:1"].products["XAUUSD"].base_weight = 0.0038258
        service._initialize_client_copy_risk(9_863.87)
        _action, position = service.copy_book.observe_source_position(
            "route:1", "C001", "XAUUSD", 80, 0.0, 0.01, NOW
        )
        assert position is not None
        mt.pnl_rows[position.comment] = {"realized": -0.69, "floating": 0.0}

        service._refresh_independent_client_risk(force=True)

        risk = service.copy_book.clients["route:1"]
        self.assertLess(risk.loss_usage, 1.0)
        self.assertEqual(risk.status, "active")
        self.assertIsNone(risk.pause_until)

    def test_demo_minimum_budget_floor_requires_demo_staged_mode(self) -> None:
        mt = FakeHedgingMt()
        service = self.sizing_service(mt)
        service.args = SimpleNamespace(
            allow_demo_min_lot_override=True,
            mode="Live",
        )
        service.routed_clients["route:1"].products["XAUUSD"].base_weight = 0.0038258

        service._initialize_client_copy_risk(9_863.87)

        expected = 9_863.87 * 0.015 * 0.0038258
        self.assertAlmostEqual(
            service.copy_book.clients["route:1"].loss_budget_usd, expected
        )

        service.args.mode = "StagedLive"
        mt.account = lambda: SimpleNamespace(
            equity=10_000.0,
            balance=10_000.0,
            margin=mt.margin,
            server="Another-Demo",
        )
        service._initialize_client_copy_risk(9_863.87)
        self.assertAlmostEqual(
            service.copy_book.clients["route:1"].loss_budget_usd, expected
        )

    def test_pause_transitions_to_fifteen_minute_recovery_shadow(self) -> None:
        mt = FakeHedgingMt()
        service = self.service(mt)
        risk = ClientCopyRisk(
            account_key="route:1",
            client_alias="C001",
            base_weight=0.10,
            effective_weight=0.0,
            loss_budget_usd=15.0,
            pause_until=(NOW - timedelta(seconds=1)).isoformat(),
        )
        service.copy_book.clients["route:1"] = risk
        with patch("copy_trading_multi_demo.utc_now", return_value=NOW):
            service._refresh_independent_client_risk(force=True)
        self.assertEqual(risk.status, "recovery_shadow")
        self.assertEqual(risk.effective_weight, 0.0)
        self.assertEqual(
            risk.recovery_shadow_until,
            (NOW + timedelta(minutes=15)).isoformat(),
        )

        after_shadow = NOW + timedelta(minutes=15)
        with patch("copy_trading_multi_demo.utc_now", return_value=after_shadow):
            service._refresh_independent_client_risk(force=True)
        self.assertEqual(risk.status, "reduced")
        self.assertAlmostEqual(risk.effective_weight, 0.0025)

    def test_friday_and_hard_margin_flatten_exact_offsetting_gross_tickets(self) -> None:
        for policy, margin, expected_phase in (
            ("flatten", 0.0, "daily_stop"),
            ("normal", 2_500.0, "margin_hard_stop"),
        ):
            with self.subTest(policy=policy):
                mt = FakeHedgingMt()
                mt.margin = margin
                service = self.service(mt)
                service.current_targets = {"XAUUSD": 0.0}
                service.current_target = 0.0
                service.log_product_order = lambda *_args, **_kwargs: None
                service.last_pool_reload_day = trading_day_key(utc_now())
                service.profile = RISK_PROFILES["Capital10k"]
                service.daily_reference_equity = 10_000.0
                service.cycle_reference_equity = 10_000.0
                service.cycle_baseline_pnl = 0.0
                service.daily_hard_stop = policy == "flatten"
                service.cooldown_until = None
                service.phase = "daily_stop" if policy == "flatten" else "live"
                service.portfolio = None
                mt.marked_pnl = lambda _start: 0.0
                mt.add(501, "CPV2:C001:BUY", 1, 0.01)
                mt.add(502, "CPV2:C002:SELL", -1, 0.01)
                with patch("copy_trading_multi_demo.friday_policy", return_value=policy):
                    service.risk_check()

                self.assertEqual(mt.positions, {})
                self.assertEqual(service.phase, expected_phase)


if __name__ == "__main__":
    unittest.main()
