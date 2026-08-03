from __future__ import annotations

import csv
import unittest
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from copy_pool_multisource import (
    ROUTES,
    MAX_CLIENT_WEIGHT,
    MAX_ROUTE_WEIGHT,
    MultiSourceDatabase,
    MultiSourcePortfolio,
    ProductSpec,
    RoutedClient,
    RoutedEvent,
    SourceCursor,
    account_key,
    normalize_route_capped_weights,
    normalize_product_budget_weights,
    mt4_source_time_to_utc,
    mt4_source_utc_offset_hours,
    open_risk_multiplier,
    passes_current_open_risk_gate,
    physical_routes,
    rank_hourly_universe,
    require_nonempty_monitor_population,
    sleeve_key,
    validate_complete_coverage,
)
from copy_trading_live_core import ClientSpec, datetime_to_filetime
from copy_trading_live_demo import RISK_PROFILES, trading_day_key, utc_now
from copy_trading_multi_demo import (
    MULTISOURCE_EVENT_PUBLIC_COLUMNS,
    MULTISOURCE_ORDER_PUBLIC_COLUMNS,
    MultiSourceLiveService,
    has_complete_hourly_evidence,
    pool_build_day_key,
)
from copy_dynamic_pool_domain import SchedulerState
from copy_independent_execution import DemoChildTicket, IndependentCopyBook


def client(route_index: int, login: int, alias: str, money_scale: float = 1.0) -> RoutedClient:
    route = ROUTES[route_index]
    key = account_key(route.key, login)
    return RoutedClient(
        account_key=key,
        login=login,
        route_key=route.key,
        physical_key=route.physical_key,
        connection=route.connection,
        schema=route.schema,
        crm_schema=route.crm_schema,
        server_code=route.server_code,
        platform=route.platform,
        server=route.server,
        spec=ClientSpec(
            login=key,  # type: ignore[arg-type]
            alias=alias,
            equity_usd=1_000.0,
            base_weight=0.03,
            money_scale=money_scale,
        ),
    )


class MultiSourceTests(unittest.TestCase):
    def test_same_day_cache_upgrade_load_and_bootstrap_keep_weights_and_ticket_ownership(self) -> None:
        routed = client(0, 1, "C001")
        source_keys = set(physical_routes())
        source_rows = [
            {"physical_key": key, "state": "ok"}
            for key in sorted(source_keys)
        ]
        coverage = {
            "logical_routes_expected": len(ROUTES),
            "logical_routes_scanned": len(ROUTES),
            "physical_sources_expected": len(source_keys),
            "physical_sources_scanned": len(source_keys),
            "route_account_counts": {route.key: 1 for route in ROUTES},
            "sources": source_rows,
        }
        universe = pd.DataFrame([{
            "account_key": routed.account_key,
            "Login": routed.login,
            "route_key": routed.route_key,
            "physical_key": routed.physical_key,
            "sleeve_key": f"{routed.account_key}|XAUUSD",
            "product": "XAUUSD",
            "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
            "net_5d_usd": 20.0, "net_20d_usd": 300.0,
            "factor_ready": True, "factor_gate_reasons": "", "is_abook": False,
            "dynamic_score": 0.99, "open_risk_multiplier": 1.0, "hold_multiplier": 1.0,
            "hold_p25_seconds": 30.0, "median_hold_seconds": 300.0,
            "hold_p90_seconds": 1_000.0, "short_trade_ratio": 0.01,
            "quality_stress_net_15x_20d_usd": 10.0,
        }])

        restored_book = IndependentCopyBook()
        _action, restored_position = restored_book.observe_source_position(
            routed.account_key, routed.spec.alias, "XAUUSD", 901, 0.0, 1.0, utc_now()
        )
        assert restored_position is not None
        restored_position.copy_eligible = True
        restored_position.comment = "COPYPOOL_DEMO_V1"
        restored_position.children.append(
            DemoChildTicket(777001, 0.01, 1, utc_now().isoformat(), 100.0)
        )

        class FakeDatabase:
            sources = {key: object() for key in source_keys}

            @staticmethod
            def selected_clients(_pool: pd.DataFrame) -> dict[str, RoutedClient]:
                return {routed.account_key: routed}

            @staticmethod
            def set_clients(_clients: object) -> None:
                return None

            @staticmethod
            def highwaters() -> dict[str, SourceCursor]:
                return {routed.physical_key: SourceCursor(200, 20)}

            @staticmethod
            def all_positions() -> list[dict[str, object]]:
                return [{
                    "account_key": routed.account_key,
                    "position_id": 901,
                    "symbol": "XAUUSD",
                    "lots": 1.0,
                }]

            @staticmethod
            def intraday_net(_start: object) -> dict[str, float]:
                return {routed.account_key: 0.0}

            @staticmethod
            def selected_open_risk() -> dict[str, dict[str, float]]:
                return {routed.account_key: {"floating_pnl_usd": 0.0, "open_position_count": 1.0}}

        class FakeMt:
            @staticmethod
            def account() -> object:
                return SimpleNamespace(balance=10_000.0, equity=10_000.0, server="ACCMGlobal-Demo")

            @staticmethod
            def marked_pnl(_start: object) -> float:
                return 0.0

            @staticmethod
            def all_strategy_positions() -> tuple[object, ...]:
                return (SimpleNamespace(
                    ticket=777001, volume=0.01, price_open=100.0,
                    comment="COPYPOOL_DEMO_V1", symbol="XAUUSD",
                ),)

            @staticmethod
            def signed_positions() -> dict[str, float]:
                return {}

            @staticmethod
            def symbol(_product: str) -> object:
                return SimpleNamespace(volume_min=0.01, volume_step=0.01)

            @staticmethod
            def margin_per_lot(_side: float, _product: str) -> float:
                return 1.0

            @staticmethod
            def stress_loss_per_lot(_product: str, _move: float) -> float:
                return 1.0

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "pool_snapshot_private.csv").write_text("legacy\n", encoding="utf-8")
            universe.to_csv(directory / "pool_universe_private.csv", index=False)
            (directory / "source_coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
            (directory / "pool_build_meta_private.json").write_text(json.dumps({
                "producer": "copy-pool-multisource-v6-weight-fallback",
                "factor_schema": "execution-quality-v1",
                "pool_build_day": pool_build_day_key(utc_now()),
                "logical_routes": len(ROUTES),
                "physical_sources": len(source_keys),
                "build_as_of": utc_now().isoformat(),
            }), encoding="utf-8")
            state_path = directory / "runtime_state_private.json"
            state_path.write_text(json.dumps({
                "risk_profile": "Capital10k",
                "trading_day": trading_day_key(utc_now()),
                "independent_copy": restored_book.to_private(),
            }), encoding="utf-8")

            service = MultiSourceLiveService.__new__(MultiSourceLiveService)
            service.pool_snapshot_path = directory / "pool_snapshot_private.csv"
            service.pool_path = directory / "pool_public.csv"
            service.private_routes_path = directory / "client_routes_private.json"
            service.universe_path = directory / "pool_universe_private.csv"
            service.coverage_path = directory / "source_coverage.json"
            service.pool_build_meta_path = directory / "pool_build_meta_private.json"
            service.private_state_path = state_path
            service.db = FakeDatabase()  # type: ignore[assignment]
            service.current_targets = {}
            service.log = lambda *_args: None
            service.load_pool()

            self.assertFalse(service.pool_was_rebuilt)
            self.assertTrue(service.pool_weights_rebuilt)

            service.mt = FakeMt()
            service.profile = RISK_PROFILES["Capital10k"]
            service.args = SimpleNamespace(
                mode="StagedLive", allow_demo_min_lot_override=False,
                demo_fast_activation=False,
            )
            service.target_for_raw = lambda *_args: 0.0
            service.bootstrap()

            restored = service.copy_book.positions[restored_position.source_key]
            self.assertEqual([child.ticket for child in restored.children], [777001])
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn(
                str(777001),
                json.dumps(persisted["independent_copy"], sort_keys=True),
            )

    def test_mt5_trade_feature_close_and_lot_totals_use_all_close_entries(self) -> None:
        sql_calls: list[str] = []

        class FakeSource:
            platform = "MT5"
            schema = "readonly"

            @staticmethod
            def query(sql: str, _params: object = ()) -> list[dict[str, object]]:
                sql_calls.append(sql)
                return [{
                    "Login": 1, "Symbol": "XAUUSD", "closes": 2,
                    "net": 10.0, "gross_profit": 12.0, "gross_loss": 2.0,
                    "lots": 0.02, "source_contract_size": 100.0,
                    "spread_cost": 1.0,
                }]

        database = MultiSourceDatabase.__new__(MultiSourceDatabase)
        end = datetime(2026, 8, 3, tzinfo=timezone.utc)
        rows = database._trade_feature_rows(
            FakeSource(), end - timedelta(days=60), end - timedelta(days=20),
            end - timedelta(days=5), end,
        )

        self.assertTrue(rows)
        self.assertTrue(sql_calls)
        sql = sql_calls[0]
        self.assertGreaterEqual(sql.count("Entry IN (1,2,3)"), 2)
        self.assertIn(
            "SUM(CASE WHEN Entry IN (1,2,3) THEN VolumeExt / 100000000.0 ELSE 0 END) AS lots",
            sql,
        )
        self.assertIn(
            "SUM(CASE WHEN Entry IN (1,2,3) THEN 1 ELSE 0 END) AS closes",
            sql,
        )

    def test_same_day_cost_factor_upgrade_rebuilds_weights_and_rejects_cost_failures(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        universe = pd.DataFrame([
            {
                "account_key": "route:1", "Login": 1, "sleeve_key": "route:1|XAUUSD",
                "route_key": "route", "physical_key": "source-a", "product": "XAUUSD",
                "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
                "net_5d_usd": 20.0, "net_20d_usd": 300.0,
                "factor_ready": True, "factor_gate_reasons": "", "is_abook": False,
                "dynamic_score": 0.99, "open_risk_multiplier": 1.0, "hold_multiplier": 1.0,
                "hold_p25_seconds": 30.0, "median_hold_seconds": 300.0,
                "hold_p90_seconds": 1_000.0, "short_trade_ratio": 0.01,
                "quality_stress_net_15x_20d_usd": 10.0,
            },
            {
                "account_key": "route:2", "Login": 2, "sleeve_key": "route:2|XAUUSD",
                "route_key": "route", "physical_key": "source-a", "product": "XAUUSD",
                "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
                "net_5d_usd": 50.0, "net_20d_usd": 200.0,
                "factor_ready": True, "factor_gate_reasons": "", "is_abook": False,
                "dynamic_score": 0.01, "open_risk_multiplier": 1.0, "hold_multiplier": 1.0,
                "hold_p25_seconds": 30.0, "median_hold_seconds": 300.0,
                "hold_p90_seconds": 1_000.0, "short_trade_ratio": 0.01,
                "quality_stress_net_15x_20d_usd": 10.0,
            },
            {
                "account_key": "route:3", "Login": 3, "sleeve_key": "route:3|XAUUSD",
                "route_key": "route", "physical_key": "source-b", "product": "XAUUSD",
                "closes_5d": 2, "closes_20d": 10, "lots_20d": 1.0,
                "net_5d_usd": 1.0, "net_20d_usd": 20.0,
                "factor_ready": True, "factor_gate_reasons": "", "is_abook": False,
                "dynamic_score": 1.0, "open_risk_multiplier": 1.0, "hold_multiplier": 1.0,
                "hold_p25_seconds": 30.0, "median_hold_seconds": 300.0,
                "hold_p90_seconds": 1_000.0, "short_trade_ratio": 0.01,
                "quality_stress_net_15x_20d_usd": 10.0,
            },
        ])
        coverage = {
            "sources": [
                {"physical_key": "source-a", "state": "ok"},
                {"physical_key": "source-b", "state": "ok"},
            ],
        }

        pool, upgraded, upgraded_coverage = service._upgrade_same_day_cost_pool(universe, coverage)

        failed = upgraded.set_index("account_key").loc["route:3"]
        self.assertFalse(bool(failed["factor_ready"]))
        self.assertIn("cost_adjusted_net_5d_not_positive", failed["factor_gate_reasons"])
        self.assertNotIn("route:3", set(pool["account_key"]))
        self.assertTrue(bool(upgraded_coverage["same_day_cache_upgraded"]))
        self.assertEqual(upgraded_coverage["factor_model"], "cost_profit_recent_coverage_v1")
        self.assertEqual(upgraded_coverage["active_accounts"], 2)
        self.assertEqual(
            {row["physical_key"]: row["selected_clients"] for row in upgraded_coverage["sources"]},
            {"source-a": 2, "source-b": 0},
        )

    @staticmethod
    def _csv_service(directory: Path) -> MultiSourceLiveService:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.event_path = directory / "events_public.csv"
        service.order_path = directory / "orders_public.csv"
        service.timeline_path = directory / "status_timeline_public.csv"
        return service

    @staticmethod
    def _event_row(**overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "event_id": "E0000001",
            "time_beijing": "2026-07-30T22:00:00+08:00",
            "client_alias": "C001",
            "source_route": "ac_cn_mt5",
            "source_server": "AC CN MT5",
            "source_platform": "MT5",
            "source_side": "BUY",
            "source_entry": 0,
            "source_lots": 0.1,
            "product": "XAUUSD",
            "effective_weight": 0.03,
            "raw_target_lots": 0.01,
            "desired_target_lots": 0.01,
            "actual_strategy_lots": 0.01,
            "gross_long_lots": 0.01,
            "gross_short_lots": 0.0,
            "db_latency_seconds": 0.2,
            "allowed_delay_seconds": 5.0,
            "signal_expired": False,
            "phase": "shadow",
            "reason": "monitor",
        }
        row.update(overrides)
        return row

    def test_holding_statistics_splits_mt5_logins_and_time_windows(self) -> None:
        as_of = datetime(2026, 7, 31, 5, 0, tzinfo=timezone.utc)
        start = as_of.astimezone(timezone(timedelta(hours=8))).replace(
            tzinfo=None
        ) - timedelta(days=20)
        opened_at = start + timedelta(days=4, hours=23)
        closed_at = start + timedelta(days=5, hours=1)
        calls: list[tuple[object, ...]] = []

        def query(sql: str, params: tuple[object, ...] = ()):
            calls.append(params)
            self.assertIn(" AS opened_at", sql)
            logins = params[:-2]
            window_start, window_end = params[-2:]
            if len(logins) > 1 or window_end - window_start > timedelta(days=3):
                raise TimeoutError("holding shard timed out")
            login = int(logins[0])
            if login != 123:
                return []
            row = {
                "Login": login,
                "PositionID": 77,
                "Symbol": "XAUUSD",
                "opened_at": opened_at if window_start <= opened_at < window_end else None,
                "closed_at": closed_at if window_start <= closed_at < window_end else None,
            }
            return [row] if row["opened_at"] is not None or row["closed_at"] is not None else []

        source = SimpleNamespace(
            platform="MT5",
            schema="mt5_test",
            query=query,
        )
        database = MultiSourceDatabase.__new__(MultiSourceDatabase)
        database.sources = {"test-source": source}
        frame = pd.DataFrame([{
            "physical_key": "test-source",
            "Login": 123,
            "account_key": "test-route:123",
        }, {
            "physical_key": "test-source",
            "Login": 124,
            "account_key": "test-route:124",
        }])

        result = database.holding_statistics(frame, as_of)

        self.assertEqual(result["test-route:123|XAUUSD"]["holding_samples"], 1.0)
        self.assertEqual(result["test-route:123|XAUUSD"]["median_hold_seconds"], 7200.0)
        self.assertEqual(len(calls), 28)

    def test_multisource_schema_is_used_for_restart_validation(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            service = self._csv_service(directory)
            for path, columns in (
                (service.event_path, MULTISOURCE_EVENT_PUBLIC_COLUMNS),
                (service.order_path, MULTISOURCE_ORDER_PUBLIC_COLUMNS),
            ):
                path.write_text(",".join(columns) + "\n", encoding="utf-8-sig")

            service._ensure_public_csv_schemas()

            self.assertEqual(list(directory.glob("*.schema-mismatch-*.csv")), [])

    def test_multisource_mt5_then_mt4_events_use_one_aligned_schema(self) -> None:
        with TemporaryDirectory() as temporary:
            service = self._csv_service(Path(temporary))
            service._append_event_csv(self._event_row())
            service._append_event_csv(self._event_row(
                event_id="E0000002",
                source_platform="MT4",
                latency_known=True,
            ))

            with service.event_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(tuple(rows[0]), MULTISOURCE_EVENT_PUBLIC_COLUMNS)
            self.assertEqual(rows[0]["latency_known"], "")
            self.assertEqual(rows[1]["latency_known"], "True")
            self.assertEqual(list(service.event_path.parent.glob("*.schema-mismatch-*.csv")), [])

    def test_multisource_event_rejects_unknown_field(self) -> None:
        with TemporaryDirectory() as temporary:
            service = self._csv_service(Path(temporary))
            with self.assertRaisesRegex(ValueError, "unexpected fields"):
                service._append_event_csv(self._event_row(unexpected="reject"))

    def test_multisource_independent_then_flatten_orders_use_one_schema(self) -> None:
        with TemporaryDirectory() as temporary:
            service = self._csv_service(Path(temporary))
            service._append_order_csv({
                "order_event": "O000001",
                "time_beijing": "2026-07-30T22:00:00+08:00",
                "client_alias": "C001",
                "source_position_id": 7,
                "product": "XAUUSD",
                "action": "INDEPENDENT_OPEN",
                "before_lots": 0.0,
                "target_lots": 0.01,
                "after_lots": 0.01,
                "demo_tickets": "123",
            })
            service._append_order_csv({
                "order_event": "O000002",
                "time_beijing": "2026-07-30T22:01:00+08:00",
                "product": "XAUUSD",
                "action": "FLATTEN:test",
                "before_lots": 0.01,
                "target_lots": 0.0,
                "after_lots": 0.0,
            })

            with service.order_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(tuple(rows[0]), MULTISOURCE_ORDER_PUBLIC_COLUMNS)
            self.assertEqual(rows[1]["client_alias"], "")
            self.assertEqual(rows[1]["demo_tickets"], "")
            self.assertEqual(list(service.order_path.parent.glob("*.schema-mismatch-*.csv")), [])

    def test_multisource_legacy_header_with_wide_row_rotates_once(self) -> None:
        with TemporaryDirectory() as temporary:
            service = self._csv_service(Path(temporary))
            legacy_columns = MULTISOURCE_EVENT_PUBLIC_COLUMNS[:16]
            service.event_path.write_text(
                ",".join(legacy_columns) + "\n" + ",".join("legacy" for _ in MULTISOURCE_EVENT_PUBLIC_COLUMNS) + "\n",
                encoding="utf-8-sig",
            )

            service._ensure_public_csv_schemas()
            service._append_event_csv(self._event_row())
            service._ensure_public_csv_schemas()

            archives = list(service.event_path.parent.glob("*.schema-mismatch-*.csv"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(service.event_path.read_text(encoding="utf-8-sig").splitlines()[0], ",".join(MULTISOURCE_EVENT_PUBLIC_COLUMNS))

    def test_sources_without_selected_clients_are_idle_not_disconnected(self) -> None:
        database = MultiSourceDatabase()
        source = next(iter(database.sources.values()))
        source.health.success(0.01)

        database.set_clients({})

        self.assertEqual(source.health.selected_clients, 0)
        self.assertEqual(source.health.state, "idle")
        source.health.set_subscription_count(1)
        self.assertEqual(source.health.state, "starting")

    def test_missing_hourly_evidence_is_unknown_instead_of_zero(self) -> None:
        daily = pd.DataFrame([{"factor_base_score": 0.8}])
        self.assertFalse(has_complete_hourly_evidence(daily))

        restored = pd.DataFrame([{
            "hourly_score": 0.8,
            "current_comprehensive_net_20d_usd": 100.0,
            "hourly_hard_eligible": True,
            "hourly_activity_eligible": True,
        }])
        self.assertTrue(has_complete_hourly_evidence(restored))

    def test_hourly_pool_publish_updates_restart_snapshot(self) -> None:
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.public_pool_columns = ["client_alias", "hourly_score"]
        service.routed_clients = {}
        frame = pd.DataFrame([{"client_alias": "C001", "hourly_score": 0.81}])

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            service.pool_snapshot_path = directory / "pool_snapshot_private.csv"
            service.pool_path = directory / "pool_public.csv"
            service.private_routes_path = directory / "client_routes_private.json"
            service._publish_hourly_pool(frame)

            restored = pd.read_csv(service.pool_snapshot_path)
            public = pd.read_csv(service.pool_path)

        self.assertEqual(float(restored.iloc[0]["hourly_score"]), 0.81)
        self.assertEqual(float(public.iloc[0]["hourly_score"]), 0.81)

    def test_hourly_refresh_keeps_build_columns_when_current_product_positions_are_empty(self) -> None:
        database = MultiSourceDatabase.__new__(MultiSourceDatabase)

        class FakeSource:
            platform = "MT5"
            schema = "readonly"

            @staticmethod
            def query(_sql, _params=()):
                return []

        database.sources = {"source": FakeSource()}
        database.current_profiles = lambda _frame: pd.DataFrame([{
            "account_key": "route:1", "Equity": 1_000.0, "Margin": 0.0, "Profit": 0.0,
        }])
        database.current_product_positions = lambda _frame, _as_of: pd.DataFrame()
        universe = pd.DataFrame([{
            "account_key": "route:1", "Login": 1, "product": "XAUUSD",
            "sleeve_key": "route:1|XAUUSD", "factor_ready": True,
            "factor_base_score": 0.8, "activity_eligible": True, "net_20d_usd": 100.0,
            "equity_pre_usd": 1_000.0, "route_key": "route", "physical_key": "source",
            "hold_multiplier": 1.0, "is_abook": False, "money_scale": 1.0,
            "product_floating_pnl": 12.0, "product_hedge_ratio": 0.25,
        }])
        build_as_of = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)

        selected, _metadata = database.refresh_hourly_universe(
            universe, build_as_of=build_as_of, as_of=build_as_of + timedelta(hours=1)
        )

        self.assertEqual(float(selected.iloc[0]["current_product_floating_pnl_usd"]), 0.0)
        self.assertEqual(float(selected.iloc[0]["product_floating_pnl"]), 12.0)
        self.assertEqual(float(selected.iloc[0]["product_hedge_ratio"]), 0.25)

    def test_product_budget_cap_falls_back_only_when_diversification_is_infeasible(self) -> None:
        one, one_fallback = normalize_product_budget_weights({"XAUUSD": 4.0})
        self.assertTrue(one_fallback)
        self.assertAlmostEqual(one["XAUUSD"], 1.0)

        two, two_fallback = normalize_product_budget_weights({"XAUUSD": 9.0, "NAS100": 1.0})
        self.assertTrue(two_fallback)
        self.assertAlmostEqual(sum(two.values()), 1.0)
        self.assertAlmostEqual(two["XAUUSD"], 0.5)
        self.assertAlmostEqual(two["NAS100"], 0.5)

        three, three_fallback = normalize_product_budget_weights(
            {"XAUUSD": 6.0, "NAS100": 3.0, "EURUSD": 1.0}
        )
        self.assertFalse(three_fallback)
        self.assertAlmostEqual(sum(three.values()), 1.0)
        self.assertLessEqual(max(three.values()), 0.40 + 1e-12)

    def test_monitor_target_does_not_reject_a_small_nonempty_qualified_population(self) -> None:
        require_nonempty_monitor_population(8, context="after product risk gates")
        with self.assertRaisesRegex(RuntimeError, "No monitor accounts remained"):
            require_nonempty_monitor_population(0, context="after product risk gates")

    def test_hourly_ranking_uses_recent_strength_but_cannot_bypass_hard_gates(self) -> None:
        rows = []
        for index in range(105):
            account = f"route:{index}"
            rows.append({
                "account_key": account,
                "product": "XAUUSD" if index < 90 else "NAS100",
                "sleeve_key": f"{account}|{'XAUUSD' if index < 90 else 'NAS100'}",
                "factor_ready": index != 0,
                "factor_base_score": 0.80 - index * 0.001,
                "activity_eligible": True,
                "net_20d_usd": 100.0,
                "equity_pre_usd": 1_000.0,
                "route_key": "route",
                "physical_key": "source",
                "hold_multiplier": 1.0,
                "is_abook": False,
                "recent_net_1h_usd": 500.0 if index == 104 else 0.0,
                "recent_net_4h_usd": 500.0 if index == 104 else 0.0,
                "closed_delta_since_build_usd": 0.0,
                "current_product_floating_pnl_usd": -200.0 if index == 1 else 0.0,
                "current_equity_usd": 1_000.0,
                "current_margin_to_equity": 0.10,
                "current_floating_loss_ratio": 0.0,
                "current_open_risk_multiplier": 1.0,
            })

        selected, metadata = rank_hourly_universe(pd.DataFrame(rows))

        selected_accounts = set(selected["account_key"])
        self.assertIn("route:104", selected_accounts)
        self.assertNotIn("route:0", selected_accounts)
        self.assertNotIn("route:1", selected_accounts)
        self.assertEqual(metadata["monitor_accounts"], 30)
        self.assertEqual(metadata["reserve_accounts"], 70)
        self.assertEqual(selected["account_key"].nunique(), 100)

    def test_registry_has_eleven_routes_and_nine_physical_sources(self) -> None:
        self.assertEqual(len(ROUTES), 11)
        self.assertEqual(len(physical_routes()), 9)
        vn_routes = {(route.crm_schema, route.server_code): route.schema for route in ROUTES}
        self.assertEqual(vn_routes[("crm_vn", 2)], "mt5_export_new")
        self.assertEqual(vn_routes[("crm_vn", 5)], "crm_vn_mt5_live2")

    def test_account_identity_includes_route(self) -> None:
        self.assertNotEqual(account_key("ac_cn_mt4", 10002), account_key("ac_gb_mt4", 10002))

    def test_weight_allocator_caps_clients_and_routes(self) -> None:
        rows = pd.DataFrame(
            {
                "route_key": ["route-a"] * 6 + ["route-b"] * 6 + ["route-c"] * 6 + ["route-d"] * 6,
                "weight_alpha": [10.0 - index * 0.1 for index in range(24)],
            }
        )
        weights = normalize_route_capped_weights(rows)
        self.assertLessEqual(float(weights.max()), MAX_CLIENT_WEIGHT + 1e-12)
        for route, indexes in rows.groupby("route_key").groups.items():
            self.assertLessEqual(float(weights.loc[list(indexes)].sum()), MAX_ROUTE_WEIGHT + 1e-12, route)
        self.assertAlmostEqual(float(weights.sum()), 0.25)

    def test_open_risk_gate_and_multiplier_boundaries(self) -> None:
        self.assertTrue(passes_current_open_risk_gate(0.0999, 0.4999))
        self.assertFalse(passes_current_open_risk_gate(0.10, 0.10))
        self.assertFalse(passes_current_open_risk_gate(0.01, 0.50))
        self.assertEqual(open_risk_multiplier(0.0, 0.20, 0.0), 1.0)
        self.assertAlmostEqual(open_risk_multiplier(0.01, 0.20, 0.0), 0.5)
        self.assertEqual(open_risk_multiplier(0.02, 0.20, 0.0), 0.0)
        self.assertEqual(open_risk_multiplier(0.0, 0.20, 1.0), 0.5)

    def test_same_numeric_login_on_different_sources_does_not_collide(self) -> None:
        first = client(0, 10002, "C001")
        second = client(5, 10002, "C002")
        portfolio = MultiSourcePortfolio({first.account_key: first, second.account_key: second})
        portfolio.replace_positions(
            [
                {"account_key": first.account_key, "position_id": 7, "symbol": "XAUUSD", "lots": 1.0},
                {"account_key": second.account_key, "position_id": 7, "symbol": "XAUUSD", "lots": -0.5},
            ]
        )
        self.assertEqual(portfolio.client_product_position(first.account_key, "XAUUSD"), 1.0)
        self.assertEqual(portfolio.client_product_position(second.account_key, "XAUUSD"), -0.5)

    def test_monitor_only_product_never_contributes_effective_weight_or_target(self) -> None:
        routed = client(0, 10003, "C001")
        routed = replace(
            routed,
            products={
                "XAUUSD": ProductSpec(
                    product="XAUUSD",
                    base_weight=0.03,
                    historical_net_20d_usd=100.0,
                    source_contract_size=100.0,
                    demo_contract_size=100.0,
                    adjusted_score=0.8,
                    activity_eligible=False,
                )
            },
        )
        portfolio = MultiSourcePortfolio({routed.account_key: routed})
        portfolio.replace_positions([{
            "account_key": routed.account_key,
            "position_id": 7,
            "symbol": "XAUUSD",
            "lots": 1.0,
        }])
        portfolio.set_intraday_net({routed.account_key: 5.0})
        portfolio.set_intraday_product_net({f"{routed.account_key}|XAUUSD": 5.0})

        self.assertEqual(portfolio.effective_weights[routed.account_key], 0.0)
        self.assertEqual(
            portfolio.effective_product_weights[f"{routed.account_key}|XAUUSD"],
            0.0,
        )
        self.assertEqual(portfolio.target("XAUUSD", 10_000.0), (0, 0, 0))

    def test_cursors_are_independent_per_physical_source(self) -> None:
        first = client(0, 1, "C001")
        second = client(5, 2, "C002")
        portfolio = MultiSourcePortfolio({first.account_key: first, second.account_key: second})
        event_a = RoutedEvent(first.physical_key, first.account_key, first.account_key, 10, 100, 1, 0, 0, "XAUUSD", 1.0, 0.0, 0, 0, 0, 0)
        event_b = RoutedEvent(second.physical_key, second.account_key, second.account_key, 1, 50, 2, 1, 0, "XAUUSD", 0.5, 0.0, 0, 0, 0, 0)
        self.assertTrue(portfolio.apply_event(event_a))
        self.assertTrue(portfolio.apply_event(event_b))
        self.assertFalse(portfolio.apply_event(event_a))
        self.assertEqual(portfolio.cursors[first.physical_key], SourceCursor(100, 10))
        self.assertEqual(portfolio.cursors[second.physical_key], SourceCursor(50, 1))

    @staticmethod
    def _batch_event_service(routed: RoutedClient):
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.portfolio = MultiSourcePortfolio({routed.account_key: routed})
        service.routed_clients = {routed.account_key: routed}
        service.signal_latencies = []
        service.sleeve_states = {}
        service.sleeve_rows = {
            sleeve_key(routed.account_key, "XAUUSD"): {
                "historical_delay_enabled": False,
                "hold_p25_seconds": 60.0,
            }
        }
        service.copy_book = IndependentCopyBook()
        service.pending_coalesced_transitions = []
        service.phase = "live"
        service.current_targets = {"XAUUSD": 0.0}
        service.event_counter = 0
        service.mt = SimpleNamespace(signed_position=lambda _product: 0.0)
        service._effective_copy_weight = lambda _account, _product: 0.1
        service.persist_private_state = lambda: None
        service._refresh_targets = lambda: (
            {"XAUUSD": 0.0}, {"XAUUSD": 0.0}, {"XAUUSD": 0.0}, 0.0
        )
        return service

    def test_mt5_batch_open_and_close_to_flat_never_reaches_execution(self) -> None:
        routed = client(0, 1, "C001")
        service = self._batch_event_service(routed)
        handled: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []
        service._handle_source_position_change = lambda **kwargs: (
            handled.append(kwargs) or ("unexpected", None)
        )
        service._append_event_csv = rows.append
        opened_at = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        closed_at = opened_at + timedelta(milliseconds=100)
        events = [
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                1, datetime_to_filetime(opened_at), 901, 0, 0,
                "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                2, datetime_to_filetime(closed_at), 901, 1, 1,
                "XAUUSD", 0.01, 0.0, -0.2, 0.0, 0.0, 0.0,
            ),
        ]

        with patch("copy_trading_multi_demo.utc_now", return_value=closed_at):
            service.apply_event_batch(events)

        self.assertEqual(handled, [])
        self.assertNotIn((routed.account_key, 901, "XAUUSD"), service.portfolio.positions)
        self.assertEqual(
            service.portfolio.cursors[routed.physical_key],
            SourceCursor(datetime_to_filetime(closed_at), 2),
        )
        self.assertAlmostEqual(service.portfolio.intraday_net_usd[routed.account_key], -0.2)
        self.assertEqual(len(rows), 1)
        self.assertIn(
            "batch_coalesced_2:batch_terminal_flat:monitor",
            str(rows[0]["reason"]),
        )

    def test_mt5_batch_with_terminal_exposure_executes_only_once(self) -> None:
        routed = client(0, 1, "C001")
        service = self._batch_event_service(routed)
        handled: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []

        def handle(**kwargs):
            handled.append(kwargs)
            return "open", SimpleNamespace(status="active")

        service._handle_source_position_change = handle
        service._append_event_csv = rows.append
        opened_at = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        added_at = opened_at + timedelta(milliseconds=100)
        events = [
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                1, datetime_to_filetime(opened_at), 902, 0, 0,
                "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                2, datetime_to_filetime(added_at), 902, 0, 0,
                "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
        ]

        with patch(
            "copy_trading_multi_demo.utc_now",
            return_value=added_at + timedelta(seconds=1),
        ):
            service.apply_event_batch(events)

        self.assertEqual(len(handled), 1)
        self.assertEqual(handled[0]["before_lots"], 0.0)
        self.assertEqual(handled[0]["after_lots"], 0.02)
        self.assertEqual(handled[0]["signal_time"], opened_at)
        self.assertEqual(service.portfolio.positions[(routed.account_key, 902, "XAUUSD")], 0.02)
        self.assertEqual(len(rows), 1)
        self.assertIn("batch_coalesced_2:open:active", str(rows[0]["reason"]))

    def test_mt5_batch_reverse_uses_opposite_entry_as_signal_time(self) -> None:
        routed = client(0, 1, "C001")
        service = self._batch_event_service(routed)
        service.portfolio.replace_positions([{
            "account_key": routed.account_key,
            "position_id": 903,
            "symbol": "XAUUSD",
            "lots": 0.01,
        }])
        handled: list[dict[str, object]] = []
        service._handle_source_position_change = lambda **kwargs: (
            handled.append(kwargs) or ("reverse", SimpleNamespace(status="active"))
        )
        service._append_event_csv = lambda _row: None
        closed_at = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        reversed_at = closed_at + timedelta(milliseconds=100)
        events = [
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                1, datetime_to_filetime(closed_at), 903, 1, 1,
                "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                2, datetime_to_filetime(reversed_at), 903, 1, 0,
                "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
        ]

        with patch("copy_trading_multi_demo.utc_now", return_value=reversed_at):
            service.apply_event_batch(events)

        self.assertEqual(len(handled), 1)
        self.assertEqual(handled[0]["before_lots"], 0.01)
        self.assertEqual(handled[0]["after_lots"], -0.01)
        self.assertEqual(handled[0]["signal_time"], reversed_at)

    def test_mt5_batch_continues_after_one_transition_fails(self) -> None:
        routed = client(0, 1, "C001")
        service = self._batch_event_service(routed)
        persisted: list[bool] = []
        handled: list[int] = []
        service.persist_private_state = lambda: persisted.append(True)

        def handle(**kwargs):
            position_id = int(kwargs["position_id"])
            handled.append(position_id)
            if position_id == 904:
                raise RuntimeError("first transition failed")
            return "open", SimpleNamespace(status="active")

        service._handle_source_position_change = handle
        service._append_event_csv = lambda _row: None
        opened_at = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        events = [
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                1, datetime_to_filetime(opened_at), 904, 0, 0,
                "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                2, datetime_to_filetime(opened_at + timedelta(milliseconds=100)),
                905, 0, 0, "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
        ]

        with (
            patch(
                "copy_trading_multi_demo.utc_now",
                return_value=opened_at + timedelta(seconds=1),
            ),
            self.assertRaisesRegex(RuntimeError, "first transition failed"),
        ):
            service.apply_event_batch(events)

        self.assertGreaterEqual(len(persisted), 3)
        self.assertEqual(handled, [904, 905])
        self.assertEqual(len(service.pending_coalesced_transitions), 1)
        self.assertEqual(
            service.pending_coalesced_transitions[0]["last_event"].position_id,
            904,
        )
        serialized = [
            service._private_coalesced_transition(
                service.pending_coalesced_transitions[0]
            )
        ]
        restored = service._load_pending_coalesced_transitions(serialized)
        self.assertEqual(restored[0]["last_event"].position_id, 904)
        retained, cancelled = service._sanitize_restarted_pending_transitions(restored)
        self.assertEqual(retained, [])
        self.assertEqual(cancelled, 1)

        service.pending_coalesced_transitions = restored
        service._handle_source_position_change = lambda **kwargs: (
            handled.append(int(kwargs["position_id"]))
            or ("open", SimpleNamespace(status="active"))
        )
        with patch(
            "copy_trading_multi_demo.utc_now",
            return_value=opened_at + timedelta(seconds=1),
        ):
            service.apply_event_batch([])
        self.assertEqual(handled, [904, 905, 904])
        self.assertEqual(service.pending_coalesced_transitions, [])
        self.assertEqual(
            service.portfolio.cursors[routed.physical_key],
            SourceCursor(datetime_to_filetime(opened_at + timedelta(milliseconds=100)), 2),
        )

    def test_mt5_restart_pending_reverse_keeps_only_risk_release(self) -> None:
        routed = client(0, 1, "C001")
        closed_at = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        reversed_at = closed_at + timedelta(milliseconds=100)
        close_event = RoutedEvent(
            routed.physical_key, routed.account_key, routed.account_key,
            1, datetime_to_filetime(closed_at), 910, 1, 1,
            "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
        )
        reverse_event = RoutedEvent(
            routed.physical_key, routed.account_key, routed.account_key,
            2, datetime_to_filetime(reversed_at), 910, 1, 0,
            "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
        )
        retained, cancelled = MultiSourceLiveService._sanitize_restarted_pending_transitions([{
            "first_event": close_event,
            "last_event": reverse_event,
            "before_lots": 0.01,
            "after_lots": -0.01,
            "event_count": 2,
            "first_risk_event": reverse_event,
        }])

        self.assertEqual(cancelled, 1)
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["after_lots"], 0.0)
        self.assertIsNone(retained[0]["first_risk_event"])

    def test_mt5_invalid_pending_journal_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a list"):
            MultiSourceLiveService._load_pending_coalesced_transitions({})
        with self.assertRaisesRegex(ValueError, "transition 0 is invalid"):
            MultiSourceLiveService._load_pending_coalesced_transitions([{}])

    def test_mt5_batch_executes_pure_reduction_before_new_risk(self) -> None:
        routed = client(0, 1, "C001")
        service = self._batch_event_service(routed)
        service.portfolio.replace_positions([{
            "account_key": routed.account_key,
            "position_id": 906,
            "symbol": "XAUUSD",
            "lots": 0.01,
        }])
        handled: list[int] = []
        service._handle_source_position_change = lambda **kwargs: (
            handled.append(int(kwargs["position_id"]))
            or ("handled", SimpleNamespace(status="active"))
        )
        service._append_event_csv = lambda _row: None
        stamp = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        events = [
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                1, datetime_to_filetime(stamp), 907, 0, 0,
                "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
            RoutedEvent(
                routed.physical_key, routed.account_key, routed.account_key,
                2, datetime_to_filetime(stamp + timedelta(milliseconds=100)),
                906, 1, 1, "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
            ),
        ]

        with patch("copy_trading_multi_demo.utc_now", return_value=stamp + timedelta(seconds=1)):
            service.apply_event_batch(events)

        self.assertEqual(handled, [906, 907])

    def test_mt5_pending_open_and_later_close_coalesce_without_demo_round_trip(self) -> None:
        routed = client(0, 1, "C001")
        service = self._batch_event_service(routed)
        handled: list[int] = []
        rows: list[dict[str, object]] = []
        service._append_event_csv = rows.append
        opened_at = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        open_event = RoutedEvent(
            routed.physical_key, routed.account_key, routed.account_key,
            1, datetime_to_filetime(opened_at), 909, 0, 0,
            "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
        )
        close_event = RoutedEvent(
            routed.physical_key, routed.account_key, routed.account_key,
            2, datetime_to_filetime(opened_at + timedelta(milliseconds=500)),
            909, 1, 1, "XAUUSD", 0.01, 0.0, -0.2, 0.0, 0.0, 0.0,
        )

        service._handle_source_position_change = lambda **kwargs: (
            handled.append(int(kwargs["position_id"]))
            or (_ for _ in ()).throw(RuntimeError("open unavailable"))
        )
        with (
            patch(
                "copy_trading_multi_demo.utc_now",
                return_value=opened_at + timedelta(milliseconds=100),
            ),
            self.assertRaisesRegex(RuntimeError, "open unavailable"),
        ):
            service.apply_event_batch([open_event])

        service._handle_source_position_change = lambda **kwargs: (
            handled.append(int(kwargs["position_id"]))
            or ("unexpected", SimpleNamespace(status="active"))
        )
        with patch(
            "copy_trading_multi_demo.utc_now",
            return_value=opened_at + timedelta(seconds=1),
        ):
            service.apply_event_batch([close_event])

        self.assertEqual(handled, [909])
        self.assertEqual(service.pending_coalesced_transitions, [])
        self.assertIn("batch_coalesced_2:batch_terminal_flat", str(rows[-1]["reason"]))

    def test_mt5_expired_terminal_exposure_is_not_reported_as_source_flat(self) -> None:
        routed = client(0, 1, "C001")
        service = self._batch_event_service(routed)
        handled: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []
        service._handle_source_position_change = lambda **kwargs: (
            handled.append(kwargs) or ("unexpected", None)
        )
        service._append_event_csv = rows.append
        opened_at = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        event = RoutedEvent(
            routed.physical_key, routed.account_key, routed.account_key,
            1, datetime_to_filetime(opened_at), 908, 0, 0,
            "XAUUSD", 0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
        )

        with patch(
            "copy_trading_multi_demo.utc_now",
            return_value=opened_at + timedelta(seconds=6),
        ):
            service.apply_event_batch([event])

        self.assertEqual(handled, [])
        self.assertIn("signal_expired_no_copy", str(rows[0]["reason"]))
        self.assertNotIn("batch_terminal_flat", str(rows[0]["reason"]))

    def test_cent_profit_scales_but_position_lots_do_not(self) -> None:
        cent = client(7, 5200101, "C001", money_scale=0.01)
        portfolio = MultiSourcePortfolio({cent.account_key: cent})
        event = RoutedEvent(
            cent.physical_key, cent.account_key, cent.account_key, 1, 1, 9, 0, 0,
            "XAUUSD.G", 2.0, 0.0, -100.0, 0.0, 0.0, 0.0,
        )
        self.assertTrue(portfolio.apply_event(event))
        self.assertEqual(portfolio.client_product_position(cent.account_key, "XAUUSD"), 2.0)
        self.assertEqual(portfolio.intraday_net_usd[cent.account_key], -1.0)

    def test_floating_profit_never_increases_weight_but_floating_loss_reduces_it(self) -> None:
        routed = client(0, 10, "C001")
        portfolio = MultiSourcePortfolio({routed.account_key: routed})
        portfolio.set_intraday_net({routed.account_key: 5.0})
        portfolio.set_open_risk({routed.account_key: {"floating_pnl_usd": 100.0}})

        self.assertEqual(portfolio.dynamic_evaluation_usd[routed.account_key], 0.0)
        self.assertEqual(portfolio.effective_weights[routed.account_key], routed.spec.base_weight)

        portfolio.set_open_risk({routed.account_key: {"floating_pnl_usd": -15.0}})

        self.assertEqual(portfolio.dynamic_evaluation_usd[routed.account_key], -15.0)
        self.assertAlmostEqual(portfolio.effective_weights[routed.account_key], 0.0075)

    def test_hedged_positions_keep_gross_open_risk_even_when_net_target_is_zero(self) -> None:
        routed = client(0, 10, "C001")
        portfolio = MultiSourcePortfolio({routed.account_key: routed})
        portfolio.replace_positions([
            {"account_key": routed.account_key, "position_id": 1, "symbol": "XAUUSD", "lots": 1.0},
            {"account_key": routed.account_key, "position_id": 2, "symbol": "XAUUSD", "lots": -1.0},
        ])
        portfolio.set_open_risk({routed.account_key: {
            "floating_pnl_usd": -8.0,
            "xau_gross_lots": 2.0,
            "xau_net_lots": 0.0,
            "xau_hedge_ratio": 1.0,
        }})

        target, _long, _short = portfolio.target("XAUUSD", 10_000.0)
        self.assertEqual(target, 0.0)
        self.assertEqual(portfolio.open_risk_by_account[routed.account_key]["xau_gross_lots"], 2.0)
        self.assertLess(portfolio.effective_weights[routed.account_key], routed.spec.base_weight)

    def test_non_trading_mt5_event_advances_cursor_without_changing_portfolio(self) -> None:
        routed = client(0, 10002, "C001")
        portfolio = MultiSourcePortfolio({routed.account_key: routed})
        portfolio.replace_positions(
            [{"account_key": routed.account_key, "position_id": 7, "symbol": "XAUUSD", "lots": 0.5}]
        )
        ledger_event = RoutedEvent(
            routed.physical_key,
            routed.account_key,
            routed.account_key,
            20,
            200,
            0,
            2,
            0,
            "",
            0.0,
            0.0,
            500.0,
            0.0,
            0.0,
            0.0,
        )

        self.assertFalse(portfolio.apply_event(ledger_event))
        self.assertEqual(portfolio.cursors[routed.physical_key], SourceCursor(200, 20))
        self.assertEqual(portfolio.client_product_position(routed.account_key, "XAUUSD"), 0.5)
        self.assertEqual(portfolio.intraday_net_usd[routed.account_key], 0.0)
        self.assertEqual(portfolio.non_trading_events, 1)
        self.assertEqual(portfolio.duplicate_events, 0)

        self.assertFalse(portfolio.apply_event(ledger_event))
        self.assertEqual(portfolio.non_trading_events, 1)
        self.assertEqual(portfolio.duplicate_events, 1)

    def test_duplicate_and_out_of_order_events_are_isolated_by_source(self) -> None:
        first = client(0, 1, "C001")
        second = client(5, 2, "C002")
        portfolio = MultiSourcePortfolio({first.account_key: first, second.account_key: second})
        newest = RoutedEvent(first.physical_key, first.account_key, first.account_key, 20, 200, 7, 0, 0, "XAUUSD", 1.0, 0.0, 0, 0, 0, 0)
        older = RoutedEvent(first.physical_key, first.account_key, first.account_key, 19, 199, 7, 1, 1, "XAUUSD", 1.0, 0.0, 0, 0, 0, 0)
        other_source = RoutedEvent(second.physical_key, second.account_key, second.account_key, 1, 100, 8, 1, 0, "XAUUSD", 0.5, 0.0, 0, 0, 0, 0)

        self.assertTrue(portfolio.apply_event(newest))
        self.assertFalse(portfolio.apply_event(newest))
        self.assertFalse(portfolio.apply_event(older))
        self.assertTrue(portfolio.apply_event(other_source))
        self.assertEqual(portfolio.client_product_position(first.account_key, "XAUUSD"), 1.0)
        self.assertEqual(portfolio.client_product_position(second.account_key, "XAUUSD"), -0.5)
        self.assertEqual(portfolio.duplicate_events, 2)

    def test_mt4_authoritative_snapshot_can_reverse_without_touching_other_sources(self) -> None:
        mt4 = client(3, 10, "C001")
        mt5 = client(0, 20, "C002")
        portfolio = MultiSourcePortfolio({mt4.account_key: mt4, mt5.account_key: mt5})
        portfolio.replace_positions([
            {"account_key": mt4.account_key, "position_id": 1, "symbol": "XAUUSD", "lots": 1.0},
            {"account_key": mt5.account_key, "position_id": 2, "symbol": "XAUUSD", "lots": 0.25},
        ])

        changed = portfolio.replace_source_positions(mt4.physical_key, [
            {"account_key": mt4.account_key, "position_id": 3, "symbol": "XAUUSD", "lots": -0.75},
        ])

        self.assertTrue(changed)
        self.assertEqual(portfolio.client_product_position(mt4.account_key, "XAUUSD"), -0.75)
        self.assertEqual(portfolio.client_product_position(mt5.account_key, "XAUUSD"), 0.25)

    def test_mt4_current_position_open_time_is_interpreted_as_utc(self) -> None:
        routed = client(3, 6002426, "C001", money_scale=0.01)
        database = MultiSourceDatabase()
        database.clients = {routed.account_key: routed}
        database.clients_by_source_login = {
            routed.physical_key: {routed.login: routed.account_key}
        }

        class FakeSource:
            platform = "MT4"
            schema = "mt4_export_syc"

            @staticmethod
            def query(_sql: str, _params: object = ()) -> list[dict[str, object]]:
                return [{
                    "TICKET": 15658692,
                    "LOGIN": 6002426,
                    "SYMBOL": "XAUUSD.E",
                    "CMD": 0,
                    "lots": 0.01,
                    "OPEN_TIME": datetime(2026, 7, 30, 14, 59, 55),
                    "OPEN_PRICE": 4010.5,
                    "CLOSE_PRICE": 4012.0,
                    "floating_pnl": 123.45,
                }]

        database.sources = {routed.physical_key: FakeSource()}

        rows = database.positions_for_source(routed.physical_key)

        self.assertEqual(rows[0]["source_opened_at"], "2026-07-30T14:59:55+00:00")
        self.assertEqual(rows[0]["source_open_price"], 4010.5)
        self.assertEqual(rows[0]["source_current_price"], 4012.0)
        self.assertAlmostEqual(rows[0]["source_floating_pnl_usd"], 1.2345)

    def test_mt4_physical_source_offsets_are_explicit_and_keep_live3_routed(self) -> None:
        self.assertEqual(
            mt4_source_utc_offset_hours("AC:mt4_export_syc:MT4"), 0
        )
        self.assertEqual(
            mt4_source_utc_offset_hours("DBG:crm_cn_mt4_live1:MT4"), 3
        )
        self.assertEqual(
            mt4_source_utc_offset_hours("DBG:crm_cn_mt4_live2:MT4"), 3
        )
        self.assertEqual(
            mt4_source_utc_offset_hours("DBG:crm_vn_mt4_live3:MT4"), 3
        )
        self.assertIn("DBG:crm_vn_mt4_live3:MT4", physical_routes())

    def test_dbg_mt4_current_position_open_time_is_normalized_from_utc_plus_three(self) -> None:
        raw_open = datetime(2026, 7, 31, 11, 2, 9)
        expected = datetime(2026, 7, 31, 8, 2, 9, tzinfo=timezone.utc)
        self.assertEqual(
            mt4_source_time_to_utc("DBG:crm_cn_mt4_live1:MT4", raw_open),
            expected,
        )
        self.assertEqual(
            mt4_source_time_to_utc("DBG:crm_cn_mt4_live2:MT4", raw_open),
            expected,
        )

    def test_dbg_mt4_position_snapshot_uses_physical_source_offset(self) -> None:
        routed = client(8, 7798014, "C001")
        database = MultiSourceDatabase()
        database.clients_by_source_login = {
            routed.physical_key: {routed.login: routed.account_key}
        }

        class FakeSource:
            platform = "MT4"
            schema = "crm_cn_mt4_live1"

            @staticmethod
            def query(_sql: str, _params: object = ()) -> list[dict[str, object]]:
                return [{
                    "TICKET": 28450463,
                    "LOGIN": 7798014,
                    "SYMBOL": "XAUUSD",
                    "CMD": 0,
                    "lots": 0.05,
                    "OPEN_TIME": datetime(2026, 7, 31, 11, 2, 9),
                }]

        database.sources = {routed.physical_key: FakeSource()}

        rows = database.positions_for_source(routed.physical_key)

        self.assertEqual(rows[0]["source_opened_at"], "2026-07-31T08:02:09+00:00")

    def test_mt4_entry_seen_three_seconds_after_open_is_not_expired(self) -> None:
        routed = client(3, 6002426, "C001")
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.routed_clients = {routed.account_key: routed}
        service.portfolio = MultiSourcePortfolio(service.routed_clients)
        service.db = SimpleNamespace(sources={
            routed.physical_key: SimpleNamespace(
                health=SimpleNamespace(latency_ms=78.0)
            )
        })
        service.current_targets = {"XAUUSD": 0.0}
        service.phase = "live"
        service.event_counter = 0
        service.event_path = Path("unused.csv")
        service.mt = SimpleNamespace(signed_position=lambda _product: 0.0)
        service.sleeve_rows = {
            sleeve_key(routed.account_key, "XAUUSD"): {
                "historical_delay_enabled": False,
                "hold_p25_seconds": 3_600.0,
            }
        }
        service.sleeve_states = {}
        service._refresh_targets = lambda: (
            {"XAUUSD": 0.0}, {"XAUUSD": 0.01}, {"XAUUSD": 0.0}, 0.0
        )
        service._approved_source_after = (
            lambda _account, _position, _product, _before, after, *, entry_timely: (
                after if entry_timely else 0.0
            )
        )
        observed: list[dict[str, object]] = []
        service._handle_source_position_change = lambda **kwargs: (
            observed.append(kwargs) or ("open", None)
        )
        event_rows: list[dict[str, object]] = []
        service._append_event_csv = event_rows.append
        observed_at = datetime(2026, 7, 30, 14, 59, 58, tzinfo=timezone.utc)

        with patch("copy_trading_multi_demo.utc_now", return_value=observed_at):
            service.apply_mt4_snapshot(routed.physical_key, [{
                "account_key": routed.account_key,
                "position_id": 15658692,
                "symbol": "XAUUSD.E",
                "lots": 0.01,
                "source_opened_at": "2026-07-30T14:59:55+00:00",
            }])

        self.assertEqual(observed[0]["after_lots"], 0.01)
        self.assertEqual(observed[0]["signal_time"], datetime(
            2026, 7, 30, 14, 59, 55, tzinfo=timezone.utc
        ))
        self.assertFalse(event_rows[0]["signal_expired"])
        self.assertTrue(event_rows[0]["latency_known"])
        self.assertEqual(event_rows[0]["allowed_delay_seconds"], 5.0)

    def test_dbg_mt4_entry_seen_two_seconds_after_normalized_open_is_not_expired(self) -> None:
        routed = client(8, 7798014, "C001")
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.routed_clients = {routed.account_key: routed}
        service.portfolio = MultiSourcePortfolio(service.routed_clients)
        service.db = SimpleNamespace(sources={
            routed.physical_key: SimpleNamespace(
                health=SimpleNamespace(latency_ms=78.0)
            )
        })
        service.current_targets = {"XAUUSD": 0.0}
        service.phase = "live"
        service.event_counter = 0
        service.event_path = Path("unused.csv")
        service.mt = SimpleNamespace(signed_position=lambda _product: 0.0)
        service.sleeve_rows = {
            sleeve_key(routed.account_key, "XAUUSD"): {
                "historical_delay_enabled": False,
                "hold_p25_seconds": 3_600.0,
            }
        }
        service.sleeve_states = {}
        service._refresh_targets = lambda: (
            {"XAUUSD": 0.0}, {"XAUUSD": 0.01}, {"XAUUSD": 0.0}, 0.0
        )
        service._approved_source_after = (
            lambda _account, _position, _product, _before, after, *, entry_timely: (
                after if entry_timely else 0.0
            )
        )
        observed: list[dict[str, object]] = []
        service._handle_source_position_change = lambda **kwargs: (
            observed.append(kwargs) or ("open", None)
        )
        event_rows: list[dict[str, object]] = []
        service._append_event_csv = event_rows.append
        observed_at = datetime(2026, 7, 31, 8, 2, 11, tzinfo=timezone.utc)

        with patch("copy_trading_multi_demo.utc_now", return_value=observed_at):
            service.apply_mt4_snapshot(routed.physical_key, [{
                "account_key": routed.account_key,
                "position_id": 28450463,
                "symbol": "XAUUSD",
                "lots": 0.05,
                "source_opened_at": "2026-07-31T08:02:09+00:00",
            }])

        self.assertEqual(observed[0]["after_lots"], 0.05)
        self.assertEqual(observed[0]["signal_time"], datetime(
            2026, 7, 31, 8, 2, 9, tzinfo=timezone.utc
        ))
        self.assertFalse(event_rows[0]["signal_expired"])
        self.assertTrue(event_rows[0]["latency_known"])
        self.assertEqual(event_rows[0]["allowed_delay_seconds"], 5.0)

    def test_mt4_snapshot_diff_emits_only_the_changed_customer_position(self) -> None:
        first = client(3, 10, "C001")
        second = client(3, 20, "C002")
        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.routed_clients = {
            first.account_key: first,
            second.account_key: second,
        }
        service.portfolio = MultiSourcePortfolio(service.routed_clients)
        service.portfolio.replace_positions([
            {"account_key": first.account_key, "position_id": 1, "symbol": "XAUUSD", "lots": 1.0},
            {"account_key": second.account_key, "position_id": 2, "symbol": "XAUUSD", "lots": -0.5},
        ])
        service.db = SimpleNamespace(sources={
            first.physical_key: SimpleNamespace(
                health=SimpleNamespace(latency_ms=12.0)
            )
        })
        service.current_targets = {"XAUUSD": 0.0}
        service.phase = "shadow"
        service.event_counter = 0
        service.event_path = Path("unused.csv")
        service.mt = SimpleNamespace(signed_position=lambda _product: 0.0)
        service._refresh_targets = lambda: (
            {"XAUUSD": 0.0}, {"XAUUSD": 1.0}, {"XAUUSD": 0.5}, 0.0
        )
        observed: list[dict[str, object]] = []

        def capture(**kwargs):
            observed.append(kwargs)
            return "reduce", None

        service._handle_source_position_change = capture
        service._append_event_csv = lambda _row: None
        service.apply_mt4_snapshot(first.physical_key, [
            {"account_key": first.account_key, "position_id": 1, "symbol": "XAUUSD", "lots": 0.25},
            {"account_key": second.account_key, "position_id": 2, "symbol": "XAUUSD", "lots": -0.5},
        ])

        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["account_key"], first.account_key)
        self.assertEqual(observed[0]["position_id"], 1)
        self.assertEqual(observed[0]["before_lots"], 1.0)
        self.assertEqual(observed[0]["after_lots"], 0.25)
        self.assertEqual(
            service.portfolio.client_product_position(second.account_key, "XAUUSD"),
            -0.5,
        )

    def test_one_selected_source_outage_is_explicit_and_stale(self) -> None:
        first = client(0, 1, "C001")
        second = client(5, 2, "C002")
        database = MultiSourceDatabase()

        class FakeSource:
            def __init__(self, routed: RoutedClient, fail: bool) -> None:
                from copy_pool_multisource import SourceHealth

                self.platform = "MT5"
                self.schema = routed.schema
                self.fail = fail
                self.health = SourceHealth(
                    routed.physical_key,
                    routed.connection,
                    routed.schema,
                    routed.platform,
                    (routed.route_key,),
                )

            def query(self, _sql: str, _params: object = ()) -> list[dict[str, object]]:
                if self.fail:
                    error = RuntimeError("simulated source outage")
                    self.health.failure(error)
                    raise error
                self.health.success(0.001)
                return []

        database.sources[first.physical_key] = FakeSource(first, False)  # type: ignore[assignment]
        database.sources[second.physical_key] = FakeSource(second, True)  # type: ignore[assignment]
        database.set_clients({first.account_key: first, second.account_key: second})

        events, errors = database.poll_mt5_events({})

        self.assertEqual(events, [])
        self.assertEqual(len(errors), 1)
        self.assertIn(second.physical_key, errors[0])
        self.assertEqual(database.sources[second.physical_key].health.state, "error")
        self.assertEqual(database.selected_source_staleness(), float("inf"))

    def test_incomplete_all_route_build_is_rejected(self) -> None:
        source_keys = set(physical_routes())
        coverage = {
            "logical_routes_expected": len(ROUTES),
            "logical_routes_scanned": len(ROUTES) - 1,
            "physical_sources_expected": len(source_keys),
            "physical_sources_scanned": len(source_keys),
            "route_account_counts": {route.key: 1 for route in ROUTES[:-1]},
            "sources": [
                {"physical_key": key, "state": "ok"}
                for key in source_keys
            ],
        }

        with self.assertRaisesRegex(RuntimeError, "All-source coverage gate failed"):
            validate_complete_coverage(coverage, source_keys)

    def test_restart_uses_authoritative_highwaters_and_persists_source_cursors(self) -> None:
        routed = client(0, 1, "C001")
        restored_book = IndependentCopyBook()
        _action, restored_position = restored_book.observe_source_position(
            routed.account_key,
            "C001",
            "XAUUSD",
            901,
            0.0,
            1.0,
            utc_now(),
        )
        assert restored_position is not None
        restored_position.copy_eligible = True

        class FakeDatabase:
            @staticmethod
            def highwaters() -> dict[str, SourceCursor]:
                return {routed.physical_key: SourceCursor(200, 20)}

            @staticmethod
            def all_positions() -> list[dict[str, object]]:
                return [{
                    "account_key": routed.account_key,
                    "position_id": 901,
                    "symbol": "XAUUSD",
                    "lots": 1.0,
                }]

            @staticmethod
            def intraday_net(_start: object) -> dict[str, float]:
                return {routed.account_key: -2.0}

            @staticmethod
            def selected_open_risk() -> dict[str, dict[str, float]]:
                return {routed.account_key: {"floating_pnl_usd": -3.0, "open_position_count": 1.0}}

        class FakeMt:
            @staticmethod
            def account() -> object:
                return SimpleNamespace(balance=10_000.0, equity=10_000.0)

            @staticmethod
            def marked_pnl(_start: object) -> float:
                return 0.0

            @staticmethod
            def all_strategy_positions() -> tuple[object, ...]:
                return ()

        with TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "runtime_state_private.json"
            state_path.write_text(json.dumps({
                "cursors": {routed.physical_key: {"timestamp": 100, "sequence": 10}},
                "risk_profile": "Capital10k",
                "trading_day": trading_day_key(utc_now()),
                "cycle_baseline_pnl": 0.0,
                "cycle_reference_equity": 10_000.0,
                "daily_reference_equity": 10_000.0,
                "daily_hard_stop": False,
                "cooldown_until": None,
                "independent_copy": restored_book.to_private(),
                "sleeve_dynamic": {
                    f"{routed.account_key}|XAUUSD": {
                        "day_start_base_weight": 0.03,
                        "effective_weight": 0.0,
                        "tier": "execution_suspended",
                    }
                },
            }), encoding="utf-8")
            service = MultiSourceLiveService.__new__(MultiSourceLiveService)
            service.private_state_path = state_path
            service.routed_clients = {routed.account_key: routed}
            service.db = FakeDatabase()  # type: ignore[assignment]
            service.mt = FakeMt()
            service.profile = RISK_PROFILES["Capital10k"]
            service.args = SimpleNamespace(mode="Shadow")
            service.target_for_raw = lambda *_args: 0.0
            service.log = lambda *_args: None
            service.pool_frame = pd.DataFrame([{
                "sleeve_key": f"{routed.account_key}|XAUUSD",
                "live_base_weight": 0.02,
                "factor_ready": True,
            }])
            service.pool_was_rebuilt = False

            service.bootstrap()

            self.assertEqual(service.portfolio.cursors[routed.physical_key], SourceCursor(200, 20))
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["cursors"][routed.physical_key], {"timestamp": 200, "sequence": 20})
            self.assertEqual(persisted["effective_weights"][routed.account_key], service.portfolio.effective_weights[routed.account_key])
            self.assertEqual(service.portfolio.intraday_net_usd[routed.account_key], -2.0)
            self.assertEqual(service.portfolio.floating_pnl_usd[routed.account_key], -3.0)
            self.assertEqual(service.portfolio.dynamic_evaluation_usd[routed.account_key], -5.0)
            self.assertEqual(
                service.sleeve_states[f"{routed.account_key}|XAUUSD"].tier.value,
                "execution_suspended",
            )
            guarded = service.copy_book.positions[restored_position.source_key]
            self.assertFalse(guarded.copy_eligible)
            self.assertTrue(guarded.restart_monitor_only)
            self.assertEqual(guarded.reject_reason, "restart_without_demo_ticket")

    def test_hourly_discovery_rotates_subscription_without_chasing_current_positions(self) -> None:
        clients = {
            item.account_key: item
            for item in [client(0, 1000 + index, f"C{index + 1:03d}") for index in range(10)]
        }
        discovered = pd.DataFrame([
            {
                "account_key": routed.account_key,
                "sleeve_key": f"{routed.account_key}|XAUUSD",
                "product": "XAUUSD",
                "activity_eligible": True,
                "hourly_activity_eligible": True,
                "pool_tier": "monitor",
                "pool_status": "active_candidate",
                "factor_ready": True,
                "live_base_weight": 0.01,
            }
            for routed in clients.values()
        ])
        discovered.loc[0, "activity_eligible"] = False
        discovered.loc[0, "hourly_activity_eligible"] = False

        class FakeDatabase:
            def refresh_hourly_universe(self, *_args, **_kwargs):
                return discovered.copy(), {
                    "factor_ready_sleeves_scanned": 10,
                    "monitor_accounts": 10,
                    "reserve_accounts": 0,
                }

            def selected_clients(self, _pool):
                return clients

            def set_clients(self, _clients):
                self.clients = dict(_clients)

            @staticmethod
            def highwaters():
                return {}

            @staticmethod
            def all_positions():
                return []

            @staticmethod
            def intraday_net(_start):
                return {}

            @staticmethod
            def intraday_product_net(_start):
                return {}

            @staticmethod
            def selected_open_risk(_now=None):
                return {}

        service = MultiSourceLiveService.__new__(MultiSourceLiveService)
        service.universe_frame = discovered.copy()
        service.pool_build_as_of = utc_now()
        service.routed_clients = {}
        service.clients = {}
        service.sleeve_states = {}
        service.copy_book = IndependentCopyBook()
        service.portfolio = MultiSourcePortfolio({})
        service.current_targets = {}
        service.db = FakeDatabase()
        service.mt = SimpleNamespace(
            configure_symbols=lambda products: {key: {} for key in products},
            account=lambda: SimpleNamespace(equity=10_000.0),
        )
        service.scheduler_state = SchedulerState()
        service.coverage = {}
        service._initialize_client_copy_risk = lambda _equity: None
        service._publish_hourly_pool = lambda _pool: None
        service.log = lambda *_args: None
        with TemporaryDirectory() as temporary:
            service.coverage_path = Path(temporary) / "coverage.json"
            service.run_hourly_discovery()

        self.assertEqual(len(service.routed_clients), 10)
        self.assertEqual(len(service.sleeve_states), 10)
        inactive = service.pool_frame.loc[
            ~service.pool_frame["daily_activity_eligible"]
        ].iloc[0]
        self.assertEqual(float(inactive["live_base_weight"]), 0.0)
        self.assertEqual(
            service.sleeve_states[str(inactive["sleeve_key"])].day_start_base_weight,
            0.0,
        )
        self.assertIsNotNone(service.scheduler_state.last_discovery_at)
        self.assertEqual(service.copy_book.legacy_source_positions, set())


if __name__ == "__main__":
    unittest.main()
