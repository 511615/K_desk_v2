from __future__ import annotations

import unittest
import time
import json
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone

from copy_trading_live_core import (
    ClientSpec,
    DealCursor,
    DealEvent,
    SourcePortfolio,
    datetime_to_filetime,
    drawdown_throttle,
    filetime_to_datetime,
    friday_policy,
    guarded_execution_target,
    holding_score_multiplier,
    hysteresis_target,
    intraday_multiplier,
    is_abook_status,
    normalize_with_cap,
    position_lot_cap,
    quantize_lots,
    server_time_from_utc,
    update_source_position,
)
from copy_trading_live_demo import (
    RISK_PROFILES,
    LiveService,
    append_csv,
    csv_data_rows,
    ensure_csv_schema,
    recent_csv_latencies,
)


class FakeMt5Executor:
    def __init__(self, current: float, foreign: bool = False) -> None:
        self.current = current
        self.foreign = foreign
        self.moves: list[float] = []

    def signed_position(self) -> float:
        return self.current

    def foreign_positions(self) -> tuple[object, ...]:
        return (object(),) if self.foreign else ()

    @staticmethod
    def pending_orders() -> tuple[object, ...]:
        return ()

    def move_to(self, target: float) -> list[object]:
        self.moves.append(target)
        self.current = target
        return []


class PartialFillMt5Executor(FakeMt5Executor):
    def move_to(self, target: float) -> list[object]:
        self.moves.append(target)
        self.current = 0.005 if target > 0 else -0.005
        raise RuntimeError("position reconciliation timeout after partial fill")

    def close_all(self) -> list[object]:
        self.current = 0.0
        return []

    def wait_for_position(self, expected: float) -> None:
        if self.current != expected:
            raise RuntimeError("unexpected residual position")


class FakeRiskMt5:
    @staticmethod
    def account() -> object:
        return SimpleNamespace(equity=10_000.0)

    @staticmethod
    def symbol() -> object:
        return SimpleNamespace(trade_contract_size=100.0)

    @staticmethod
    def margin_per_lot(_side: float) -> float:
        return 3_000.0


class CoreTests(unittest.TestCase):
    def test_filetime_round_trip(self) -> None:
        value = datetime(2026, 7, 28, 6, 15, 55, 123456, tzinfo=timezone.utc)
        restored = filetime_to_datetime(datetime_to_filetime(value))
        self.assertLess(abs((restored - value).total_seconds()), 0.000001)

    def test_abook_status_contains_a(self) -> None:
        self.assertTrue(is_abook_status("A"))
        self.assertTrue(is_abook_status("TA"))
        self.assertFalse(is_abook_status("B"))

    def test_holding_multiplier(self) -> None:
        self.assertEqual(holding_score_multiplier(3.0), 0.0)
        self.assertAlmostEqual(holding_score_multiplier(16.5), 0.75)
        self.assertEqual(holding_score_multiplier(30.0), 1.0)

    def test_intraday_dynamic_weight(self) -> None:
        self.assertEqual(intraday_multiplier(1.0, 1000.0), 1.0)
        self.assertAlmostEqual(intraday_multiplier(-5.0, 1000.0), 0.75)
        self.assertAlmostEqual(intraday_multiplier(-10.0, 1000.0), 0.5)
        self.assertEqual(intraday_multiplier(-20.0, 1000.0), 0.0)

    def test_cent_intraday_bootstrap_scales_money_only(self) -> None:
        clients = {
            1: ClientSpec(1, "C001", 100.0, 0.1, money_scale=0.01),
        }
        portfolio = SourcePortfolio(clients)
        portfolio.set_intraday_net({1: -100.0})
        self.assertEqual(portfolio.intraday_net_usd[1], -1.0)
        self.assertAlmostEqual(portfolio.effective_weights[1], 0.05)

    def test_weight_normalization_and_cap(self) -> None:
        weights = normalize_with_cap({1: 10.0, 2: 5.0, 3: 2.0, 4: 1.0}, budget=0.1, cap=0.03)
        self.assertAlmostEqual(sum(weights.values()), 0.1)
        self.assertLessEqual(max(weights.values()), 0.03)

    def test_hysteresis(self) -> None:
        self.assertEqual(hysteresis_target(0.009, 0.0), 0.0)
        self.assertEqual(hysteresis_target(0.010, 0.0), 0.01)
        self.assertEqual(hysteresis_target(0.008, 0.01), 0.01)
        self.assertEqual(hysteresis_target(0.004, 0.01), 0.0)
        self.assertEqual(hysteresis_target(-0.011, 0.01), -0.01)

    def test_multistep_hysteresis_quantizes_target(self) -> None:
        self.assertEqual(hysteresis_target(0.034, 0.0, max_lots=0.05), 0.03)
        self.assertEqual(hysteresis_target(0.036, 0.03, max_lots=0.05), 0.04)
        self.assertEqual(hysteresis_target(0.024, 0.03, max_lots=0.05), 0.02)
        self.assertEqual(hysteresis_target(-0.049, 0.03, max_lots=0.05), -0.05)
        self.assertEqual(quantize_lots(-0.025, 0.01), -0.03)

    def test_stress_risk_and_margin_caps(self) -> None:
        common = {
            "reference_equity_usd": 10_000.0,
            "current_equity_usd": 10_000.0,
            "hard_cap_lots": 0.05,
            "stress_move_usd_per_unit": 20.0,
            "contract_size": 100.0,
            "risk_fraction": 0.01,
            "margin_fraction": 0.10,
            "lot_step": 0.01,
        }
        self.assertEqual(position_lot_cap(**common, margin_per_lot_usd=3_000.0), 0.05)
        self.assertEqual(position_lot_cap(**common, margin_per_lot_usd=30_000.0), 0.03)
        self.assertEqual(
            position_lot_cap(
                **{**common, "reference_equity_usd": 8_000.0},
                margin_per_lot_usd=3_000.0,
            ),
            0.04,
        )

    def test_cycle_drawdown_throttle_and_percentage_stops(self) -> None:
        self.assertEqual(drawdown_throttle(10.0, 75.0), 1.0)
        self.assertEqual(drawdown_throttle(-15.0, 75.0), 1.0)
        self.assertAlmostEqual(drawdown_throttle(-37.5, 75.0), 0.625)
        self.assertEqual(drawdown_throttle(-75.0, 75.0), 0.0)
        profile = RISK_PROFILES["Capital10k"]
        self.assertEqual(profile.cycle_loss_limit(10_000.0), 150.0)
        self.assertEqual(profile.daily_loss_limit(10_000.0), 300.0)
        self.assertEqual(profile.equity_floor_usd, 9_500.0)

    def test_capital10k_runtime_cap_de_risks_with_cycle_drawdown(self) -> None:
        service = LiveService.__new__(LiveService)
        service.profile = RISK_PROFILES["Capital10k"]
        service.mt = FakeRiskMt5()
        service.cycle_reference_equity = 10_000.0
        self.assertEqual(service.position_cap(0.0), 0.05)
        self.assertEqual(service.position_cap(-75.0), 0.03)
        self.assertEqual(service.position_cap(-150.0), 0.0)

    def test_private_state_persists_restart_risk_guards(self) -> None:
        with TemporaryDirectory() as temporary:
            service = LiveService.__new__(LiveService)
            service.portfolio = SourcePortfolio({})
            service.private_state_path = Path(temporary) / "state.json"
            service.profile = RISK_PROFILES["Capital10k"]
            service.cycle_baseline_pnl = -12.5
            service.cycle_reference_equity = 10_000.0
            service.daily_reference_equity = 10_000.0
            service.daily_hard_stop = True
            service.cooldown_until = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
            service.persist_private_state()
            saved = json.loads(service.private_state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["risk_profile"], "Capital10k")
            self.assertEqual(saved["cycle_baseline_pnl"], -12.5)
            self.assertTrue(saved["daily_hard_stop"])
            self.assertIsNotNone(saved["cooldown_until"])

    def test_guarded_execution_blocks_new_exposure(self) -> None:
        self.assertEqual(guarded_execution_target(0.0, 0.01, False), 0.0)
        self.assertEqual(guarded_execution_target(0.01, 0.0, False), 0.0)

    def test_guarded_reversal_closes_before_opening(self) -> None:
        self.assertEqual(guarded_execution_target(0.01, -0.01, False), 0.0)
        self.assertEqual(guarded_execution_target(0.01, -0.01, True), -0.01)
        self.assertEqual(guarded_execution_target(-0.01, 0.01, False), 0.0)

    def test_open_close_and_reversal_semantics(self) -> None:
        current = update_source_position(0.0, action=0, entry=0, lots=1.0)
        self.assertEqual(current, 1.0)
        current = update_source_position(current, action=1, entry=1, lots=0.4)
        self.assertEqual(current, 0.6)
        current = update_source_position(
            current, action=1, entry=2, lots=1.0, volume_closed_lots=0.6
        )
        self.assertAlmostEqual(current, -0.4)

    def test_portfolio_deduplicates_and_nets(self) -> None:
        clients = {
            1: ClientSpec(1, "C001", 1000.0, 0.03),
            2: ClientSpec(2, "C002", 1000.0, 0.03),
        }
        portfolio = SourcePortfolio(clients)
        buy = DealEvent(10, 100, 1, 101, 0, 0, "XAUUSD.G", 1.0, 0.0, 0, 0, 0, 0)
        sell = DealEvent(11, 101, 2, 102, 1, 0, "XAUUSD.G", 0.5, 0.0, 0, 0, 0, 0)
        self.assertTrue(portfolio.apply_deal(buy))
        self.assertFalse(portfolio.apply_deal(buy))
        self.assertTrue(portfolio.apply_deal(sell))
        target, gross_long, gross_short = portfolio.target("XAUUSD", 1000.0)
        self.assertAlmostEqual(target, 0.015)
        self.assertAlmostEqual(gross_long, 0.03)
        self.assertAlmostEqual(gross_short, 0.015)
        self.assertEqual(portfolio.duplicate_events, 1)

    def test_portfolio_rejects_out_of_order_event(self) -> None:
        clients = {1: ClientSpec(1, "C001", 1000.0, 0.03)}
        portfolio = SourcePortfolio(clients)
        newest = DealEvent(11, 101, 1, 101, 0, 0, "XAUUSD.G", 1.0, 0.0, 0, 0, 0, 0)
        older = DealEvent(10, 100, 1, 101, 1, 1, "XAUUSD.G", 1.0, 0.0, 0, 0, 0, 0)
        self.assertTrue(portfolio.apply_deal(newest))
        self.assertFalse(portfolio.apply_deal(older))
        self.assertEqual(portfolio.client_product_position(1, "XAUUSD"), 1.0)

    def test_friday_policy_uses_server_time(self) -> None:
        before = datetime(2026, 7, 31, 19, 29, tzinfo=timezone.utc)
        reduce_only = datetime(2026, 7, 31, 19, 30, tzinfo=timezone.utc)
        flatten = datetime(2026, 7, 31, 20, 30, tzinfo=timezone.utc)
        self.assertEqual(friday_policy(server_time_from_utc(before)), "normal")
        self.assertEqual(friday_policy(server_time_from_utc(reduce_only)), "reduce_only")
        self.assertEqual(friday_policy(server_time_from_utc(flatten)), "flatten")

    def test_cursor_ordering(self) -> None:
        self.assertLess(DealCursor(100, 1), DealCursor(100, 2))
        self.assertLess(DealCursor(100, 99), DealCursor(101, 1))

    def test_public_sequence_resumes_after_restart(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.csv"
            append_csv(path, {"event_id": "E0000001", "value": 1})
            append_csv(path, {"event_id": "E0000002", "value": 2})
            self.assertEqual(csv_data_rows(path), 2)

    def test_csv_schema_mismatch_rotates_original_before_appending(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "events_public.csv"
            legacy = "\n".join((
                "event_id,time_beijing,current_value",
                "E0000001,old,1,legacy_trailing_value",
                "",
            ))
            path.write_text(legacy, encoding="utf-8-sig", newline="")

            archive = ensure_csv_schema(path, ("event_id", "time_beijing", "current_value"))
            self.assertIsNotNone(archive)
            assert archive is not None
            self.assertEqual(archive.read_text(encoding="utf-8-sig"), legacy)
            self.assertFalse(path.exists())

            append_csv(path, {"event_id": "E0000002", "time_beijing": "new", "current_value": 2})
            self.assertEqual(
                path.read_text(encoding="utf-8-sig").splitlines(),
                ["event_id,time_beijing,current_value", "E0000002,new,2"],
            )
            self.assertEqual(csv_data_rows(path), 1)

    def test_recent_latency_window_restores_only_valid_samples(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.csv"
            for index in range(35):
                append_csv(
                    path,
                    {
                        "event_id": f"E{index:03d}",
                        "db_latency_seconds": index / 10,
                    },
                )
            restored = recent_csv_latencies(path, limit=30)
            self.assertEqual(len(restored), 30)
            self.assertEqual(restored[0], 0.5)
            self.assertEqual(restored[-1], 3.4)

    def test_live_reversal_closes_only_until_gates_recover(self) -> None:
        service = LiveService.__new__(LiveService)
        service.mt = FakeMt5Executor(0.01)
        service.current_target = -0.01
        service.last_error = ""
        service.external_position_conflict = False
        service.pending_order_conflict = False
        service.quote_allows_open = lambda: False
        service.log_order = lambda *_args: None

        service.execute_target(-0.01, "TEST")

        self.assertEqual(service.mt.moves, [0.0])
        self.assertEqual(service.mt.signed_position(), 0.0)
        self.assertEqual(service.current_target, -0.01)

        service.phase = "live"
        service.quote_allows_open = lambda: True
        service.reconcile_mt5_target()
        self.assertEqual(service.mt.moves, [0.0, -0.01])
        self.assertEqual(service.mt.signed_position(), -0.01)

    def test_foreign_position_allows_close_but_blocks_reversal_open(self) -> None:
        service = LiveService.__new__(LiveService)
        service.mt = FakeMt5Executor(0.01, foreign=True)
        service.current_target = -0.01
        service.last_error = ""
        service.external_position_conflict = False
        service.pending_order_conflict = False
        service.quote_allows_open = lambda: True
        service.log_order = lambda *_args: None

        service.execute_target(-0.01, "TEST")

        self.assertEqual(service.mt.moves, [0.0])
        self.assertIn("Exposure conflict", service.last_error)

    def test_open_gates_block_spread_quote_age_and_database_staleness(self) -> None:
        service = LiveService.__new__(LiveService)
        service.operational_gates_ready = lambda: True
        service.last_db_success = time.monotonic()

        service.mt = FakeMt5Executor(0.0)
        service.mt.quote_state = lambda: (4000.0, 4001.01, 0.1)
        self.assertFalse(service.quote_allows_open())

        service.mt.quote_state = lambda: (4000.0, 4000.36, 2.01)
        self.assertFalse(service.quote_allows_open())

        service.mt.quote_state = lambda: (4000.0, 4000.36, 0.1)
        service.last_db_success = time.monotonic() - 3.01
        self.assertFalse(service.quote_allows_open())

    def test_partial_fill_reconciliation_failure_flattens_and_hard_stops(self) -> None:
        service = LiveService.__new__(LiveService)
        service.mt = PartialFillMt5Executor(0.0)
        service.current_target = 0.01
        service.phase = "live"
        service.last_error = ""
        service.external_position_conflict = False
        service.pending_order_conflict = False
        service.quote_allows_open = lambda: True
        service.log_order = lambda *_args: None
        service.log = lambda *_args: None

        with self.assertRaises(RuntimeError):
            service.execute_target(0.01, "TEST")

        self.assertEqual(service.phase, "execution_hard_stop")
        self.assertEqual(service.current_target, 0.0)
        self.assertEqual(service.mt.signed_position(), 0.0)


if __name__ == "__main__":
    unittest.main()
