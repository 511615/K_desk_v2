from __future__ import annotations

import argparse
import json
import math
import signal
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import MetaTrader5 as mt5

from copy_independent_execution import (
    ClientCopyRisk,
    DemoChildTicket,
    IndependentCopyBook,
    IndependentCopyPosition,
    loss_budget_multiplier,
    quantize_lots,
    slow_weight_increase,
    source_position_key,
)
from copy_dynamic_pool_domain import (
    PoolTier,
    RankingCandidate,
    SchedulerState,
    SleeveDynamicState,
    acknowledge_accepted_pool_build,
    advance_expiry_recovery,
    advance_shadow_state,
    allowed_signal_delay_seconds,
    build_rank_universe,
    daily_rebuild,
    is_signal_expired,
    mark_scheduler_run,
    record_expired_signal,
    reduce_effective_weight,
    scheduler_due,
    update_rank_state,
)
from copy_pool_multisource import (
    ROUTES,
    TOTAL_CLIENT_BUDGET,
    MultiSourceDatabase,
    MultiSourcePortfolio,
    RoutedClient,
    RoutedEvent,
    SourceCursor,
    require_nonempty_monitor_population,
    sleeve_key,
    validate_complete_coverage,
)
from copy_pool_factor_service import CopyPoolFactorService
from copy_quote_replay_cache import QuoteReplayCache
from mt5_quote_partition_provider import Mt5QuotePartitionProvider, TerminalBoundMt5Api
from copy_product_catalog import (
    default_roundtrip_spread_usd_per_lot,
    normalize_source_product,
    product_spec,
    stress_move_fraction,
)
from copy_trading_live_core import (
    drawdown_throttle,
    filetime_to_datetime,
    friday_policy,
    guarded_execution_target,
    hysteresis_target,
    server_time_from_utc,
)
from copy_trading_live_demo import (
    ALLOWED_SYMBOL,
    ALLOWED_SERVER,
    BEIJING,
    COOLDOWN_SECONDS,
    DB_FLATTEN_SECONDS,
    DB_OPEN_BLOCK_SECONDS,
    LATENCY_GATE_WINDOW,
    MIN_LATENCY_GATE_SAMPLES,
    QUOTE_MAX_AGE_SECONDS,
    RECONCILE_SECONDS,
    RECOVERY_SHADOW_SECONDS,
    RISK_PROFILES,
    SPREAD_CAP_PRICE,
    LiveService,
    append_csv,
    atomic_json,
    beijing_now,
    csv_data_rows,
    percentile_95,
    trading_day_key,
    trading_day_start_utc,
    utc_now,
)


INTRADAY_REFRESH_SECONDS = 10.0
CLIENT_RISK_REFRESH_SECONDS = 10.0
REBUILD_RETRY_SECONDS = 60.0
CLIENT_PAUSE_SECONDS = 2 * 60 * 60
CLIENT_RECOVERY_SHADOW_SECONDS = 15 * 60
SOURCE_ADD_LIMIT_SECONDS = 12 * 60 * 60
SOURCE_CLOSE_LIMIT_SECONDS = 24 * 60 * 60
PORTFOLIO_MARGIN_SOFT_FRACTION = 0.15
PORTFOLIO_MARGIN_HARD_FRACTION = 0.25
PORTFOLIO_CLUSTER_RISK_FRACTION = 0.40
PORTFOLIO_CLIENT_RISK_FRACTION = 0.20
HOURLY_EVIDENCE_COLUMNS = {
    "hourly_score",
    "current_comprehensive_net_20d_usd",
    "hourly_hard_eligible",
    "hourly_activity_eligible",
}
UNKNOWN_HOURLY_PUBLIC_COLUMNS = HOURLY_EVIDENCE_COLUMNS | {
    "recent_net_1h_usd",
    "recent_net_4h_usd",
}


def has_complete_hourly_evidence(pool: pd.DataFrame) -> bool:
    return (
        HOURLY_EVIDENCE_COLUMNS.issubset(pool.columns)
        and not pool[list(HOURLY_EVIDENCE_COLUMNS)].isna().to_numpy().any()
    )


def pool_build_day_key(now: datetime) -> str:
    local = now.astimezone(BEIJING)
    build_date = local.date()
    if (local.hour, local.minute) < (5, 15):
        build_date -= timedelta(days=1)
    return build_date.isoformat()


class MultiSourceLiveService(LiveService):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(args)
        quote_provider = Mt5QuotePartitionProvider(
            TerminalBoundMt5Api(mt5, args.terminal),
            copy_ticks_all=int(mt5.COPY_TICKS_ALL),
        )
        factor_service = CopyPoolFactorService(
            QuoteReplayCache(self.output_dir / "quote_replay_cache", quote_provider),
            warm_missing_quote_partitions=True,
            historical_delay_enabled=False,
        )
        self.db = MultiSourceDatabase(factor_service=factor_service)
        self.routed_clients: dict[str, RoutedClient] = {}
        self.portfolio: MultiSourcePortfolio | None = None
        self.coverage: dict[str, Any] = {}
        self.coverage_path = self.output_dir / "source_coverage.json"
        self.universe_path = self.output_dir / "pool_universe_private.csv"
        self.pool_snapshot_path = self.output_dir / "pool_snapshot_private.csv"
        self.pool_build_meta_path = self.output_dir / "pool_build_meta_private.json"
        self.last_intraday_refresh = 0.0
        self.last_rebuild_attempt = 0.0
        self.last_discovery_attempt = 0.0
        self.poll_latencies: list[float] = []
        self.signal_latencies: list[float] = []
        self.pending_source_snapshot: dict[tuple[str, int, str], float] | None = None
        self.current_targets: dict[str, float] = {}
        self.product_execution: dict[str, dict[str, Any]] = {}
        self.product_order_counter: dict[str, int] = {}
        self.copy_book = IndependentCopyBook()
        self.copy_recovery_shadow_started = 0.0
        self.last_client_risk_refresh = 0.0
        self.sleeve_states: dict[str, SleeveDynamicState] = {}
        self.scheduler_state = SchedulerState()
        self.sleeve_rows: dict[str, dict[str, Any]] = {}
        self.pool_was_rebuilt = False

    def load_pool(self, force_rebuild: bool = False) -> None:
        pool: pd.DataFrame
        coverage: dict[str, Any]
        cache_valid = False
        accepted_build_day: str | None = None
        if not force_rebuild and self.pool_snapshot_path.exists() and self.pool_build_meta_path.exists() and self.coverage_path.exists():
            try:
                meta = json.loads(self.pool_build_meta_path.read_text(encoding="utf-8"))
                coverage = json.loads(self.coverage_path.read_text(encoding="utf-8"))
                cache_valid = (
                        meta.get("producer") == "copy-pool-multisource-v6-weight-fallback"
                    and meta.get("pool_build_day") == pool_build_day_key(utc_now())
                    and int(meta.get("logical_routes", 0)) == len(ROUTES)
                    and int(meta.get("physical_sources", 0)) == len(self.db.sources)
                    and int(coverage.get("logical_routes_scanned", 0)) == len(ROUTES)
                )
                if cache_valid:
                    validate_complete_coverage(coverage, self.db.sources)
                    pool = pd.read_csv(self.pool_snapshot_path)
                    accepted_build_day = str(meta.get("pool_build_day") or "") or None
                    required = {
                        "account_key", "Login", "route_key", "physical_key", "live_base_weight",
                        "floating_pnl_usd", "floating_loss_ratio", "open_position_count",
                        "product", "product_floating_pnl_usd", "comprehensive_net_20d_usd",
                        "factor_ready", "factor_base_score", "factor_gate_reasons",
                        "delay_score", "mdd_20d", "mdd_60d", "holding_path_complete",
                        "pool_tier", "conservative_break_even_ms",
                        "historical_delay_enabled", "delay_factor_status",
                    }
                    if pool.empty or not required.issubset(pool.columns):
                        cache_valid = False
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                cache_valid = False
        if cache_valid:
            try:
                universe = pd.read_csv(self.universe_path)
                universe_required = {
                    "account_key", "Login", "product", "sleeve_key",
                    "factor_ready", "factor_base_score", "activity_eligible",
                }
                if universe.empty or not universe_required.issubset(universe.columns):
                    cache_valid = False
            except (OSError, ValueError, TypeError):
                cache_valid = False
        if cache_valid:
            self.pool_was_rebuilt = False
            self.log("Restored the current trading day's accepted all-source pool snapshot.")
        else:
            pool, universe, coverage = self.db.build_pool()
            self.pool_was_rebuilt = True
            validate_complete_coverage(coverage, self.db.sources)
            accepted_build_day = pool_build_day_key(utc_now())
            pool.to_csv(self.pool_snapshot_path, index=False, encoding="utf-8")
            universe.to_csv(self.universe_path, index=False, encoding="utf-8-sig")
            atomic_json(
                self.pool_build_meta_path,
                {
                    "producer": "copy-pool-multisource-v6-weight-fallback",
                    "factor_schema": "execution-quality-v1",
                    "pool_build_day": accepted_build_day,
                    "logical_routes": len(ROUTES),
                    "physical_sources": len(self.db.sources),
                    "built_at": beijing_now().isoformat(),
                    "build_as_of": str(coverage.get("as_of") or beijing_now().isoformat()),
                },
            )
        routed = self.db.selected_clients(pool)
        require_nonempty_monitor_population(
            len(routed), context="after the all-source gates"
        )
        self.routed_clients = routed
        self.pool_build_day = accepted_build_day
        self.clients = {key: client.spec for key, client in routed.items()}  # type: ignore[assignment]
        self.pool_frame = pool
        self.universe_frame = universe
        self.pool_hourly_evidence_ready = has_complete_hourly_evidence(pool)
        build_as_of_text = str(
            (meta if cache_valid else {}).get("build_as_of")
            if cache_valid else coverage.get("as_of")
        )
        try:
            self.pool_build_as_of = datetime.fromisoformat(build_as_of_text)
        except (TypeError, ValueError):
            self.pool_build_as_of = utc_now()
        if self.pool_build_as_of.tzinfo is None:
            self.pool_build_as_of = self.pool_build_as_of.replace(tzinfo=BEIJING)
        self.sleeve_rows = {
            str(row.sleeve_key): row._asdict() for row in pool.itertuples(index=False)
        }
        self.coverage = coverage
        self.db.set_clients(routed)
        self.current_targets = {
            product: self.current_targets.get(product, 0.0)
            for client in routed.values()
            for product in client.products
        }

        public_columns = [
            "client_alias", "Login", "route_key", "platform", "server", "physical_key",
            "product", "demo_symbol", "sleeve_key",
            "dynamic_score", "adjusted_score", "is_abook", "median_hold_seconds",
            "monitor_score", "hold_p25_seconds", "hold_p90_seconds",
            "short_trade_ratio", "holding_samples", "activity_eligible", "pool_status",
            "daily_activity_eligible",
            "pool_tier", "factor_ready", "factor_base_score", "factor_gate_reasons",
            "hourly_score", "recent_net_1h_usd", "recent_net_4h_usd",
            "current_comprehensive_net_20d_usd", "hourly_hard_eligible",
            "hourly_activity_eligible",
            "factor_risk_adjusted_return_5d", "factor_risk_adjusted_return_20d",
            "factor_spread_stress_return", "factor_pf_quality", "factor_delay_score",
            "factor_return_to_drawdown", "factor_holding_quality",
            "historical_delay_enabled", "delay_factor_status",
            "delay_score", "entry_p95_ms", "exit_p95_ms", "entry_break_even_ms",
            "exit_break_even_ms", "combined_break_even_ms", "conservative_break_even_ms",
            "delay_profit_retention", "delay_executable_ratio",
            "mdd_20d", "mdd_60d", "current_drawdown", "max_daily_loss",
            "equity_coverage_20d", "equity_coverage_60d", "intraday_equity_complete",
            "holding_path_complete", "overnight_ratio", "weekend_ratio", "swap_drag",
            "long_loss_ratio", "loss_addition_ratio",
            "hold_multiplier", "live_base_weight", "equity_pre_usd", "money_scale",
            "customer_base_weight", "product_budget_weight", "portfolio_base_weight",
            "ret_5d", "ret_20d", "stress_ret_20d", "pf_20d", "closes_20d",
            "quality_net_5d_usd", "quality_net_20d_usd", "floating_pnl_usd",
            "net_5d_usd", "net_20d_usd", "product_floating_pnl_usd",
            "comprehensive_net_5d_usd", "comprehensive_net_20d_usd",
            "floating_loss_ratio", "margin_to_equity", "open_position_count",
            "open_gross_lots", "xau_gross_lots", "xau_net_lots", "xau_hedge_ratio",
            "product_open_position_count", "product_open_gross_lots", "product_open_net_lots",
            "product_oldest_open_seconds", "product_hedge_ratio",
            "oldest_open_seconds", "floating_risk_multiplier", "margin_risk_multiplier",
            "hedge_risk_multiplier", "open_risk_multiplier",
        ]
        self.public_pool_columns = public_columns
        for column in public_columns:
            if column not in pool.columns:
                pool[column] = "" if column in {
                    "factor_gate_reasons", "pool_status", "pool_tier",
                } | UNKNOWN_HOURLY_PUBLIC_COLUMNS else 0.0
        pool[public_columns].to_csv(self.pool_path, index=False, encoding="utf-8-sig")
        atomic_json(self.coverage_path, coverage)
        atomic_json(
            self.private_routes_path,
            {
                "generated_at": beijing_now().isoformat(),
                "logical_routes": len(ROUTES),
                "clients": [
                    {
                        "alias": client.spec.alias,
                        "account_key": client.account_key,
                        "login": client.login,
                        "platform": client.platform,
                        "server": client.server,
                        "route_key": client.route_key,
                        "physical_key": client.physical_key,
                        "products": sorted(client.products),
                    }
                    for client in routed.values()
                ],
            },
        )
        selected_routes = len({client.route_key for client in routed.values()})
        selected_sources = len({client.physical_key for client in routed.values()})
        self.log(
            f"Loaded {len(routed)} clients from {selected_routes} logical routes and "
            f"{selected_sources} physical sources; all {len(ROUTES)} routes were scanned."
        )

    def _hourly_aliases(self, pool: pd.DataFrame) -> dict[str, str]:
        aliases = {
            key: client.spec.alias for key, client in self.routed_clients.items()
        }
        used = set(aliases.values())
        next_alias = 1
        for account in sorted(str(value) for value in pool["account_key"].unique()):
            if account in aliases:
                continue
            while f"C{next_alias:03d}" in used and next_alias <= 999:
                next_alias += 1
            if next_alias > 999:
                raise RuntimeError("Hourly discovery exhausted the C001-C999 alias namespace.")
            alias = f"C{next_alias:03d}"
            aliases[account] = alias
            used.add(alias)
        return aliases

    def _publish_hourly_pool(self, pool: pd.DataFrame) -> None:
        for column in self.public_pool_columns:
            if column not in pool.columns:
                pool[column] = "" if column in {
                    "client_alias", "route_key", "platform", "server", "physical_key",
                    "product", "demo_symbol", "sleeve_key", "factor_gate_reasons",
                    "pool_status", "pool_tier",
                } | UNKNOWN_HOURLY_PUBLIC_COLUMNS else 0.0
        pool.to_csv(self.pool_snapshot_path, index=False, encoding="utf-8")
        pool[self.public_pool_columns].to_csv(
            self.pool_path, index=False, encoding="utf-8-sig"
        )
        atomic_json(
            self.private_routes_path,
            {
                "generated_at": beijing_now().isoformat(),
                "logical_routes": len(ROUTES),
                "clients": [
                    {
                        "alias": client.spec.alias,
                        "account_key": client.account_key,
                        "login": client.login,
                        "platform": client.platform,
                        "server": client.server,
                        "route_key": client.route_key,
                        "physical_key": client.physical_key,
                        "products": sorted(client.products),
                    }
                    for client in self.routed_clients.values()
                ],
            },
        )

    def run_hourly_discovery(self) -> None:
        if self.universe_frame.empty:
            raise RuntimeError("Hourly discovery requires the accepted daily universe cache.")
        now = utc_now()
        discovered, metadata = self.db.refresh_hourly_universe(
            self.universe_frame,
            build_as_of=self.pool_build_as_of,
            as_of=now,
        )
        if discovered["account_key"].nunique() < 10:
            raise RuntimeError("Hourly discovery returned fewer than ten qualified accounts.")
        aliases = self._hourly_aliases(discovered)
        discovered["client_alias"] = discovered["account_key"].astype(str).map(aliases)
        discovered["daily_activity_eligible"] = discovered.get(
            "hourly_activity_eligible", discovered["activity_eligible"]
        ).fillna(False).astype(bool)
        sleeve_counts = discovered.groupby("account_key")["sleeve_key"].transform("count")
        reference_weights = sleeve_counts.map(
            lambda count: min(0.015, 0.03 / max(float(count), 1.0))
        )
        discovered["live_base_weight"] = [
            self.sleeve_states[key].day_start_base_weight
            if key in self.sleeve_states
            else (float(reference) if bool(activity_eligible) else 0.0)
            for key, reference, activity_eligible in zip(
                discovered["sleeve_key"],
                reference_weights,
                discovered["daily_activity_eligible"],
            )
        ]
        for column, default in (
            ("customer_base_weight", 0.0),
            ("product_budget_weight", 0.0),
            ("portfolio_base_weight", 0.0),
        ):
            if column not in discovered:
                discovered[column] = default
        discovered["portfolio_base_weight"] = discovered["live_base_weight"]

        new_clients = self.db.selected_clients(discovered)
        retiring_accounts = {
            account
            for account in self.routed_clients
            if account not in new_clients
            and bool(self.copy_book.positions_for_client(account))
        }
        merged_clients = dict(new_clients)
        for account in retiring_accounts:
            merged_clients[account] = self.routed_clients[account]

        selected_sleeves = set(discovered["sleeve_key"].astype(str))
        for key, state in list(self.sleeve_states.items()):
            if key not in selected_sleeves:
                self.sleeve_states[key] = replace(
                    state, tier=PoolTier.HARD_REJECTED, effective_weight=0.0
                )
        for row in discovered.itertuples():
            key = str(row.sleeve_key)
            self.sleeve_states.setdefault(
                key,
                SleeveDynamicState(
                    day_start_base_weight=max(0.0, float(row.live_base_weight)),
                    tier=PoolTier.MONITOR,
                ),
            )

        self.routed_clients = merged_clients
        self.clients = {key: client.spec for key, client in merged_clients.items()}  # type: ignore[assignment]
        assert self.portfolio is not None
        self.portfolio.clients = merged_clients
        self.portfolio.__post_init__()
        self.db.set_clients(merged_clients)
        for source_key, highwater in self.db.highwaters().items():
            self.portfolio.cursors.setdefault(source_key, highwater)
        current_positions = self.db.all_positions()
        self.portfolio.replace_positions(current_positions)
        self.copy_book.mark_bootstrap_positions([
            {**row, "product": normalize_source_product(row.get("symbol"))}
            for row in current_positions
            if normalize_source_product(row.get("symbol")) is not None
        ])
        self.pool_frame = discovered
        self.sleeve_rows = {
            str(row.sleeve_key): row._asdict()
            for row in discovered.itertuples(index=False)
        }
        self.current_targets = {
            product: self.current_targets.get(product, 0.0)
            for client in merged_clients.values()
            for product in client.products
        }
        self.product_execution = self.mt.configure_symbols(self.current_targets)
        self._initialize_client_copy_risk(float(self.mt.account().equity))
        self.portfolio.set_intraday_net(
            self.db.intraday_net(trading_day_start_utc(now))
        )
        self.portfolio.set_intraday_product_net(
            self.db.intraday_product_net(trading_day_start_utc(now))
        )
        self.portfolio.set_open_risk(self.db.selected_open_risk(now))
        self.coverage["hourly_discovery"] = metadata
        atomic_json(self.coverage_path, self.coverage)
        self._publish_hourly_pool(discovered)
        self.scheduler_state = mark_scheduler_run(
            self.scheduler_state, now, discovery=True
        )
        self.log(
            f"Hourly discovery refreshed {metadata['factor_ready_sleeves_scanned']} "
            f"factor-ready sleeves into {metadata['monitor_accounts']} monitor and "
            f"{metadata['reserve_accounts']} reserve accounts."
        )

    def bootstrap(self) -> None:
        saved: dict[str, Any] = {}
        restored: dict[str, SourceCursor] = {}
        if self.private_state_path.exists():
            try:
                saved = json.loads(self.private_state_path.read_text(encoding="utf-8"))
                restored = {
                    str(key): SourceCursor(
                        int(value.get("timestamp", 0)), int(value.get("sequence", 0))
                    )
                    for key, value in (saved.get("cursors") or {}).items()
                }
                self.log("Restored per-source cursors; live source positions remain authoritative.")
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.log(f"Private state could not be restored and will be rebuilt: {exc}")

        restored_sleeves = saved.get("sleeve_dynamic") if isinstance(saved, Mapping) else None
        restored_scheduler = saved.get("scheduler") if isinstance(saved, Mapping) else None
        self.sleeve_states = {}
        pool_frame = getattr(self, "pool_frame", pd.DataFrame())
        for row in pool_frame.itertuples():
            key = str(row.sleeve_key)
            state: SleeveDynamicState | None = None
            if isinstance(restored_sleeves, Mapping) and isinstance(restored_sleeves.get(key), dict):
                try:
                    state = SleeveDynamicState.from_dict(restored_sleeves[key])
                except (TypeError, ValueError, KeyError):
                    state = None
            if state is None:
                state = SleeveDynamicState(
                    day_start_base_weight=max(0.0, float(row.live_base_weight)),
                    effective_weight=0.0,
                    tier=PoolTier.MONITOR,
                )
            elif (
                getattr(self, "pool_was_rebuilt", False)
                or saved.get("trading_day") != trading_day_key(utc_now())
            ):
                state = daily_rebuild(
                    state,
                    max(0.0, float(row.live_base_weight)),
                    0.0,
                    hard_eligible=bool(row.factor_ready),
                )
            self.sleeve_states[key] = state
        if isinstance(restored_scheduler, dict):
            try:
                self.scheduler_state = SchedulerState.from_dict(restored_scheduler)
            except (TypeError, ValueError):
                self.scheduler_state = SchedulerState()
        else:
            self.scheduler_state = SchedulerState()
        if not getattr(self, "pool_hourly_evidence_ready", False):
            self.scheduler_state = replace(
                self.scheduler_state, last_discovery_at=None
            )
        if getattr(self, "pool_build_day", None):
            self.scheduler_state = acknowledge_accepted_pool_build(
                self.scheduler_state, str(self.pool_build_day)
            )

        highwaters = self.db.highwaters()
        rows = self.db.all_positions()
        open_risk = self.db.selected_open_risk()
        self.copy_book = (
            IndependentCopyBook()
            if getattr(self, "pool_was_rebuilt", False)
            else IndependentCopyBook.from_private(saved.get("independent_copy"))
        )
        self.portfolio = MultiSourcePortfolio(self.routed_clients)
        self.portfolio.replace_positions(rows)
        self.copy_book.mark_bootstrap_positions([
            {
                **row,
                "product": normalize_source_product(row.get("symbol")),
            }
            for row in rows
            if normalize_source_product(row.get("symbol")) is not None
        ])
        for source_key, highwater in highwaters.items():
            old = restored.get(source_key, SourceCursor())
            if old > highwater:
                self.log(f"Saved cursor for {source_key} was ahead of its database; current high-water wins.")
            self.portfolio.cursors[source_key] = highwater
        self.portfolio.set_intraday_net(self.db.intraday_net(trading_day_start_utc(utc_now())))
        product_net_reader = getattr(self.db, "intraday_product_net", None)
        current_product_net = (
            product_net_reader(trading_day_start_utc(utc_now()))
            if callable(product_net_reader)
            else {}
        )
        self.portfolio.set_intraday_product_net(current_product_net)
        self.portfolio.set_open_risk(open_risk)
        current_day = trading_day_key(utc_now())
        saved_is_current = (
            saved.get("risk_profile") == self.profile.name
            and saved.get("trading_day") == current_day
        )
        if not saved_is_current:
            self.copy_book.prune_closed()
        saved_baseline = saved.get("intraday_product_baseline_usd", {})
        self.portfolio.set_intraday_product_baseline(
            saved_baseline
            if saved_is_current and isinstance(saved_baseline, Mapping)
            else current_product_net
        )
        saved_product_delta = saved.get("product_realized_delta_usd", {})
        if (
            saved_is_current
            and isinstance(saved_product_delta, Mapping)
        ):
            for key in self.portfolio.product_realized_delta_usd:
                self.portfolio.product_realized_delta_usd[key] = float(saved_product_delta.get(key, 0.0))
            for account_key_value in self.routed_clients:
                self.portfolio._update_weight(account_key_value)

        account = self.mt.account()
        if (
            self.profile.minimum_start_balance_usd is not None
            and float(account.balance) < self.profile.minimum_start_balance_usd
        ):
            raise RuntimeError(
                f"{self.profile.name} requires at least "
                f"{self.profile.minimum_start_balance_usd:.2f} USD balance."
            )
        if saved.get("risk_profile") == self.profile.name and saved.get("trading_day") == current_day:
            self.cycle_baseline_pnl = float(saved.get("cycle_baseline_pnl", 0.0))
            self.cycle_reference_equity = float(saved.get("cycle_reference_equity", account.equity))
            self.daily_reference_equity = float(saved.get("daily_reference_equity", account.equity))
            self.daily_hard_stop = bool(saved.get("daily_hard_stop", False))
            cooldown_text = saved.get("cooldown_until")
            self.cooldown_until = datetime.fromisoformat(cooldown_text) if cooldown_text else None
        else:
            self.cycle_baseline_pnl = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
            self.cycle_reference_equity = float(account.equity)
            self.daily_reference_equity = float(account.equity)
            self.daily_hard_stop = False
            self.cooldown_until = None
        self._initialize_client_copy_risk(float(account.equity))
        self._validate_copy_ticket_mapping()
        if any(client.products for client in self.routed_clients.values()):
            if not hasattr(self, "current_targets"):
                self.current_targets = {
                    product: 0.0
                    for client in self.routed_clients.values()
                    for product in client.products
                }
            self._refresh_targets()
        else:
            raw, _long, _short = self.portfolio.target(ALLOWED_SYMBOL, float(account.equity))
            marked = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
            self.current_target = self.target_for_raw(
                raw, 0.0, marked - self.cycle_baseline_pnl
            )
        self.last_db_success = time.monotonic()
        self.phase = "shadow" if self.args.mode != "Live" else "live"
        self.shadow_started = time.monotonic()
        if self.daily_hard_stop:
            self.phase = "daily_stop"
        elif self.cooldown_until is not None and utc_now() < self.cooldown_until:
            self.phase = "cooldown"
        elif self.cooldown_until is not None:
            self.phase = "recovery_shadow"
            self.required_shadow_seconds = RECOVERY_SHADOW_SECONDS
        self.last_pool_reload_day = current_day
        self.reconcile_streak = 0
        self.pending_source_snapshot = None
        self.pending_source_snapshot_count = 0
        self.persist_private_state()

    def _initialize_client_copy_risk(self, equity_usd: float) -> None:
        prior = self.copy_book.clients
        rebuilt: dict[str, ClientCopyRisk] = {}
        total_budget = max(float(equity_usd), 1.0) * 0.015
        for key, client in self.routed_clients.items():
            base_weight = sum(
                spec.base_weight
                for spec in client.products.values()
                if spec.activity_eligible
            )
            old = prior.get(key)
            rebuilt[key] = ClientCopyRisk(
                account_key=key,
                client_alias=client.spec.alias,
                base_weight=base_weight,
                effective_weight=(
                    min(base_weight, max(0.0, old.effective_weight))
                    if old else base_weight
                ),
                loss_budget_usd=(
                    total_budget * min(base_weight, PORTFOLIO_CLIENT_RISK_FRACTION)
                ),
                realized_pnl_usd=old.realized_pnl_usd if old else 0.0,
                floating_pnl_usd=old.floating_pnl_usd if old else 0.0,
                cycle_baseline_pnl_usd=(
                    old.cycle_baseline_pnl_usd if old else 0.0
                ),
                pause_until=old.pause_until if old else None,
                recovery_shadow_until=old.recovery_shadow_until if old else None,
                last_weight_update_at=old.last_weight_update_at if old else None,
                status=old.status if old else ("active" if base_weight > 0 else "monitor"),
                reduction_reason=old.reduction_reason if old else "",
            )
        self.copy_book.clients = rebuilt

    def _close_client_copies(self, account_key: str, reason: str) -> None:
        for position in self.copy_book.positions_for_client(account_key):
            position.copy_eligible = False
            if position.children:
                self._close_position_to(position, 0.0, reason)
                position.status = "paused"
                position.reject_reason = reason

    def _refresh_independent_client_risk(self, *, force: bool = False) -> None:
        now_monotonic = time.monotonic()
        if (
            not force
            and now_monotonic - self.last_client_risk_refresh
            < CLIENT_RISK_REFRESH_SECONDS
        ):
            return
        pnl_reader = getattr(self.mt, "pnl_by_comment", None)
        pnl_rows = (
            pnl_reader(trading_day_start_utc(utc_now()))
            if callable(pnl_reader)
            else {}
        )
        now = utc_now()
        for account_key, risk in self.copy_book.clients.items():
            realized = 0.0
            floating = 0.0
            for position in self.copy_book.positions_for_client(account_key):
                values = pnl_rows.get(position.comment, {})
                realized += float(values.get("realized", 0.0))
                floating += float(values.get("floating", 0.0))
            risk.realized_pnl_usd = realized
            risk.floating_pnl_usd = floating

            if risk.is_paused(now):
                risk.effective_weight = 0.0
                risk.status = "paused"
                risk.reduction_reason = "客户复制亏损冷却中"
            elif risk.pause_until:
                risk.pause_until = None
                risk.cycle_baseline_pnl_usd = realized + floating
                risk.recovery_shadow_until = (
                    now + timedelta(seconds=CLIENT_RECOVERY_SHADOW_SECONDS)
                ).isoformat()
                risk.effective_weight = 0.0
                risk.status = "recovery_shadow"
                risk.reduction_reason = "恢复前影子观察15分钟"
            elif risk.is_recovery_shadow(now):
                risk.effective_weight = 0.0
                risk.status = "recovery_shadow"
                risk.reduction_reason = "恢复前影子观察15分钟"
            elif risk.loss_usage >= 1.0:
                risk.effective_weight = 0.0
                risk.status = "paused"
                risk.reduction_reason = "客户复制亏损额度已用尽"
                risk.pause_until = (now + timedelta(seconds=CLIENT_PAUSE_SECONDS)).isoformat()
                risk.recovery_shadow_until = None
                self._close_client_copies(account_key, "client_loss_budget")
            else:
                if risk.recovery_shadow_until:
                    risk.recovery_shadow_until = None
                target = risk.base_weight * loss_budget_multiplier(risk.loss_usage)
                last = now
                if risk.last_weight_update_at:
                    try:
                        last = datetime.fromisoformat(risk.last_weight_update_at)
                    except ValueError:
                        last = now
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                elapsed_minutes = max(0.0, (now - last).total_seconds() / 60.0)
                if target <= risk.effective_weight:
                    risk.effective_weight = target
                elif risk.base_weight > 0:
                    current_ratio = risk.effective_weight / risk.base_weight
                    target_ratio = target / risk.base_weight
                    risk.effective_weight = risk.base_weight * slow_weight_increase(
                        current_ratio, target_ratio, elapsed_minutes
                    )
                risk.status = "reduced" if risk.effective_weight < risk.base_weight - 1e-12 else "active"
                risk.reduction_reason = (
                    f"客户亏损额度使用 {risk.loss_usage:.1%}"
                    if risk.status == "reduced" else ""
                )
            risk.last_weight_update_at = now.isoformat()
        self.last_client_risk_refresh = now_monotonic

    def reconcile_independent_copies(self, *, allow_increase: bool = False) -> None:
        self._validate_copy_ticket_mapping()
        timed_out_clients = {
            position.account_key
            for position in self.copy_book.positions.values()
            if position.children
            and self._position_hold_seconds(position) >= SOURCE_CLOSE_LIMIT_SECONDS
        }
        for account_key in timed_out_clients:
            risk = self.copy_book.clients.get(account_key)
            if risk is not None:
                risk.effective_weight = 0.0
                risk.status = "paused"
                risk.reduction_reason = "来源持仓超过24小时"
                risk.pause_until = (
                    utc_now() + timedelta(seconds=CLIENT_PAUSE_SECONDS)
                ).isoformat()
            self._close_client_copies(account_key, "source_position_over_24h")
        for position in list(self.copy_book.positions.values()):
            self._sync_independent_position(
                position,
                "INDEPENDENT_RECONCILE",
                allow_increase=allow_increase and position.copy_eligible,
            )

    def _validate_copy_ticket_mapping(self) -> None:
        position_reader = getattr(self.mt, "all_strategy_positions", None)
        actual = {
            int(position.ticket): position
            for position in (position_reader() if callable(position_reader) else ())
        }
        owners = self.copy_book.ticket_owners()
        unknown = sorted(set(actual) - set(owners))
        missing = sorted(set(owners) - set(actual))
        if unknown or missing:
            raise RuntimeError(
                "Independent copy-ticket mapping mismatch: "
                f"unknown_demo={unknown[:10]}, missing_demo={missing[:10]}"
            )
        for position in self.copy_book.positions.values():
            copied = 0.0
            for child in position.children:
                live = actual[child.ticket]
                child.lots = float(live.volume)
                child.open_price = float(live.price_open)
                copied += child.lots
            position.copied_lots = copied

    def _live_positions(self) -> tuple[Any, ...]:
        reader = getattr(self.mt, "all_strategy_positions", None)
        return tuple(reader() if callable(reader) else ())

    def _sync_book_children(self, position: IndependentCopyPosition) -> None:
        reader = getattr(self.mt, "strategy_positions_by_comment", None)
        rows = tuple(reader(position.comment, position.product) if callable(reader) else ())
        children: list[DemoChildTicket] = []
        for row in rows:
            opened = ""
            if getattr(row, "time", None) is not None:
                opened = datetime.fromtimestamp(
                    float(row.time), tz=timezone.utc
                ).isoformat()
            children.append(DemoChildTicket(
                ticket=int(row.ticket),
                lots=float(row.volume),
                side=1 if int(row.type) == 0 else -1,
                open_time=opened,
                open_price=float(getattr(row, "price_open", 0.0) or 0.0),
            ))
        position.children = sorted(children, key=lambda child: (child.open_time, child.ticket))
        position.copied_lots = sum(child.lots for child in position.children)

    def _position_hold_seconds(self, position: IndependentCopyPosition) -> float:
        value = position.source_opened_at or position.first_signal_at
        if not value:
            return 0.0
        try:
            opened = datetime.fromisoformat(value)
        except ValueError:
            return 0.0
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return max(0.0, (utc_now() - opened).total_seconds())

    def _client_risk_multiplier(self, account_key: str) -> float:
        copy_book = getattr(self, "copy_book", None)
        if copy_book is None:
            return 1.0
        risk = copy_book.clients.get(account_key)
        if risk is None or risk.base_weight <= 0:
            return 0.0
        return max(0.0, min(1.0, risk.effective_weight / risk.base_weight))

    def _effective_copy_weight(self, account_key: str, product: str) -> float:
        assert self.portfolio is not None
        client = self.routed_clients[account_key]
        spec = client.products.get(product)
        if spec is None:
            return max(
                0.0,
                self.portfolio.effective_weights.get(account_key, 0.0),
            ) * self._client_risk_multiplier(account_key)
        if not spec.activity_eligible or spec.base_weight <= 0:
            return 0.0
        source_weight = self.portfolio.effective_product_weights.get(
            sleeve_key(account_key, product), 0.0
        )
        source_multiplier = max(0.0, min(1.0, source_weight / spec.base_weight))
        state = getattr(self, "sleeve_states", {}).get(
            sleeve_key(account_key, product)
        )
        dynamic_weight = state.effective_weight if state is not None else 0.0
        return min(spec.base_weight * source_multiplier, dynamic_weight) * self._client_risk_multiplier(account_key)

    def refresh_dynamic_sleeves(self) -> None:
        now = utc_now()
        due = scheduler_due(self.scheduler_state, now)
        if due.discovery:
            if time.monotonic() - self.last_discovery_attempt >= REBUILD_RETRY_SECONDS:
                self.last_discovery_attempt = time.monotonic()
                self.run_hourly_discovery()
                now = utc_now()
                due = scheduler_due(self.scheduler_state, now)
        if due.risk:
            healthy = self.operational_gates_ready()
            for key, state in list(self.sleeve_states.items()):
                state = advance_expiry_recovery(state, now)
                if state.tier in (PoolTier.ENTRY_SHADOW, PoolTier.RECOVERY_SHADOW):
                    row = self.sleeve_rows.get(key, {})
                    state = advance_shadow_state(
                        state, now,
                        still_qualified=bool(row.get("factor_ready", False)),
                        shadow_health_ok=healthy,
                        target_weight=float(row.get("live_base_weight", 0.0) or 0.0),
                    )
                self.sleeve_states[key] = state
            self.scheduler_state = mark_scheduler_run(
                self.scheduler_state, now, risk=True
            )
        if due.rank:
            candidates: list[RankingCandidate] = []
            for key, state in list(self.sleeve_states.items()):
                row = self.sleeve_rows.get(key, {})
                account_key_value = str(row.get("account_key") or "")
                product = str(row.get("product") or "")
                if not account_key_value or not product:
                    continue
                client = self.routed_clients.get(account_key_value)
                current_product = self.portfolio.product_comprehensive_pnl_usd.get(
                    key, float(row.get("comprehensive_net_20d_usd", 0.0) or 0.0)
                ) if self.portfolio is not None else 0.0
                equity = max(float(client.spec.equity_usd), 1.0) if client else 1.0
                session_net = 0.0
                if self.portfolio is not None:
                    session_net = (
                        self.portfolio.intraday_product_net_usd.get(key, 0.0)
                        + min(self.portfolio.floating_product_pnl_usd.get(key, 0.0), 0.0)
                    )
                performance = max(0.50, min(1.10, 1.0 + 5.0 * session_net / equity))
                expiry_count = len(state.entry_expired_at) + len(state.exit_expired_at)
                execution_quality = max(0.0, 1.0 - 0.15 * expiry_count)
                score = float(
                    row.get("hourly_score", row.get("factor_base_score", 0.0)) or 0.0
                ) * performance * execution_quality
                candidate = RankingCandidate(
                    sleeve_key=key,
                    account_key=account_key_value,
                    product=product,
                    score=score,
                    hard_eligible=(
                        bool(row.get("factor_ready", False))
                        and current_product > 0.0
                    ),
                    activity_eligible=bool(
                        row.get("daily_activity_eligible", row.get("activity_eligible", False))
                    ),
                    min_lot_feasible=self._minimum_lot_feasible(
                        account_key_value, product,
                    ),
                )
                candidates.append(candidate)
            ranked = build_rank_universe(candidates)
            active_accounts = set(ranked.monitor_accounts)
            qualified_accounts = active_accounts | set(ranked.reserve_accounts)
            by_key = {candidate.sleeve_key: candidate for candidate in candidates}
            for key, state in list(self.sleeve_states.items()):
                candidate = by_key.get(key)
                if candidate is None:
                    continue
                row = self.sleeve_rows.get(key, {})
                active_zone = candidate.account_key in active_accounts
                qualified_zone = candidate.account_key in qualified_accounts
                self.sleeve_states[key] = update_rank_state(
                    state, candidate, now,
                    active_zone=active_zone,
                    qualified_zone=qualified_zone,
                    target_weight=float(row.get("live_base_weight", 0.0) or 0.0),
                )
            total_effective = sum(
                state.effective_weight for state in self.sleeve_states.values()
            )
            excess = max(0.0, total_effective - TOTAL_CLIENT_BUDGET)
            if excess > 1e-12:
                for candidate in sorted(candidates, key=lambda item: item.score):
                    state = self.sleeve_states[candidate.sleeve_key]
                    reduction = min(state.effective_weight, excess)
                    if reduction <= 0:
                        continue
                    self.sleeve_states[candidate.sleeve_key] = reduce_effective_weight(
                        state, state.effective_weight - reduction, now
                    )
                    excess -= reduction
                    if excess <= 1e-12:
                        break
            self.scheduler_state = mark_scheduler_run(
                self.scheduler_state, now, rank=True
            )

    def _minimum_lot_feasible(self, account_key: str, product: str) -> bool:
        if not account_key or not product:
            return False
        risk = self.copy_book.clients.get(account_key)
        if risk is None:
            return False
        try:
            symbol = self.mt.symbol(product)
            minimum = float(symbol.volume_min)
            stress = max(
                self.mt.stress_loss_per_lot(product, stress_move_fraction(product)),
                1.0,
            )
            margin = max(self.mt.margin_per_lot(1.0, product), 1.0)
            account = self.mt.account()
        except Exception:
            return False
        remaining_loss = max(0.0, risk.loss_budget_usd - risk.loss_used_usd)
        margin_budget = max(float(account.equity), 1.0) * PORTFOLIO_MARGIN_SOFT_FRACTION
        margin_free = max(
            0.0,
            margin_budget - max(float(getattr(account, "margin", 0.0) or 0.0), 0.0),
        )
        strict_capacity = min(remaining_loss / stress, margin_free / margin)
        if strict_capacity >= minimum - 1e-12:
            return True
        return (
            self._demo_minimum_lot_override_enabled(account)
            and minimum * stress <= max(float(account.equity), 1.0) * 0.015
            and minimum * margin <= margin_free
        )

    def _demo_minimum_lot_override_enabled(self, account: Any | None = None) -> bool:
        account = account or self.mt.account()
        return (
            bool(getattr(getattr(self, "args", None), "allow_demo_min_lot_override", False))
            and str(getattr(account, "server", "")) == ALLOWED_SERVER
            and str(getattr(self.args, "mode", "")) == "StagedLive"
        )

    def _stress_usage(
        self,
        excluded_tickets: set[int],
    ) -> tuple[float, dict[tuple[str, int], float], dict[str, float]]:
        total = 0.0
        clusters: dict[tuple[str, int], float] = {}
        clients: dict[str, float] = {}
        owners = self.copy_book.ticket_owners()
        for row in self._live_positions():
            ticket = int(row.ticket)
            if ticket in excluded_tickets:
                continue
            product = str(row.symbol)
            side = 1 if int(row.type) == 0 else -1
            stress = float(row.volume) * max(
                self.mt.stress_loss_per_lot(product, stress_move_fraction(product)), 1.0
            )
            total += stress
            clusters[(product, side)] = clusters.get((product, side), 0.0) + stress
            source_key_value = owners.get(ticket)
            if source_key_value and source_key_value in self.copy_book.positions:
                account_key = self.copy_book.positions[source_key_value].account_key
                clients[account_key] = clients.get(account_key, 0.0) + stress
        return total, clusters, clients

    def _desired_copy_lots(
        self,
        position: IndependentCopyPosition,
        *,
        allow_increase: bool,
    ) -> tuple[float, str]:
        if abs(position.source_lots) < 1e-12:
            return 0.0, "source_closed"
        client = self.routed_clients.get(position.account_key)
        risk = self.copy_book.clients.get(position.account_key)
        if client is None or risk is None or position.product not in client.products:
            return 0.0, "client_not_in_current_pool"
        spec = client.products[position.product]
        if not position.copy_eligible:
            return 0.0, "old_or_shadow_position"
        now = utc_now()
        if risk.is_paused(now):
            return 0.0, "client_loss_pause"
        if risk.is_recovery_shadow(now):
            return 0.0, "client_recovery_shadow"
        hold_seconds = self._position_hold_seconds(position)
        if hold_seconds >= SOURCE_CLOSE_LIMIT_SECONDS:
            return 0.0, "source_position_over_24h"
        weight = self._effective_copy_weight(position.account_key, position.product)
        if weight <= 0:
            return 0.0, "zero_effective_weight"
        account = self.mt.account()
        normalized_source_lots = (
            abs(position.source_lots)
            * max(spec.source_contract_size, 1e-12)
            / max(spec.demo_contract_size, 1e-12)
        )
        proportional = (
            normalized_source_lots
            * max(float(account.equity), 1.0)
            * weight
            / max(float(client.spec.equity_usd), 1.0)
        )
        symbol = self.mt.symbol(position.product)
        minimum = float(symbol.volume_min)
        step = float(symbol.volume_step)
        stress_per_lot = max(
            self.mt.stress_loss_per_lot(
                position.product, stress_move_fraction(position.product)
            ),
            1.0,
        )
        margin_per_lot = max(
            self.mt.margin_per_lot(position.side, position.product), 1.0
        )
        excluded = {child.ticket for child in position.children}
        total_stress, clusters, client_stress = self._stress_usage(excluded)
        cycle_budget = max(float(account.equity), 1.0) * 0.015
        remaining_client = max(
            0.0,
            risk.loss_budget_usd - risk.loss_used_usd
            - client_stress.get(position.account_key, 0.0),
        )
        portfolio_cap = max(0.0, cycle_budget - total_stress) / stress_per_lot
        cluster_cap = max(
            0.0,
            cycle_budget * PORTFOLIO_CLUSTER_RISK_FRACTION
            - clusters.get((position.product, position.side), 0.0),
        ) / stress_per_lot
        client_cap = remaining_client / stress_per_lot
        current_abs = abs(position.copied_signed_lots)
        available_margin = max(
            0.0,
            max(float(account.equity), 1.0) * PORTFOLIO_MARGIN_SOFT_FRACTION
            - max(float(getattr(account, "margin", 0.0) or 0.0), 0.0),
        )
        margin_cap = current_abs + available_margin / margin_per_lot
        target_abs = min(proportional, client_cap, portfolio_cap, cluster_cap, margin_cap)
        decision = "risk_allowed"
        if (
            target_abs < minimum - 1e-12
            and proportional > 0.0
            and allow_increase
            and current_abs < minimum - 1e-12
            and self._demo_minimum_lot_override_enabled(account)
            and total_stress + minimum * stress_per_lot <= cycle_budget + 1e-12
            and clusters.get((position.product, position.side), 0.0) < 1e-12
            and minimum * margin_per_lot <= available_margin + 1e-12
        ):
            target_abs = minimum
            decision = "risk_allowed_demo_minimum"
        if hold_seconds >= SOURCE_ADD_LIMIT_SECONDS:
            target_abs = min(target_abs, current_abs)
        if not allow_increase:
            target_abs = min(target_abs, current_abs)
        quantized = quantize_lots(target_abs, minimum, step)
        if quantized <= 0:
            return 0.0, "below_minimum_risk_lot"
        return math.copysign(quantized, position.source_lots), decision

    def _log_independent_order(
        self,
        position: IndependentCopyPosition,
        action: str,
        before: float,
        target: float,
        result: Any | None,
        reason: str,
    ) -> None:
        self.order_counter += 1
        bid, ask, age = self.mt.quote_state(position.product)
        append_csv(self.order_path, {
            "order_event": f"O{self.order_counter:06d}",
            "time_beijing": beijing_now().isoformat(),
            "client_alias": position.client_alias,
            "source_position_id": position.source_position_id,
            "product": position.product,
            "action": action,
            "before_lots": before,
            "target_lots": target,
            "after_lots": position.copied_signed_lots,
            "demo_tickets": "|".join(str(child.ticket) for child in position.children),
            "bid": bid,
            "ask": ask,
            "spread_price": ask - bid,
            "quote_age_seconds": age,
            "retcode": int(result.retcode) if result is not None else "",
            "comment": str(result.comment) if result is not None else reason,
        })

    def _close_position_to(
        self,
        position: IndependentCopyPosition,
        target_abs: float,
        reason: str,
    ) -> None:
        self._sync_book_children(position)
        remaining = max(0.0, position.copied_lots - target_abs)
        for child in reversed(position.children.copy()):
            if remaining <= 1e-9:
                break
            live = self.mt.position_by_ticket(child.ticket)
            if live is None:
                raise RuntimeError(f"Mapped Demo ticket {child.ticket} disappeared before close.")
            before = position.copied_signed_lots
            close_lots = min(float(live.volume), remaining)
            result = self.mt.close_position(live, close_lots)
            expected = before - math.copysign(close_lots, before)
            self.mt.wait_for_comment_position(
                position.comment, position.product, expected
            )
            self._sync_book_children(position)
            self._log_independent_order(
                position, "INDEPENDENT_REDUCE", before, expected, result, reason
            )
            remaining = max(0.0, position.copied_lots - target_abs)
        if remaining > 1e-9:
            raise RuntimeError("Unable to close the complete customer-owned Demo volume.")

    def _sync_independent_position(
        self,
        position: IndependentCopyPosition,
        reason: str,
        *,
        allow_increase: bool,
    ) -> None:
        self._sync_book_children(position)
        before = position.copied_signed_lots
        if abs(position.source_lots) < 1e-12:
            target, decision = 0.0, "source_closed"
        else:
            target, decision = self._desired_copy_lots(
                position, allow_increase=allow_increase
            )
        if before * target < -1e-12:
            self._close_position_to(position, 0.0, f"{reason}:reverse_close")
            before = 0.0
        if abs(target) < abs(before) - 1e-9 or (
            abs(target) < 1e-12 and abs(before) > 1e-12
        ):
            self._close_position_to(position, abs(target), reason)
            before = position.copied_signed_lots
        increase = abs(target) > abs(before) + 1e-9
        if increase:
            can_open = (
                allow_increase
                and not self.refresh_mt5_conflicts()
                and self.quote_allows_open(position.product)
            )
            if can_open:
                delta = target - before
                result = self.mt.open_position(
                    delta,
                    position.product,
                    hard_cap_lots=abs(delta),
                    comment=position.comment,
                )
                self.mt.wait_for_comment_position(
                    position.comment, position.product, target
                )
                self._sync_book_children(position)
                self._log_independent_order(
                    position, "INDEPENDENT_OPEN", before, target, result, reason
                )
                position.status = "active"
                position.reject_reason = ""
            else:
                position.status = "risk_rejected"
                position.reject_reason = "execution_gate_blocked"
                self.copy_book.rejected_events += 1
        elif abs(position.copied_signed_lots) < 1e-12:
            position.status = "closed" if abs(position.source_lots) < 1e-12 else "monitor"
            position.reject_reason = "" if abs(position.source_lots) < 1e-12 else decision
        else:
            position.status = "active"
            position.reject_reason = "" if decision.startswith("risk_allowed") else decision
        self.copy_book.remove_closed(position.source_key)

    def _handle_source_position_change(
        self,
        *,
        account_key: str,
        product: str,
        position_id: int,
        before_lots: float,
        after_lots: float,
        signal_time: datetime,
        reason: str,
    ) -> tuple[str, IndependentCopyPosition | None]:
        client = self.routed_clients[account_key]
        action, position = self.copy_book.observe_source_position(
            account_key,
            client.spec.alias,
            product,
            position_id,
            before_lots,
            after_lots,
            signal_time,
        )
        if position is None:
            return action, None
        if action == "open":
            state = self.sleeve_states.get(sleeve_key(account_key, product))
            position.copy_eligible = (
                self.phase == "live"
                and state is not None
                and state.tier == PoolTier.ACTIVE
            )
            if not position.copy_eligible:
                position.status = "shadow_monitor"
                position.reject_reason = "old_or_shadow_position"
        policy = friday_policy(server_time_from_utc(utc_now()))
        allow_increase = (
            self.phase == "live"
            and position.copy_eligible
            and policy == "normal"
        )
        self._sync_independent_position(
            position, reason, allow_increase=allow_increase
        )
        return action, position

    def persist_private_state(self) -> None:
        if self.portfolio is None:
            return
        atomic_json(
            self.private_state_path,
            {
                "cursors": {key: asdict(value) for key, value in self.portfolio.cursors.items()},
                "positions": [
                    {"account_key": key, "position_id": position, "product": product, "lots": lots}
                    for (key, position, product), lots in self.portfolio.positions.items()
                ],
                "intraday_net_usd": self.portfolio.intraday_net_usd,
                "intraday_product_net_usd": self.portfolio.intraday_product_net_usd,
                "intraday_product_baseline_usd": self.portfolio.intraday_product_baseline_usd,
                "product_realized_delta_usd": self.portfolio.product_realized_delta_usd,
                "floating_pnl_usd": self.portfolio.floating_pnl_usd,
                "floating_product_pnl_usd": self.portfolio.floating_product_pnl_usd,
                "dynamic_evaluation_usd": self.portfolio.dynamic_evaluation_usd,
                "product_comprehensive_pnl_usd": self.portfolio.product_comprehensive_pnl_usd,
                "open_risk_by_account": self.portfolio.open_risk_by_account,
                "effective_weights": self.portfolio.effective_weights,
                "effective_product_weights": self.portfolio.effective_product_weights,
                "sleeve_dynamic": {
                    key: state.to_dict() for key, state in self.sleeve_states.items()
                },
                "scheduler": self.scheduler_state.to_dict(),
                "independent_copy": self.copy_book.to_private(),
                "risk_profile": self.profile.name,
                "trading_day": trading_day_key(utc_now()),
                "cycle_baseline_pnl": self.cycle_baseline_pnl,
                "cycle_reference_equity": self.cycle_reference_equity,
                "daily_reference_equity": self.daily_reference_equity,
                "daily_hard_stop": self.daily_hard_stop,
                "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
                "saved_at": beijing_now().isoformat(),
            },
        )

    def public_status(self) -> dict[str, Any]:
        status = super().public_status()
        assert self.portfolio is not None
        account = self.mt.account()
        portfolio_targets = self.portfolio.targets(float(account.equity))
        actual = self.mt.signed_positions()
        execution_weights = {
            sleeve_key(key, product): self._effective_copy_weight(key, product)
            for key, client in self.routed_clients.items()
            for product in client.products
        }
        active_accounts = {
            str(self.sleeve_rows.get(key, {}).get("account_key") or "")
            for key, state in self.sleeve_states.items()
            if state.tier == PoolTier.ACTIVE
        }
        active_accounts.discard("")
        actual_exposure: dict[str, dict[str, float]] = {}
        for live_position in self._live_positions():
            product = str(live_position.symbol)
            values = actual_exposure.setdefault(product, {"long": 0.0, "short": 0.0})
            if int(live_position.type) == 0:
                values["long"] += float(live_position.volume)
            else:
                values["short"] += float(live_position.volume)
        product_rows: list[dict[str, Any]] = []
        estimated_margin = 0.0
        estimated_stress = 0.0
        for product in sorted(set(self.current_targets) | set(actual)):
            raw, gross_long, gross_short = portfolio_targets.get(product, (0.0, 0.0, 0.0))
            desired = self.current_targets.get(product, 0.0)
            try:
                bid, ask, age = self.mt.quote_state(product)
                spread = ask - bid
            except Exception:
                bid = ask = spread = 0.0
                age = float("inf")
            if abs(desired) > 1e-12:
                estimated_margin += abs(desired) * max(
                    self.mt.margin_per_lot(1.0 if desired > 0 else -1.0, product), 0.0
                )
                estimated_stress += abs(desired) * max(
                    self.mt.stress_loss_per_lot(product, stress_move_fraction(product)), 0.0
                )
            product_rows.append({
                "product": product,
                "raw_target_lots": raw,
                "desired_target_lots": desired,
                "actual_strategy_lots": actual.get(product, 0.0),
                "gross_long_lots": actual_exposure.get(product, {}).get("long", 0.0),
                "gross_short_lots": actual_exposure.get(product, {}).get("short", 0.0),
                "active_weight": sum(
                    execution_weights.get(sleeve_key(key, product), 0.0)
                    for key, client in self.routed_clients.items()
                    if product in client.products
                ),
                "bid": bid,
                "ask": ask,
                "spread_price": spread,
                "quote_age_seconds": age,
                "spread_allows_open": (
                    spread > 0
                    and spread * product_spec(product).contract_size
                    <= 1.5 * default_roundtrip_spread_usd_per_lot(product)
                ),
            })
        selected_routes = {client.route_key for client in self.routed_clients.values()}
        selected_sources = {client.physical_key for client in self.routed_clients.values()}
        status.update(
            {
                "logical_routes_scanned": int(self.coverage.get("logical_routes_scanned", 0)),
                "logical_routes_expected": len(ROUTES),
                "logical_routes_selected": len(selected_routes),
                "physical_sources_scanned": int(self.coverage.get("physical_sources_scanned", 0)),
                "physical_sources_selected": len(selected_sources),
                "selected_source_staleness_seconds": self.db.selected_source_staleness(),
                "db_poll_latency_p95_seconds": percentile_95(self.poll_latencies[-120:]),
                "signal_latency_p95_seconds": percentile_95(self.signal_latencies[-120:]),
                "source_health": self.db.health_public(),
                "symbol": "MULTI",
                "products": product_rows,
                "products_selected": len(self.current_targets),
                "products_with_target": sum(
                    1 for value in self.current_targets.values() if abs(value) > 1e-12
                ),
                "products_with_position": len(actual_exposure),
                "estimated_margin_usd": estimated_margin,
                "estimated_stress_loss_usd": estimated_stress,
                "portfolio_margin_budget_usd": float(account.equity) * PORTFOLIO_MARGIN_SOFT_FRACTION,
                "portfolio_stress_budget_usd": float(account.equity) * 0.015,
                "execution_model": "independent_customer_positions_v2",
                "demo_minimum_lot_override": self._demo_minimum_lot_override_enabled(account),
                "active_weights": sum(execution_weights.values()),
                "monitor_sleeves": len(self.pool_frame),
                "active_copy_clients": len(active_accounts),
                "risk_managed_clients": sum(
                    risk.status in {"active", "reduced"}
                    for risk in self.copy_book.clients.values()
                ),
                "independent_source_positions": len(self.copy_book.positions),
                "independent_demo_tickets": len(self.copy_book.ticket_owners()),
                "dynamic_sleeves": [
                    {
                        "sleeve_key": key,
                        "tier": state.tier.value,
                        "base_weight": state.day_start_base_weight,
                        "effective_weight": state.effective_weight,
                        "shadow_ends_at": (
                            state.shadow_ends_at.isoformat() if state.shadow_ends_at else None
                        ),
                        "entry_expired_count": len(state.entry_expired_at),
                        "exit_expired_count": len(state.exit_expired_at),
                    }
                    for key, state in sorted(self.sleeve_states.items())
                ],
                "scheduler": self.scheduler_state.to_dict(),
                "client_risks": [
                    risk.public()
                    for risk in sorted(
                        self.copy_book.clients.values(),
                        key=lambda item: item.client_alias,
                    )
                ],
                "independent_positions": [
                    position.public()
                    for position in sorted(
                        self.copy_book.positions.values(),
                        key=lambda item: (item.client_alias, item.product, item.source_position_id),
                    )
                ],
            }
        )
        status["db_seconds_since_success"] = self.db.selected_source_staleness()
        return status

    def operational_gates_ready(self) -> bool:
        return (
            self.reconcile_streak >= 3
            and self.pending_source_snapshot_count == 0
            and self.portfolio is not None
            and self.portfolio.duplicate_events == 0
            and int(self.coverage.get("logical_routes_scanned", 0)) == len(ROUTES)
            and int(self.coverage.get("physical_sources_scanned", 0)) == len(self.db.sources)
            and self.db.selected_source_staleness() <= DB_OPEN_BLOCK_SECONDS
            and len(self.poll_latencies[-120:]) >= MIN_LATENCY_GATE_SAMPLES
            and (percentile_95(self.poll_latencies[-120:]) or float("inf")) < 2.0
        )

    def quote_allows_open(self, product: str = ALLOWED_SYMBOL) -> bool:
        bid, ask, age = self.mt.quote_state(product)
        spread_cost = max(0.0, ask - bid) * float(self.mt.symbol(product).trade_contract_size)
        return (
            ask >= bid > 0
            and spread_cost <= 1.5 * default_roundtrip_spread_usd_per_lot(product)
            and age <= QUOTE_MAX_AGE_SECONDS
            and self.db.selected_source_staleness() <= DB_OPEN_BLOCK_SECONDS
            and self.operational_gates_ready()
        )

    def reconcile_sources(self) -> None:
        assert self.portfolio is not None
        before = self.portfolio.comparable_positions()
        rows = self.db.all_positions()
        check = MultiSourcePortfolio(self.routed_clients)
        check.replace_positions(rows)
        after = check.comparable_positions()
        if before == after:
            self.reconcile_streak += 1
            self.pending_source_snapshot = None
            self.pending_source_snapshot_count = 0
        else:
            self.reconcile_streak = 0
            if self.pending_source_snapshot == after:
                self.pending_source_snapshot_count += 1
            else:
                self.pending_source_snapshot = after
                self.pending_source_snapshot_count = 1
            if self.pending_source_snapshot_count >= 3:
                drift_before = dict(self.portfolio.positions)
                self.portfolio.replace_positions(rows)
                drift_after = dict(self.portfolio.positions)
                for key in sorted(set(drift_before) | set(drift_after)):
                    before_lots = drift_before.get(key, 0.0)
                    after_lots = drift_after.get(key, 0.0)
                    if abs(before_lots - after_lots) < 1e-12:
                        continue
                    self._handle_source_position_change(
                        account_key=key[0],
                        product=key[2],
                        position_id=key[1],
                        before_lots=before_lots,
                        after_lots=after_lots,
                        signal_time=utc_now(),
                        reason="SOURCE_RECONCILE",
                    )
                self.pending_source_snapshot = None
                self.pending_source_snapshot_count = 0
                self.log("Persistent multi-source position drift corrected after three matching snapshots.")
        self.last_reconcile = time.monotonic()
        self.last_db_success = time.monotonic()

    @staticmethod
    def _floor_to_step(value: float, step: float) -> float:
        units = math.floor(abs(value) / step + 1e-12)
        return math.copysign(round(units * step, 8), value) if units else 0.0

    def product_lot_cap(self, product: str, cycle_pnl_usd: float) -> float:
        account = self.mt.account()
        symbol = self.mt.symbol(product)
        step = float(symbol.volume_step)
        equity = max(float(account.equity), 1.0)
        throttle = drawdown_throttle(cycle_pnl_usd, self.cycle_loss_limit())
        stress_per_lot = max(
            self.mt.stress_loss_per_lot(product, stress_move_fraction(product)),
            1.0,
        )
        margin_per_lot = max(
            self.mt.margin_per_lot(1.0, product),
            self.mt.margin_per_lot(-1.0, product),
            1.0,
        )
        stress_cap = equity * 0.0075 / stress_per_lot
        margin_cap = equity * 0.08 / margin_per_lot
        cap = min(float(symbol.volume_max), stress_cap, margin_cap) * throttle
        return max(0.0, self._floor_to_step(cap, step))

    def _refresh_targets(
        self,
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float], float]:
        assert self.portfolio is not None
        account = self.mt.account()
        portfolio_targets = self.portfolio.targets(float(account.equity))
        raw = {product: values[0] for product, values in portfolio_targets.items()}
        gross_long = {product: values[1] for product, values in portfolio_targets.items()}
        gross_short = {product: values[2] for product, values in portfolio_targets.items()}
        marked = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
        cycle = marked - self.cycle_baseline_pnl
        products = set(raw) | set(self.current_targets) | set(self.mt.signed_positions())
        proposed: dict[str, float] = {}
        for product in sorted(products):
            symbol = self.mt.symbol(product)
            step = float(symbol.volume_step)
            minimum = float(symbol.volume_min)
            proposed[product] = hysteresis_target(
                raw.get(product, 0.0),
                self.current_targets.get(product, 0.0),
                max_lots=self.product_lot_cap(product, cycle),
                enter_lots=minimum,
                exit_lots=minimum / 2.0,
                lot_step=step,
            )

        total_margin = 0.0
        total_stress = 0.0
        for product, target in proposed.items():
            if abs(target) < 1e-12:
                continue
            total_margin += abs(target) * max(
                self.mt.margin_per_lot(1.0 if target > 0 else -1.0, product), 1.0
            )
            total_stress += abs(target) * max(
                self.mt.stress_loss_per_lot(product, stress_move_fraction(product)), 1.0
            )
        throttle = drawdown_throttle(cycle, self.cycle_loss_limit())
        margin_budget = max(float(account.equity), 1.0) * 0.20 * throttle
        stress_budget = max(float(account.equity), 1.0) * 0.02 * throttle
        scale = min(
            1.0,
            margin_budget / total_margin if total_margin > 0 else 1.0,
            stress_budget / total_stress if total_stress > 0 else 1.0,
        )
        self.current_targets = {
            product: self._floor_to_step(target * scale, float(self.mt.symbol(product).volume_step))
            for product, target in proposed.items()
        }
        self.current_target = self.current_targets.get(ALLOWED_SYMBOL, 0.0)
        return raw, gross_long, gross_short, cycle

    def _refresh_target(self) -> tuple[float, float, float, float]:
        raw, gross_long, gross_short, cycle = self._refresh_targets()
        return (
            raw.get(ALLOWED_SYMBOL, 0.0),
            gross_long.get(ALLOWED_SYMBOL, 0.0),
            gross_short.get(ALLOWED_SYMBOL, 0.0),
            cycle,
        )

    def apply_event(self, event: RoutedEvent) -> None:
        assert self.portfolio is not None
        product = normalize_source_product(event.symbol)
        before_lots = (
            self.portfolio.positions.get(
                (event.account_key, event.position_id, product), 0.0
            )
            if product is not None else 0.0
        )
        if not self.portfolio.apply_event(event):
            return
        latency = max(0.0, (utc_now() - filetime_to_datetime(event.timestamp)).total_seconds())
        self.signal_latencies.append(latency)
        client = self.routed_clients[event.account_key]
        if product is None:
            return
        after_lots = self.portfolio.positions.get(
            (event.account_key, event.position_id, product), 0.0
        )
        dynamic_key = sleeve_key(event.account_key, product)
        state = self.sleeve_states.get(dynamic_key)
        row = self.sleeve_rows.get(dynamic_key, {})
        allowed_delay = self._signal_delay_budget(row)
        risk_increase = (
            abs(after_lots) > 1e-12
            and (
                abs(before_lots) <= 1e-12
                or before_lots * after_lots < 0
                or (
                    before_lots * after_lots > 0
                    and abs(after_lots) > abs(before_lots) + 1e-12
                )
            )
        )
        expired = is_signal_expired(latency, allowed_delay)
        entry_timely = not (risk_increase and expired)
        if state is not None and expired:
            self.sleeve_states[dynamic_key] = record_expired_signal(
                state, "entry" if risk_increase else "exit", utc_now()
            )
        approved_after = self._approved_source_after(
            event.account_key,
            event.position_id,
            product,
            before_lots,
            after_lots,
            entry_timely=entry_timely,
        )
        copy_action, copy_position = self._handle_source_position_change(
            account_key=event.account_key,
            product=product,
            position_id=event.position_id,
            before_lots=before_lots,
            after_lots=approved_after,
            signal_time=filetime_to_datetime(event.timestamp),
            reason=f"SOURCE:{client.spec.alias}:{client.route_key}",
        )
        raw_targets, gross_longs, gross_shorts, _cycle = self._refresh_targets()
        raw = raw_targets.get(product, 0.0)
        gross_long = gross_longs.get(product, 0.0)
        gross_short = gross_shorts.get(product, 0.0)
        desired = self.current_targets.get(product, 0.0)
        self.event_counter += 1
        append_csv(
            self.event_path,
            {
                "event_id": f"E{self.event_counter:07d}",
                "time_beijing": filetime_to_datetime(event.timestamp).astimezone(BEIJING).isoformat(),
                "client_alias": client.spec.alias,
                "source_route": client.route_key,
                "source_server": client.server,
                "source_platform": client.platform,
                "source_side": "BUY" if event.action == 0 else "SELL",
                "source_entry": event.entry,
                "source_lots": event.lots,
                "product": product,
                "effective_weight": self._effective_copy_weight(
                    event.account_key, product
                ),
                "raw_target_lots": raw,
                "desired_target_lots": desired,
                "actual_strategy_lots": self.mt.signed_position(product),
                "gross_long_lots": gross_long,
                "gross_short_lots": gross_short,
                "db_latency_seconds": latency,
                "allowed_delay_seconds": allowed_delay,
                "signal_expired": expired,
                "phase": self.phase,
                "reason": (
                    ("signal_expired:" if expired else "")
                    + f"{copy_action}:"
                    f"{copy_position.status if copy_position is not None else 'monitor'}"
                ),
            },
        )

    def _approved_source_after(
        self,
        account_key: str,
        position_id: int,
        product: str,
        source_before: float,
        source_after: float,
        *,
        entry_timely: bool,
    ) -> float:
        book = getattr(self, "copy_book", None)
        if book is None:
            return source_after if entry_timely else source_before
        position = book.positions.get(
            source_position_key(account_key, position_id, product)
        )
        approved_before = position.source_lots if position is not None else 0.0
        if source_before * source_after < 0:
            return source_after if entry_timely else 0.0
        if abs(source_after) <= 1e-12:
            return 0.0
        if source_before * source_after > 0 and abs(source_after) < abs(source_before):
            return math.copysign(min(abs(approved_before), abs(source_after)), source_after)
        if not entry_timely:
            return approved_before
        increase = max(0.0, abs(source_after) - abs(source_before))
        if abs(approved_before) <= 1e-12:
            return math.copysign(increase, source_after)
        return math.copysign(
            min(abs(source_after), abs(approved_before) + increase), source_after
        )

    @staticmethod
    def _signal_delay_budget(row: Mapping[str, Any]) -> float:
        enabled_value = row.get("historical_delay_enabled", True)
        historical_delay_enabled = (
            enabled_value
            if isinstance(enabled_value, bool)
            else str(enabled_value).strip().lower() in {"1", "true", "yes"}
        )
        break_even_seconds = (
            float(row.get("conservative_break_even_ms", 0.0) or 0.0) / 1000.0
            if historical_delay_enabled
            else 5.0
        )
        return allowed_signal_delay_seconds(
            break_even_seconds,
            float(row.get("hold_p25_seconds", 0.0) or 0.0),
        )

    @staticmethod
    def _source_position_map(
        portfolio: MultiSourcePortfolio, source_key: str
    ) -> dict[tuple[str, int, str], float]:
        return {
            key: value
            for key, value in portfolio.positions.items()
            if portfolio.clients[key[0]].physical_key == source_key
        }

    def apply_mt4_snapshot(self, source_key: str, rows: list[dict[str, Any]]) -> None:
        assert self.portfolio is not None
        before = self._source_position_map(self.portfolio, source_key)
        self.portfolio.replace_source_positions(source_key, rows)
        after = self._source_position_map(self.portfolio, source_key)
        snapshot_rows = {
            (
                str(row["account_key"]),
                int(row["position_id"]),
                str(normalize_source_product(row.get("symbol"))),
            ): row
            for row in rows
            if normalize_source_product(row.get("symbol")) is not None
        }
        if before == after:
            return
        source_latency = self.db.sources[source_key].health.latency_ms or 0.0
        keys = sorted(set(before) | set(after))
        raw_targets, gross_longs, gross_shorts, _cycle = self._refresh_targets()
        for key in keys:
            delta = after.get(key, 0.0) - before.get(key, 0.0)
            if abs(delta) < 1e-12:
                continue
            client = self.routed_clients[key[0]]
            product = key[2]
            source_row = snapshot_rows.get(key)
            opened_text = str((source_row or {}).get("source_opened_at") or "")
            signal_time = utc_now()
            latency_known = False
            if opened_text and abs(before.get(key, 0.0)) <= 1e-12:
                try:
                    signal_time = datetime.fromisoformat(opened_text)
                    latency_known = signal_time.tzinfo is not None
                except ValueError:
                    signal_time = utc_now()
            latency = max(0.0, (utc_now() - signal_time).total_seconds())
            dynamic_key = sleeve_key(key[0], product)
            row = getattr(self, "sleeve_rows", {}).get(dynamic_key, {})
            allowed_delay = self._signal_delay_budget(row)
            risk_increase = (
                abs(after.get(key, 0.0)) > abs(before.get(key, 0.0)) + 1e-12
                or before.get(key, 0.0) * after.get(key, 0.0) < 0
            )
            expired = bool(
                risk_increase
                and (
                    not latency_known
                    or is_signal_expired(latency, allowed_delay)
                )
            )
            state = getattr(self, "sleeve_states", {}).get(dynamic_key)
            if state is not None and expired:
                self.sleeve_states[dynamic_key] = record_expired_signal(
                    state, "entry", utc_now()
                )
            approved_after = self._approved_source_after(
                key[0], key[1], product,
                before.get(key, 0.0), after.get(key, 0.0),
                entry_timely=not expired,
            )
            copy_action, copy_position = self._handle_source_position_change(
                account_key=key[0],
                product=product,
                position_id=key[1],
                before_lots=before.get(key, 0.0),
                after_lots=approved_after,
                signal_time=signal_time,
                reason=f"SOURCE_SNAPSHOT:{source_key}",
            )
            raw = raw_targets.get(product, 0.0)
            gross_long = gross_longs.get(product, 0.0)
            gross_short = gross_shorts.get(product, 0.0)
            desired = self.current_targets.get(product, 0.0)
            self.event_counter += 1
            append_csv(
                self.event_path,
                {
                    "event_id": f"E{self.event_counter:07d}",
                    "time_beijing": beijing_now().isoformat(),
                    "client_alias": client.spec.alias,
                    "source_route": client.route_key,
                    "source_server": client.server,
                    "source_platform": "MT4",
                    "source_side": "BUY" if delta > 0 else "SELL",
                    "source_entry": 0 if abs(after.get(key, 0.0)) > abs(before.get(key, 0.0)) else 1,
                    "source_lots": abs(delta),
                    "product": key[2],
                    "effective_weight": self._effective_copy_weight(
                        key[0], product
                    ),
                    "raw_target_lots": raw,
                    "desired_target_lots": desired,
                    "actual_strategy_lots": self.mt.signed_position(product),
                    "gross_long_lots": gross_long,
                    "gross_short_lots": gross_short,
                    "db_latency_seconds": source_latency / 1000.0,
                    "allowed_delay_seconds": allowed_delay,
                    "signal_expired": expired,
                    "latency_known": latency_known,
                    "phase": self.phase,
                    "reason": (
                        f"MT4:{copy_action}:"
                        f"{copy_position.status if copy_position is not None else 'monitor'}"
                    ),
                },
            )

    def refresh_mt5_conflicts(self) -> bool:
        managed = set(self.current_targets)
        self.external_position_conflict = bool(self.mt.all_foreign_positions(managed))
        self.pending_order_conflict = bool(self.mt.all_pending_orders(managed))
        if self.external_position_conflict or self.pending_order_conflict:
            labels: list[str] = []
            if self.external_position_conflict:
                labels.append("managed-product external position")
            if self.pending_order_conflict:
                labels.append("managed-product pending order")
            self.last_error = f"Exposure conflict detected ({', '.join(labels)}); new risk is blocked."
            return True
        return False

    def log_product_order(
        self,
        product: str,
        action: str,
        before: float,
        target: float,
        result: Any | None,
    ) -> None:
        self.order_counter += 1
        bid, ask, age = self.mt.quote_state(product)
        append_csv(
            self.order_path,
            {
                "order_event": f"O{self.order_counter:06d}",
                "time_beijing": beijing_now().isoformat(),
                "product": product,
                "action": action,
                "before_lots": before,
                "target_lots": target,
                "after_lots": self.mt.signed_position(product),
                "bid": bid,
                "ask": ask,
                "spread_price": ask - bid,
                "quote_age_seconds": age,
                "retcode": int(result.retcode) if result is not None else "",
                "comment": str(result.comment) if result is not None else "",
            },
        )

    def flatten(self, reason: str) -> None:
        before_by_product: dict[str, float] = {}
        for position in self._live_positions():
            product = str(position.symbol)
            before_by_product[product] = before_by_product.get(product, 0.0) + (
                float(position.volume) if int(position.type) == 0 else -float(position.volume)
            )
        products = set(before_by_product)
        results = self.mt.close_all_symbols()
        wait_for_flat = getattr(self.mt, "wait_for_no_strategy_positions", None)
        if callable(wait_for_flat):
            wait_for_flat()
        elif self._live_positions():
            raise RuntimeError("Strategy tickets remain after flatten.")
        for product in products:
            self.log_product_order(
                product,
                f"FLATTEN:{reason}",
                before_by_product[product],
                0.0,
                results[-1] if results else None,
            )
        self.current_targets = {product: 0.0 for product in self.current_targets}
        self.current_target = 0.0
        for position in self.copy_book.positions.values():
            self._sync_book_children(position)
            position.copy_eligible = False
            position.status = "risk_flattened"
            position.reject_reason = reason
        self.log(f"All strategy product positions flattened: {reason}.")

    def execution_hard_stop(self, reason: str, error: Exception) -> None:
        try:
            self.flatten(f"hard_stop:{reason}")
        except Exception as flatten_error:
            self.log(f"Emergency multi-product flatten failed: {flatten_error}")
        self.phase = "execution_hard_stop"
        self.log(f"Execution hard stop: {error}")

    def execute_targets(
        self,
        desired: Mapping[str, float],
        reason: str,
        allow_new_exposure: bool = True,
    ) -> None:
        current = self.mt.signed_positions()
        products = set(current) | set(desired)
        conflict = self.refresh_mt5_conflicts()
        tasks: list[tuple[bool, str, float, float]] = []
        for product in products:
            before = current.get(product, 0.0)
            target = float(desired.get(product, 0.0))
            can_open = (
                allow_new_exposure
                and not conflict
                and self.quote_allows_open(product)
            )
            immediate = guarded_execution_target(before, target, can_open)
            if abs(before - immediate) < 1e-9:
                continue
            reduction = (
                abs(immediate) < abs(before) - 1e-9
                or before * immediate < 0
            )
            tasks.append((not reduction, product, before, immediate))
        tasks.sort(key=lambda item: (item[0], item[1]))
        for _is_increase, product, before, immediate in tasks:
            target_requested = float(desired.get(product, 0.0))
            action = reason if abs(immediate - target_requested) < 1e-9 else f"{reason}:CLOSE_ONLY"
            try:
                results = self.mt.move_to(
                    immediate,
                    product,
                    hard_cap_lots=self.product_lot_cap(
                        product,
                        self.mt.marked_pnl(trading_day_start_utc(utc_now()))
                        - self.cycle_baseline_pnl,
                    ),
                )
                self.log_product_order(
                    product,
                    action,
                    before,
                    immediate,
                    results[-1] if results else None,
                )
            except Exception as exc:
                self.execution_hard_stop(reason, exc)
                raise

    def reconcile_mt5_target(self) -> None:
        policy = friday_policy(server_time_from_utc(utc_now()))
        if policy == "flatten":
            if self._live_positions():
                self.flatten("friday_fallback")
            return
        self.reconcile_independent_copies(
            allow_increase=self.phase == "live" and policy == "normal"
        )

    def risk_check(self) -> None:
        policy = friday_policy(server_time_from_utc(utc_now()))
        if policy == "flatten" and self._live_positions():
            self.flatten("friday_fallback")
        current_day = trading_day_key(utc_now())
        if current_day != self.last_pool_reload_day:
            server_now = server_time_from_utc(utc_now())
            if (server_now.hour, server_now.minute) >= (0, 15):
                self.daily_hard_stop = False
                self.daily_reference_equity = float(self.mt.account().equity)
        account = self.mt.account()
        margin_ratio = max(float(getattr(account, "margin", 0.0) or 0.0), 0.0) / max(
            float(account.equity), 1.0
        )
        if margin_ratio >= PORTFOLIO_MARGIN_HARD_FRACTION:
            if self._live_positions():
                self.flatten("margin_hard_limit")
            self.phase = "margin_hard_stop"
            return
        marked = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
        cycle = marked - self.cycle_baseline_pnl
        if (
            self.profile.equity_floor_usd is not None
            and float(account.equity) <= self.profile.equity_floor_usd
        ):
            if self._live_positions():
                self.flatten("equity_floor")
            self.daily_hard_stop = True
            self.phase = "equity_floor_stop"
            return
        if marked <= -self.daily_loss_limit():
            if self._live_positions():
                self.flatten("daily_loss_stop")
            self.daily_hard_stop = True
            self.phase = "daily_stop"
            return
        if self.phase == "live" and cycle <= -self.cycle_loss_limit():
            self.flatten("cycle_loss_stop")
            self.cooldown_until = utc_now() + timedelta(seconds=COOLDOWN_SECONDS)
            self.phase = "cooldown"
        if self.phase == "cooldown" and self.cooldown_until is not None and utc_now() >= self.cooldown_until:
            self.phase = "recovery_shadow"
            self.shadow_started = time.monotonic()
            self.required_shadow_seconds = RECOVERY_SHADOW_SECONDS
            self.reconcile_streak = 0
        if self.phase == "recovery_shadow" and self.shadow_ready():
            self.cycle_baseline_pnl = marked
            self.cycle_reference_equity = float(account.equity)
            self.phase = "live"
        if self.portfolio is not None and self.phase not in {
            "daily_stop", "equity_floor_stop", "execution_hard_stop",
        }:
            self._refresh_targets()

    def maybe_transition_live(self) -> None:
        if self.args.mode == "Shadow":
            return
        if self.phase == "armed_waiting_autotrading" and not self.operational_gates_ready():
            self.phase = "shadow"
            self.log("Operational gates regressed; returning to shadow mode.")
            return
        ready = self.phase == "shadow" and self.shadow_ready()
        armed = self.phase == "armed_waiting_autotrading"
        if ready and not (self.args.enable_live_trading and bool(self.mt.terminal().trade_allowed)):
            self.phase = "armed_waiting_autotrading"
            self.log("Shadow gates passed; waiting for explicit launcher authorization and MT5 trade capability.")
            return
        if (ready or armed) and self.args.enable_live_trading and bool(self.mt.terminal().trade_allowed):
            self.phase = "live"
            self.cycle_baseline_pnl = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
            self.cycle_reference_equity = float(self.mt.account().equity)
            self.log("Shadow gates passed; independent customer-position Demo execution is active.")

    def maybe_daily_rebuild(self) -> None:
        now = utc_now()
        if not scheduler_due(self.scheduler_state, now).daily_rebuild:
            return
        if time.monotonic() - self.last_rebuild_attempt < REBUILD_RETRY_SECONDS:
            return
        self.last_rebuild_attempt = time.monotonic()
        if self._live_positions():
            self.flatten("daily_pool_rebuild")
        self.current_targets = {product: 0.0 for product in self.current_targets}
        self.current_target = 0.0
        self.phase = "pool_rebuilding"
        try:
            self.load_pool(force_rebuild=True)
            self.product_execution = self.mt.configure_symbols(self.current_targets)
            self.bootstrap()
        except Exception:
            self.phase = "pool_rebuild_failed"
            raise
        self.phase = "recovery_shadow"
        self.shadow_started = time.monotonic()
        self.required_shadow_seconds = RECOVERY_SHADOW_SECONDS
        self.reconcile_streak = 0
        self.last_pool_reload_day = trading_day_key(now)
        self.scheduler_state = mark_scheduler_run(
            self.scheduler_state, now, daily_rebuild_run=True
        )
        self.log("All-source daily pool rebuild completed; recovery shadow started.")

    def run(self) -> None:
        self.db.connect()
        self.load_pool(force_rebuild=self.args.force_rebuild)
        if self.args.preflight_only:
            self.log(
                "All-source preflight completed; database coverage and the pool contract were "
                "verified, the MT5 terminal was not initialized, and no order API was called."
            )
            self.db.close()
            return
        self.mt.initialize()
        self.product_execution = self.mt.configure_symbols(self.current_targets)
        account = self.mt.account()
        if (
            self.profile.minimum_start_balance_usd is not None
            and float(account.balance) < self.profile.minimum_start_balance_usd
        ):
            raise RuntimeError(
                f"{self.profile.name} refuses account balance {float(account.balance):.2f} USD."
            )
        existing_positions = self.mt.signed_positions()
        unknown_positions = set(existing_positions) - set(self.current_targets)
        if unknown_positions:
            raise RuntimeError(
                f"Existing strategy exposure contains products outside the accepted pool: {sorted(unknown_positions)}"
            )
        self.refresh_mt5_conflicts()
        self.bootstrap()
        self._refresh_independent_client_risk(force=True)
        self.log(
            f"Multi-source service started in {self.phase}; profile={self.profile.name}, "
            f"shadow={self.required_shadow_seconds:.0f}s, poll={self.args.poll_ms}ms."
        )
        self.persist_private_state()
        self.write_status()
        started = time.monotonic()
        try:
            while self.running:
                if self.args.run_seconds and time.monotonic() - started >= self.args.run_seconds:
                    break
                loop_started = time.monotonic()
                try:
                    assert self.portfolio is not None
                    events, mt5_errors = self.db.poll_mt5_events(self.portfolio.cursors)
                    snapshots, mt4_errors = self.db.poll_mt4_positions()
                    for event in events:
                        self.apply_event(event)
                    for source_key, rows in snapshots.items():
                        self.apply_mt4_snapshot(source_key, rows)
                    self.poll_latencies.append(time.monotonic() - loop_started)
                    if not mt5_errors and not mt4_errors:
                        self.last_db_success = time.monotonic()
                    else:
                        self.last_error = "; ".join(mt5_errors + mt4_errors)

                    if time.monotonic() - self.last_intraday_refresh >= INTRADAY_REFRESH_SECONDS:
                        self.portfolio.set_intraday_net(
                            self.db.intraday_net(trading_day_start_utc(utc_now()))
                        )
                        product_net_reader = getattr(self.db, "intraday_product_net", None)
                        if callable(product_net_reader):
                            self.portfolio.set_intraday_product_net(
                                product_net_reader(trading_day_start_utc(utc_now()))
                            )
                        self.portfolio.set_open_risk(self.db.selected_open_risk())
                        self._refresh_independent_client_risk(force=True)
                        self.last_intraday_refresh = time.monotonic()
                    if time.monotonic() - self.last_reconcile >= RECONCILE_SECONDS:
                        self.reconcile_sources()
                    self.maybe_daily_rebuild()
                    self.maybe_transition_live()
                    self.refresh_dynamic_sleeves()
                    self.risk_check()
                    self.refresh_mt5_conflicts()
                    self.reconcile_mt5_target()
                    if self.db.selected_source_staleness() >= DB_FLATTEN_SECONDS:
                        if self._live_positions():
                            self.flatten("selected_source_outage")
                    self.persist_private_state()
                    self.write_status()
                    if not mt5_errors and not mt4_errors:
                        self.last_error = ""
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self.log(self.last_error)
                    if self.db.selected_source_staleness() >= DB_FLATTEN_SECONDS:
                        try:
                            if self._live_positions():
                                self.flatten("database_or_runtime_outage")
                        except Exception as flatten_error:
                            self.log(f"Emergency flatten failed: {flatten_error}")
                    time.sleep(min(2.0, self.args.poll_ms / 1000.0 * 2))
                elapsed = time.monotonic() - loop_started
                time.sleep(max(0.0, self.args.poll_ms / 1000.0 - elapsed))
        finally:
            self.persist_private_state()
            try:
                self.write_status()
            except Exception:
                pass
            self.db.close()
            self.mt.shutdown()
            self.log("Multi-source service stopped.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="All-route dynamic customer-pool MT5 Demo copier.")
    parser.add_argument("--input-dir", type=Path, default=Path("D:/risk/output_data"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--risk-profile", choices=tuple(RISK_PROFILES), default="Capital10k")
    parser.add_argument("--mode", choices=("Shadow", "StagedLive", "Live"), default="StagedLive")
    parser.add_argument("--shadow-minutes", type=float, default=30.0)
    parser.add_argument("--poll-ms", type=int, default=500)
    parser.add_argument("--run-seconds", type=float, default=0.0)
    parser.add_argument("--enable-live-trading", action="store_true")
    parser.add_argument("--allow-demo-min-lot-override", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()
    if args.shadow_minutes < 0:
        parser.error("--shadow-minutes must be nonnegative")
    if args.poll_ms < 250 or args.poll_ms > 10_000:
        parser.error("--poll-ms must be between 250 and 10000")
    return args


def main() -> None:
    service = MultiSourceLiveService(parse_args())

    def stop_service(_signum: int, _frame: Any) -> None:
        service.running = False

    signal.signal(signal.SIGINT, stop_service)
    signal.signal(signal.SIGTERM, stop_service)
    service.run()


if __name__ == "__main__":
    main()
