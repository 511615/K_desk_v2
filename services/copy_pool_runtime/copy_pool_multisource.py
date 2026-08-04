from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd
import pymysql
from copy_dynamic_pool_domain import RankingCandidate, build_rank_universe
from copy_product_catalog import (
    default_roundtrip_spread_usd_per_lot,
    normalize_source_product,
    product_spec,
)
from copy_trading_live_core import (
    ClientSpec,
    holding_score_multiplier,
    intraday_multiplier,
)

BEIJING = timezone(timedelta(hours=8))
POOL_SIZE = 30
MIN_ACTIVE_CLIENTS_PER_PRODUCT = 5
TOTAL_CLIENT_BUDGET = 0.25
MAX_CLIENT_WEIGHT = 0.03
MAX_SLEEVE_WEIGHT = 0.015
MAX_PRODUCT_WEIGHT = 0.08
MAX_ROUTE_WEIGHT = 0.08
MAX_CLIENTS_PER_ROUTE = 5
MT4_STRESS_SPREAD_USD_PER_LOT = 60.0
MAX_BUILD_FLOATING_LOSS_RATIO = 0.10
MAX_BUILD_MARGIN_TO_EQUITY = 0.50


def require_nonempty_monitor_population(account_count: int, *, context: str) -> None:
    """Reject an empty qualified population without turning the 30-account target into a gate."""
    if int(account_count) < 1:
        raise RuntimeError(f"No monitor accounts remained {context}.")


def open_risk_multiplier(
    floating_loss_ratio: float,
    margin_to_equity: float,
    xau_hedge_ratio: float,
) -> float:
    floating = intraday_multiplier(-max(float(floating_loss_ratio), 0.0), 1.0)
    margin = 1.0 if margin_to_equity <= 0.20 else max(
        0.0, min(1.0, (MAX_BUILD_MARGIN_TO_EQUITY - margin_to_equity) / 0.30)
    )
    hedge = 1.0 - 0.5 * max(0.0, min(1.0, xau_hedge_ratio))
    return min(floating, margin, hedge)


def passes_current_open_risk_gate(
    floating_loss_ratio: float,
    margin_to_equity: float,
) -> bool:
    return (
        math.isfinite(floating_loss_ratio)
        and math.isfinite(margin_to_equity)
        and floating_loss_ratio < MAX_BUILD_FLOATING_LOSS_RATIO
        and margin_to_equity < MAX_BUILD_MARGIN_TO_EQUITY
    )


@dataclass(frozen=True)
class LogicalRoute:
    key: str
    connection: str
    crm_schema: str
    server_code: int
    schema: str
    platform: str
    server: str
    mt4_utc_offset_hours: int | None = None

    @property
    def physical_key(self) -> str:
        return f"{self.connection}:{self.schema}:{self.platform}"


ROUTES: tuple[LogicalRoute, ...] = (
    LogicalRoute("ac_gb_mt5", "AC", "int_sass_crm_ac", 1, "int_sass_crm_ac_mt5_live_new", "MT5", "AC GB MT5"),
    LogicalRoute("ac_cn_mt5", "AC", "sass_crm_ac", 1, "sass_crm_ac_mt5_live", "MT5", "AC CN MT5"),
    LogicalRoute("ac_cn_mt5_live3", "AC", "sass_crm_ac", 3, "sass_crm_ac_mt5_live3", "MT5", "AC CN MT5 Live3"),
    LogicalRoute("ac_cn_mt4", "AC", "sass_crm_ac", 2, "mt4_export_syc", "MT4", "AC CN MT4", 0),
    LogicalRoute("ac_gb_mt4", "AC", "int_sass_crm_ac", 2, "mt4_export_syc", "MT4", "AC GB MT4", 0),
    LogicalRoute("dbg_cn_mt5", "DBG", "crm_cn", 4, "mt5_export_new", "MT5", "DBG CN MT5"),
    LogicalRoute("dbg_gb_mt5", "DBG", "crm_vn", 2, "mt5_export_new", "MT5", "DBG GB MT5"),
    LogicalRoute("dbg_gb_mt5_live2", "DBG", "crm_vn", 5, "crm_vn_mt5_live2", "MT5", "DBG GB MT5 Live2"),
    LogicalRoute("dbg_cn_mt4_live1", "DBG", "crm_cn", 1, "crm_cn_mt4_live1", "MT4", "DBG CN MT4 Live1", 3),
    LogicalRoute("dbg_cn_mt4_live2", "DBG", "crm_cn", 3, "crm_cn_mt4_live2", "MT4", "DBG CN MT4 Live2", 3),
    # Live3 follows the current DBG MT4 +03:00 convention until a fresh runtime event audit reconfirms it.
    LogicalRoute("dbg_vn_mt4_live3", "DBG", "crm_vn", 1, "crm_vn_mt4_live3", "MT4", "DBG VN MT4 Live3", 3),
)


def physical_routes() -> dict[str, tuple[LogicalRoute, ...]]:
    grouped: dict[str, list[LogicalRoute]] = defaultdict(list)
    for route in ROUTES:
        grouped[route.physical_key].append(route)
    return {key: tuple(value) for key, value in grouped.items()}


def mt4_source_utc_offset_hours(source_key: str) -> int:
    """Return the audited source-local UTC offset for one physical MT4 source."""
    routes = physical_routes().get(source_key)
    if not routes:
        raise ValueError(f"Unknown physical source {source_key!r}.")
    if routes[0].platform != "MT4":
        raise ValueError(f"Physical source {source_key!r} is not MT4.")
    offsets = {route.mt4_utc_offset_hours for route in routes}
    if len(offsets) != 1 or None in offsets:
        raise ValueError(f"MT4 source {source_key!r} has no unambiguous UTC offset.")
    return int(offsets.pop())


def mt4_source_time_to_utc(source_key: str, value: datetime) -> datetime:
    """Normalize a raw MT4 server datetime to an aware UTC instant."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    offset = timezone(timedelta(hours=mt4_source_utc_offset_hours(source_key)))
    return value.replace(tzinfo=offset).astimezone(timezone.utc)


def account_key(route_key: str, login: int) -> str:
    return f"{route_key}:{int(login)}"


def validate_complete_coverage(
    coverage: Mapping[str, Any], physical_keys: Iterable[str]
) -> None:
    expected_routes = {route.key for route in ROUTES}
    expected_sources = set(physical_keys)
    route_counts = coverage.get("route_account_counts")
    source_rows = coverage.get("sources")
    covered_routes = set(route_counts) if isinstance(route_counts, Mapping) else set()
    covered_sources = {
        str(row.get("physical_key"))
        for row in source_rows
        if isinstance(row, Mapping) and row.get("physical_key")
    } if isinstance(source_rows, list) else set()
    healthy_sources = {
        str(row.get("physical_key"))
        for row in source_rows
        if isinstance(row, Mapping) and row.get("state") == "ok"
    } if isinstance(source_rows, list) else set()
    complete = (
        int(coverage.get("logical_routes_expected", 0)) == len(expected_routes)
        and int(coverage.get("logical_routes_scanned", 0)) == len(expected_routes)
        and int(coverage.get("physical_sources_expected", 0)) == len(expected_sources)
        and int(coverage.get("physical_sources_scanned", 0)) == len(expected_sources)
        and covered_routes == expected_routes
        and covered_sources == expected_sources
        and healthy_sources == expected_sources
    )
    if not complete:
        raise RuntimeError(
            "All-source coverage gate failed: the accepted pool requires every configured "
            "logical route and physical source to complete successfully."
        )


def _chunks(values: Sequence[int], size: int = 250) -> Iterable[Sequence[int]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _percentile_rank(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average").fillna(0.0)


def _winsorize(series: pd.Series, low: float = 0.01, high: float = 0.99) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() < 2:
        return numeric.fillna(0.0)
    return numeric.clip(numeric.quantile(low), numeric.quantile(high))


def _normalize_capped(raw: Mapping[Any, float], cap: float) -> dict[Any, float]:
    result = {key: 0.0 for key in raw}
    remaining = {key for key, value in raw.items() if float(value) > 0}
    budget = 1.0
    while remaining and budget > 1e-12:
        subtotal = sum(float(raw[key]) for key in remaining)
        if subtotal <= 0:
            break
        proposed = {key: float(raw[key]) / subtotal * budget for key in remaining}
        saturated = {
            key
            for key, value in proposed.items()
            if value >= cap - result[key] - 1e-12
        }
        if not saturated:
            for key, value in proposed.items():
                result[key] += value
            break
        for key in saturated:
            allocation = max(0.0, cap - result[key])
            result[key] += allocation
            budget -= allocation
            remaining.remove(key)
    return result


def normalize_product_budget_weights(
    raw: Mapping[str, float], cap: float = 0.40
) -> tuple[dict[str, float], bool]:
    """Normalize product weights to 100%, using the cap only when it is feasible."""
    result = _normalize_capped(raw, cap=cap)
    positive = [key for key, value in raw.items() if float(value) > 0]
    allocated = sum(result.values())
    remainder = max(0.0, 1.0 - allocated)
    if not positive or remainder <= 1e-12:
        return result, False
    increment = remainder / len(positive)
    for key in positive:
        result[key] += increment
    return result, True


def _is_cent(currency: object, group: object, account_type: object) -> bool:
    values = "|".join(str(value or "").upper() for value in (currency, group, account_type))
    tokens = values.replace("\\", "|").replace("/", "|").replace("-", "|").replace("_", "|").split("|")
    return any(token.strip() in {"USC", "USCENT", "CENT"} for token in tokens)


def normalize_route_capped_weights(
    rows: pd.DataFrame,
    budget: float = TOTAL_CLIENT_BUDGET,
    client_cap: float = MAX_CLIENT_WEIGHT,
    route_cap: float = MAX_ROUTE_WEIGHT,
    sleeve_cap: float = MAX_SLEEVE_WEIGHT,
    product_cap: float = MAX_PRODUCT_WEIGHT,
) -> pd.Series:
    if rows.empty:
        return pd.Series(dtype=float)
    raw = {index: max(float(value), 0.0) for index, value in rows["weight_alpha"].items()}
    routes = {index: str(rows.at[index, "route_key"]) for index in rows.index}
    accounts = {
        index: str(rows.at[index, "account_key"]) if "account_key" in rows else f"row:{index}"
        for index in rows.index
    }
    products = {
        index: str(rows.at[index, "product"]) if "product" in rows else f"row:{index}"
        for index in rows.index
    }
    result = {index: 0.0 for index in rows.index}
    remaining = {index for index in rows.index if raw[index] > 0}
    route_used: dict[str, float] = defaultdict(float)
    account_used: dict[str, float] = defaultdict(float)
    product_used: dict[str, float] = defaultdict(float)
    remaining_budget = float(budget)
    for _ in range(len(rows) * 6 + 20):
        if not remaining or remaining_budget <= 1e-12:
            break
        subtotal = sum(raw[index] for index in remaining)
        if subtotal <= 0:
            break
        proposed = {
            index: raw[index] / subtotal * remaining_budget for index in remaining
        }
        factor = 1.0
        for index, allocation in proposed.items():
            factor = min(factor, max(0.0, sleeve_cap - result[index]) / allocation)
        for mapping, used, cap in (
            (routes, route_used, route_cap),
            (accounts, account_used, client_cap),
            (products, product_used, product_cap),
        ):
            grouped: dict[str, float] = defaultdict(float)
            for index, allocation in proposed.items():
                grouped[mapping[index]] += allocation
            for group, allocation in grouped.items():
                factor = min(factor, max(0.0, cap - used[group]) / allocation)
        factor = max(0.0, min(1.0, factor))
        if factor <= 1e-12:
            break
        allocated = 0.0
        for index, proposal in proposed.items():
            addition = proposal * factor
            result[index] += addition
            route_used[routes[index]] += addition
            account_used[accounts[index]] += addition
            product_used[products[index]] += addition
            allocated += addition
        remaining_budget -= allocated
        if factor >= 1.0 - 1e-12:
            break
        saturated_routes = {key for key, value in route_used.items() if value >= route_cap - 1e-12}
        saturated_accounts = {key for key, value in account_used.items() if value >= client_cap - 1e-12}
        saturated_products = {key for key, value in product_used.items() if value >= product_cap - 1e-12}
        remaining = {
            index
            for index in remaining
            if result[index] < sleeve_cap - 1e-12
            and routes[index] not in saturated_routes
            and accounts[index] not in saturated_accounts
            and products[index] not in saturated_products
        }
    return pd.Series(result, index=rows.index, dtype=float)


@dataclass
class SourceHealth:
    physical_key: str
    connection: str
    schema: str
    platform: str
    logical_routes: tuple[str, ...]
    state: str = "starting"
    selected_clients: int = 0
    candidate_accounts: int = 0
    eligible_accounts: int = 0
    last_success_monotonic: float = 0.0
    last_success_at: str = ""
    latency_ms: float | None = None
    last_error: str = ""

    def success(self, latency_seconds: float) -> None:
        self.state = "ok"
        self.last_success_monotonic = time.monotonic()
        self.last_success_at = datetime.now(BEIJING).isoformat()
        self.latency_ms = latency_seconds * 1000.0
        self.last_error = ""

    def failure(self, exc: Exception) -> None:
        self.state = "error"
        self.last_error = f"{type(exc).__name__}: {exc}"

    def set_subscription_count(self, count: int) -> None:
        self.selected_clients = max(0, int(count))
        if self.selected_clients == 0 and self.state in {"starting", "ok", "idle"}:
            self.state = "idle"
        elif self.selected_clients > 0 and self.state == "idle":
            self.state = "starting"

    def public(self) -> dict[str, Any]:
        age = None
        if self.last_success_monotonic > 0:
            age = max(0.0, time.monotonic() - self.last_success_monotonic)
        payload = asdict(self)
        payload.pop("last_success_monotonic", None)
        payload["age_seconds"] = age
        return payload


class ReadOnlySource:
    def __init__(self, routes: Sequence[LogicalRoute]) -> None:
        if not routes:
            raise ValueError("A physical source requires at least one logical route.")
        first = routes[0]
        self.routes = tuple(routes)
        self.key = first.physical_key
        self.connection_name = first.connection
        self.schema = first.schema
        self.platform = first.platform
        self.connection: pymysql.Connection | None = None
        self.lock = threading.Lock()
        self.health = SourceHealth(
            physical_key=self.key,
            connection=self.connection_name,
            schema=self.schema,
            platform=self.platform,
            logical_routes=tuple(route.key for route in routes),
        )

    def connect(self) -> None:
        prefix = f"COPY_{self.connection_name}_DB_"
        required = [f"{prefix}{name}" for name in ("HOST", "PORT", "USER", "PASSWORD")]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing {self.connection_name} database environment: {', '.join(missing)}")
        self.close()
        self.connection = pymysql.connect(
            host=os.environ[f"{prefix}HOST"],
            port=int(os.environ[f"{prefix}PORT"]),
            user=os.environ[f"{prefix}USER"],
            password=os.environ[f"{prefix}PASSWORD"],
            database=self.schema,
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=8,
            read_timeout=30,
            write_timeout=8,
            cursorclass=pymysql.cursors.DictCursor,
        )
        with self.connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None

    def reset_connection(self) -> None:
        with self.lock:
            self.close()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT statements are allowed.")
        started = time.monotonic()
        with self.lock:
            try:
                if self.connection is None:
                    self.connect()
                else:
                    try:
                        self.connection.ping(reconnect=False)
                    except Exception:
                        self.connect()
                assert self.connection is not None
                with self.connection.cursor() as cursor:
                    cursor.execute(sql, tuple(params))
                    rows = list(cursor.fetchall())
                self.health.success(time.monotonic() - started)
                return rows
            except Exception as exc:
                self.health.failure(exc)
                self.close()
                raise


@dataclass(frozen=True, order=True)
class SourceCursor:
    timestamp: int = 0
    sequence: int = 0


@dataclass(frozen=True)
class RoutedEvent:
    source_key: str
    account_key: str
    login: str
    sequence: int
    timestamp: int
    position_id: int
    action: int
    entry: int
    symbol: str
    lots: float
    volume_closed_lots: float
    profit: float
    commission: float
    storage: float
    fee: float

    @property
    def cursor(self) -> SourceCursor:
        return SourceCursor(self.timestamp, self.sequence)


@dataclass(frozen=True)
class ProductSpec:
    product: str
    base_weight: float
    historical_net_20d_usd: float
    source_contract_size: float
    demo_contract_size: float
    adjusted_score: float
    median_hold_seconds: float | None = None
    activity_eligible: bool = True
    customer_base_weight: float = 0.0
    product_budget_weight: float = 0.0


def sleeve_key(account_key_value: str, product: str) -> str:
    return f"{account_key_value}|{product}"


def rank_hourly_universe(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Re-rank cached hard-qualified sleeves with bounded session evidence."""
    required = {
        "account_key", "product", "sleeve_key", "factor_ready",
        "factor_base_score", "activity_eligible", "net_20d_usd",
        "equity_pre_usd", "route_key", "physical_key", "hold_multiplier",
        "is_abook",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Hourly discovery universe is missing columns: {sorted(missing)}")
    if frame.empty:
        return frame.copy(), {
            "monitor_accounts": 0, "reserve_accounts": 0,
            "selected_sleeves": 0, "coverage_products": [],
            "product_cap_fallback_accounts": [],
        }

    ranked = frame.copy()
    defaults: dict[str, Any] = {
        "recent_net_1h_usd": 0.0,
        "recent_net_4h_usd": 0.0,
        "closed_delta_since_build_usd": 0.0,
        "current_product_floating_pnl_usd": 0.0,
        "current_equity_usd": pd.to_numeric(ranked["equity_pre_usd"], errors="coerce"),
        "current_margin_to_equity": 0.0,
        "current_floating_loss_ratio": 0.0,
        "current_open_risk_multiplier": 1.0,
    }
    for column, default in defaults.items():
        if column not in ranked:
            ranked[column] = default
        ranked[column] = pd.to_numeric(ranked[column], errors="coerce").fillna(default)

    equity = ranked["current_equity_usd"].where(
        ranked["current_equity_usd"] > 0,
        pd.to_numeric(ranked["equity_pre_usd"], errors="coerce"),
    ).replace(0, float("nan"))
    ranked["recent_return_1h"] = ranked["recent_net_1h_usd"] / equity
    ranked["recent_return_4h"] = ranked["recent_net_4h_usd"] / equity
    # Percentile ranks already bound the influence of an extreme return. A
    # second 1/99 winsorization would erase a genuine lone leader in a universe
    # of roughly one hundred sleeves.
    ranked["recent_score_1h"] = _percentile_rank(ranked["recent_return_1h"])
    ranked["recent_score_4h"] = _percentile_rank(ranked["recent_return_4h"])
    ranked["hourly_score"] = (
        0.65 * pd.to_numeric(ranked["factor_base_score"], errors="coerce").fillna(0.0)
        + 0.15 * ranked["recent_score_1h"]
        + 0.20 * ranked["recent_score_4h"]
        + ranked["is_abook"].fillna(False).astype(bool).astype(float) * 0.02
    ).clip(0.0, 1.0)
    ranked["current_comprehensive_net_20d_usd"] = (
        pd.to_numeric(ranked["net_20d_usd"], errors="coerce").fillna(0.0)
        + ranked["closed_delta_since_build_usd"]
        + ranked["current_product_floating_pnl_usd"]
    )
    ranked["hourly_hard_eligible"] = (
        ranked["factor_ready"].fillna(False).astype(bool)
        & (ranked["current_comprehensive_net_20d_usd"] > 0)
        & (equity >= 100.0)
        & (ranked["current_floating_loss_ratio"] < MAX_BUILD_FLOATING_LOSS_RATIO)
        & (ranked["current_margin_to_equity"] < MAX_BUILD_MARGIN_TO_EQUITY)
    )
    ranked["hourly_activity_eligible"] = (
        ranked["activity_eligible"].fillna(False).astype(bool)
        & ranked["hourly_hard_eligible"]
    )
    ranked["hourly_monitor_score"] = (
        ranked["hourly_score"]
        * ranked["current_open_risk_multiplier"].clip(0.0, 1.0)
        * pd.to_numeric(ranked["hold_multiplier"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    )

    universe = build_rank_universe(
        RankingCandidate(
            sleeve_key=str(row.sleeve_key), account_key=str(row.account_key),
            product=str(row.product), score=float(row.hourly_monitor_score),
            hard_eligible=bool(row.hourly_hard_eligible),
            activity_eligible=bool(row.hourly_activity_eligible),
            min_lot_feasible=True,
        )
        for row in ranked.itertuples()
    )
    monitor_accounts = set(universe.monitor_accounts)
    selected_accounts = monitor_accounts | set(universe.reserve_accounts)
    selected = ranked.loc[
        ranked["account_key"].astype(str).isin(selected_accounts)
    ].copy()
    selected["pool_tier"] = selected["account_key"].map(
        lambda value: "monitor" if str(value) in monitor_accounts else "reserve"
    )
    selected["activity_eligible"] = (
        selected["hourly_activity_eligible"]
        & selected["account_key"].astype(str).isin(monitor_accounts)
    )
    selected["pool_status"] = [
        "reserve" if tier == "reserve" else (
            "active_candidate" if activity else "monitor_only"
        )
        for tier, activity in zip(selected["pool_tier"], selected["activity_eligible"])
    ]
    selected["dynamic_score"] = selected["hourly_score"]
    selected["monitor_score"] = selected["hourly_monitor_score"]
    selected["adjusted_score"] = selected["hourly_monitor_score"]
    selected = selected.sort_values(
        ["activity_eligible", "hourly_monitor_score"], ascending=[False, False]
    ).reset_index(drop=True)
    selected["rank"] = range(1, len(selected) + 1)
    return selected, {
        "monitor_accounts": len(universe.monitor_accounts),
        "reserve_accounts": len(universe.reserve_accounts),
        "selected_sleeves": len(selected),
        "coverage_products": list(universe.coverage_products),
        "product_cap_fallback_accounts": list(universe.cap_fallback_accounts),
    }


@dataclass(frozen=True)
class RoutedClient:
    account_key: str
    login: int
    route_key: str
    physical_key: str
    connection: str
    schema: str
    crm_schema: str
    server_code: int
    platform: str
    server: str
    spec: ClientSpec
    products: Mapping[str, ProductSpec] = field(default_factory=dict)


@dataclass
class MultiSourcePortfolio:
    clients: Mapping[str, RoutedClient]
    positions: dict[tuple[str, int, str], float] = field(default_factory=dict)
    position_contract_sizes: dict[tuple[str, int, str], float] = field(default_factory=dict)
    intraday_net_usd: dict[str, float] = field(default_factory=dict)
    intraday_product_net_usd: dict[str, float] = field(default_factory=dict)
    intraday_product_baseline_usd: dict[str, float] = field(default_factory=dict)
    product_realized_delta_usd: dict[str, float] = field(default_factory=dict)
    floating_pnl_usd: dict[str, float] = field(default_factory=dict)
    floating_product_pnl_usd: dict[str, float] = field(default_factory=dict)
    dynamic_evaluation_usd: dict[str, float] = field(default_factory=dict)
    product_comprehensive_pnl_usd: dict[str, float] = field(default_factory=dict)
    open_risk_by_account: dict[str, dict[str, float]] = field(default_factory=dict)
    effective_weights: dict[str, float] = field(default_factory=dict)
    effective_product_weights: dict[str, float] = field(default_factory=dict)
    cursors: dict[str, SourceCursor] = field(default_factory=dict)
    duplicate_events: int = 0
    non_trading_events: int = 0

    def __post_init__(self) -> None:
        for key, client in self.clients.items():
            self.intraday_net_usd.setdefault(key, 0.0)
            self.floating_pnl_usd.setdefault(key, 0.0)
            self.dynamic_evaluation_usd.setdefault(key, 0.0)
            self.open_risk_by_account.setdefault(key, {})
            active_base_weight = (
                sum(
                    spec.base_weight
                    for spec in client.products.values()
                    if spec.activity_eligible
                )
                if client.products
                else client.spec.base_weight
            )
            self.effective_weights.setdefault(key, active_base_weight)
            for product, spec in client.products.items():
                product_key = sleeve_key(key, product)
                self.intraday_product_net_usd.setdefault(product_key, 0.0)
                self.intraday_product_baseline_usd.setdefault(product_key, 0.0)
                self.product_realized_delta_usd.setdefault(product_key, 0.0)
                self.floating_product_pnl_usd.setdefault(product_key, 0.0)
                self.product_comprehensive_pnl_usd.setdefault(
                    product_key, spec.historical_net_20d_usd
                )
                self.effective_product_weights.setdefault(
                    product_key,
                    spec.base_weight if spec.activity_eligible else 0.0,
                )

    def replace_positions(self, rows: Iterable[Mapping[str, Any]]) -> None:
        replacement: dict[tuple[str, int, str], float] = {}
        contracts: dict[tuple[str, int, str], float] = {}
        for row in rows:
            key = str(row["account_key"])
            if key not in self.clients:
                continue
            product = normalize_source_product(row["symbol"])
            if product is None or (self.clients[key].products and product not in self.clients[key].products):
                continue
            signed = float(row["lots"])
            if abs(signed) > 1e-12:
                position_key = (key, int(row["position_id"]), product)
                replacement[position_key] = signed
                contracts[position_key] = float(
                    row.get("contract_size") or product_spec(product).contract_size
                )
        self.positions = replacement
        self.position_contract_sizes = contracts

    def replace_source_positions(self, source_key: str, rows: Iterable[Mapping[str, Any]]) -> bool:
        retained = {
            key: value
            for key, value in self.positions.items()
            if self.clients[key[0]].physical_key != source_key
        }
        retained_contracts = {
            key: value
            for key, value in self.position_contract_sizes.items()
            if self.clients[key[0]].physical_key != source_key
        }
        before = self.comparable_positions()
        self.positions = retained
        self.position_contract_sizes = retained_contracts
        for row in rows:
            key = str(row["account_key"])
            if key not in self.clients:
                continue
            product = normalize_source_product(row["symbol"])
            if product is None or (self.clients[key].products and product not in self.clients[key].products):
                continue
            signed = float(row["lots"])
            if abs(signed) > 1e-12:
                position_key = (key, int(row["position_id"]), product)
                self.positions[position_key] = signed
                self.position_contract_sizes[position_key] = float(
                    row.get("contract_size") or product_spec(product).contract_size
                )
        return before != self.comparable_positions()

    def apply_event(self, event: RoutedEvent) -> bool:
        cursor = self.cursors.get(event.source_key, SourceCursor())
        if event.cursor <= cursor:
            self.duplicate_events += 1
            return False
        self.cursors[event.source_key] = event.cursor
        if event.action not in (0, 1):
            self.non_trading_events += 1
            return False
        client = self.clients.get(event.account_key)
        if client is None:
            return False
        product = normalize_source_product(event.symbol)
        if product is None or (client.products and product not in client.products):
            return False
        key = (event.account_key, event.position_id, product)
        if client.products and product in client.products:
            self.position_contract_sizes[key] = client.products[product].source_contract_size
        else:
            self.position_contract_sizes[key] = product_spec(product).contract_size
        current = self.positions.get(key, 0.0)
        sign = 1.0 if event.action == 0 else -1.0
        if event.entry == 0:
            updated = current + sign * event.lots
        elif event.entry in (1, 3):
            updated = max(0.0, current - event.lots) if current > 0 else min(0.0, current + event.lots)
        else:
            close_lots = min(abs(current), max(0.0, event.volume_closed_lots))
            reduced = max(0.0, current - close_lots) if current > 0 else min(0.0, current + close_lots)
            updated = reduced + sign * max(0.0, event.lots - close_lots)
        if abs(updated) < 1e-12:
            self.positions.pop(key, None)
            self.position_contract_sizes.pop(key, None)
        else:
            self.positions[key] = updated
        delta = (event.profit + event.commission + event.storage + event.fee) * client.spec.money_scale
        self.intraday_net_usd[event.account_key] = self.intraday_net_usd.get(event.account_key, 0.0) + delta
        product_key = sleeve_key(event.account_key, product)
        self.intraday_product_net_usd[product_key] = (
            self.intraday_product_net_usd.get(product_key, 0.0) + delta
        )
        self.product_realized_delta_usd[product_key] = (
            self.product_realized_delta_usd.get(product_key, 0.0) + delta
        )
        self._update_weight(event.account_key)
        return True

    def set_intraday_net(self, values: Mapping[str, float]) -> None:
        for key in self.clients:
            self.intraday_net_usd[key] = float(values.get(key, 0.0))
            self._update_weight(key)

    def set_intraday_product_net(self, values: Mapping[str, float]) -> None:
        for key, client in self.clients.items():
            for product in client.products:
                product_key = sleeve_key(key, product)
                self.intraday_product_net_usd[product_key] = float(values.get(product_key, 0.0))
            self._update_weight(key)

    def set_intraday_product_baseline(self, values: Mapping[str, float]) -> None:
        for key, client in self.clients.items():
            for product in client.products:
                product_key = sleeve_key(key, product)
                self.intraday_product_baseline_usd[product_key] = float(
                    values.get(product_key, self.intraday_product_net_usd.get(product_key, 0.0))
                )
            self._update_weight(key)

    def set_open_risk(self, values: Mapping[str, Mapping[str, float]]) -> None:
        for key in self.clients:
            risk = dict(values.get(key, {}))
            floating = float(risk.get("floating_pnl_usd", 0.0))
            self.floating_pnl_usd[key] = floating
            self.open_risk_by_account[key] = {
                str(name): float(value)
                for name, value in risk.items()
                if name != "products"
            }
            products = risk.get("products", {})
            if isinstance(products, Mapping):
                for product, product_risk in products.items():
                    if not isinstance(product_risk, Mapping):
                        continue
                    product_key = sleeve_key(key, str(product))
                    self.floating_product_pnl_usd[product_key] = float(
                        product_risk.get("floating_pnl_usd", 0.0)
                    )
            self._update_weight(key)

    def _update_weight(self, key: str) -> None:
        client = self.clients[key].spec
        evaluation = min(self.intraday_net_usd.get(key, 0.0), 0.0) + min(
            self.floating_pnl_usd.get(key, 0.0), 0.0
        )
        self.dynamic_evaluation_usd[key] = evaluation
        self.effective_weights[key] = client.base_weight * intraday_multiplier(
            evaluation, client.equity_usd
        )
        routed = self.clients[key]
        if not routed.products:
            return
        account_multiplier = intraday_multiplier(evaluation, client.equity_usd)
        effective_total = 0.0
        for product, spec in routed.products.items():
            product_key = sleeve_key(key, product)
            product_evaluation = min(self.intraday_product_net_usd.get(product_key, 0.0), 0.0) + min(
                self.floating_product_pnl_usd.get(product_key, 0.0), 0.0
            )
            comprehensive = (
                spec.historical_net_20d_usd
                + self.intraday_product_net_usd.get(product_key, 0.0)
                - self.intraday_product_baseline_usd.get(product_key, 0.0)
                + self.floating_product_pnl_usd.get(product_key, 0.0)
            )
            self.product_comprehensive_pnl_usd[product_key] = comprehensive
            multiplier = min(
                account_multiplier,
                intraday_multiplier(product_evaluation, client.equity_usd),
            )
            weight = (
                spec.base_weight * multiplier
                if spec.activity_eligible and comprehensive > 0
                else 0.0
            )
            self.effective_product_weights[product_key] = weight
            effective_total += weight
        self.effective_weights[key] = effective_total

    def client_product_position(self, key: str, product: str) -> float:
        demo_contract = product_spec(product).contract_size
        return sum(
            lots * self.position_contract_sizes.get(position_key, demo_contract) / demo_contract
            for position_key, lots in self.positions.items()
            if position_key[0] == key and position_key[2] == product
        )

    def target(self, product: str, demo_equity_usd: float) -> tuple[float, float, float]:
        contributions: list[float] = []
        for key, client in self.clients.items():
            source_lots = self.client_product_position(key, product)
            if abs(source_lots) < 1e-12:
                continue
            if client.products:
                product_config = client.products.get(product)
                if product_config is None or not product_config.activity_eligible:
                    continue
                weight = self.effective_product_weights.get(
                    sleeve_key(key, product), product_config.base_weight
                )
            else:
                weight = self.effective_weights[key]
            contributions.append(
                source_lots
                * demo_equity_usd
                * weight
                / max(client.spec.equity_usd, 1.0)
            )
        gross_long = sum(max(value, 0.0) for value in contributions)
        gross_short = sum(max(-value, 0.0) for value in contributions)
        return sum(contributions), gross_long, gross_short

    def targets(self, demo_equity_usd: float) -> dict[str, tuple[float, float, float]]:
        products = {
            product
            for client in self.clients.values()
            for product in client.products
        }
        if not products:
            products = {position[2] for position in self.positions}
        return {
            product: self.target(product, demo_equity_usd)
            for product in sorted(products)
        }

    def comparable_positions(self) -> dict[tuple[str, int, str], float]:
        return {key: round(value, 8) for key, value in self.positions.items() if abs(value) > 1e-10}


class MultiSourceDatabase:
    def __init__(self, factor_service: Any | None = None) -> None:
        self.sources = {
            key: ReadOnlySource(routes) for key, routes in physical_routes().items()
        }
        self.clients: dict[str, RoutedClient] = {}
        self.clients_by_source_login: dict[str, dict[int, str]] = defaultdict(dict)
        self.factor_service = factor_service

    def connect(self) -> None:
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(source.connect): key for key, source in self.sources.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
        if errors:
            self.close()
            raise RuntimeError("All-source connection gate failed: " + "; ".join(errors))

    def close(self) -> None:
        for source in self.sources.values():
            source.close()

    def set_clients(self, clients: Mapping[str, RoutedClient]) -> None:
        self.clients = dict(clients)
        self.clients_by_source_login = defaultdict(dict)
        for key, client in clients.items():
            existing = self.clients_by_source_login[client.physical_key].get(client.login)
            if existing is not None and existing != key:
                raise RuntimeError(
                    f"Ambiguous selected login {client.login} on {client.physical_key}."
                )
            self.clients_by_source_login[client.physical_key][client.login] = key
        for source_key, source in self.sources.items():
            source.health.set_subscription_count(
                len(self.clients_by_source_login.get(source_key, {}))
            )

    @staticmethod
    def _placeholders(count: int) -> str:
        if count <= 0:
            raise ValueError("At least one login is required.")
        return ",".join(["%s"] * count)

    def _run_physical_groups(
        self,
        frame: pd.DataFrame,
        worker: Callable[[str, pd.DataFrame], Any],
        *,
        context: str,
    ) -> list[tuple[str, Any]]:
        groups = [
            (str(source_key), group.copy())
            for source_key, group in frame.groupby("physical_key", sort=True)
        ]
        if not groups:
            return []
        results: dict[str, Any] = {}
        errors: dict[str, Exception] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(groups))) as executor:
            futures = {
                executor.submit(worker, source_key, group): source_key
                for source_key, group in groups
            }
            for future in as_completed(futures):
                source_key = futures[future]
                try:
                    results[source_key] = future.result()
                except Exception as exc:
                    errors[source_key] = exc
        if errors:
            detail = "; ".join(
                f"{source_key}: {type(exc).__name__}: {exc}"
                for source_key, exc in sorted(errors.items())
            )
            first_error = errors[sorted(errors)[0]]
            raise RuntimeError(
                f"{context} failed for physical source {detail}"
            ) from first_error
        return [(source_key, results[source_key]) for source_key, _group in groups]

    def route_accounts(self) -> tuple[dict[str, dict[int, dict[str, Any]]], dict[str, int]]:
        results: dict[str, dict[int, dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        for route in ROUTES:
            source = self.sources[route.physical_key]
            rows = source.query(
                f"SELECT mt_login, status, mt_type_name FROM {route.crm_schema}.mt_users_account "
                "WHERE mt_server_code = %s",
                (route.server_code,),
            )
            mapped = {
                int(row["mt_login"]): {
                    "status": str(row.get("status") or ""),
                    "mt_type_name": str(row.get("mt_type_name") or ""),
                }
                for row in rows
            }
            results[route.key] = mapped
            counts[route.key] = len(mapped)
        return results, counts

    def _trade_feature_rows(
        self, source: ReadOnlySource, start_60: datetime, start_20: datetime, start_5: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        if source.platform == "MT5":
            sql = f"""
 SELECT Login, Symbol,
 SUM(CASE WHEN Entry IN (1,2,3) THEN 1 ELSE 0 END) AS closes,
 SUM(Profit + Commission + Storage + Fee) AS net,
 SUM(CASE WHEN Profit + Commission + Storage + Fee > 0 THEN Profit + Commission + Storage + Fee ELSE 0 END) AS gross_profit,
 -SUM(CASE WHEN Profit + Commission + Storage + Fee < 0 THEN Profit + Commission + Storage + Fee ELSE 0 END) AS gross_loss,
  SUM(CASE WHEN Entry IN (1,2,3) THEN VolumeExt / 100000000.0 ELSE 0 END) AS lots,
  MAX(ContractSize) AS source_contract_size,
 SUM(CASE WHEN MarketAsk > MarketBid AND ContractSize > 0
          THEN (MarketAsk - MarketBid) * ContractSize * (VolumeExt / 100000000.0) * GREATEST(RateProfit, 1) / 2
          ELSE 0 END) AS spread_cost
FROM {source.schema}.mt5_deals
 WHERE Time >= %s AND Time < %s AND Action IN (0,1) AND Symbol <> ''
 GROUP BY Login, Symbol
"""
            initial_shard = timedelta(days=2)
        else:
            sql = f"""
 SELECT LOGIN AS Login, SYMBOL AS Symbol, COUNT(*) AS closes,
 SUM(PROFIT + COMMISSION + SWAPS + TAXES) AS net,
 SUM(CASE WHEN PROFIT + COMMISSION + SWAPS + TAXES > 0 THEN PROFIT + COMMISSION + SWAPS + TAXES ELSE 0 END) AS gross_profit,
 -SUM(CASE WHEN PROFIT + COMMISSION + SWAPS + TAXES < 0 THEN PROFIT + COMMISSION + SWAPS + TAXES ELSE 0 END) AS gross_loss,
  SUM(VOLUME / 100.0) AS lots,
  0 AS source_contract_size,
  0 AS spread_cost
FROM {source.schema}.mt4_trades
WHERE CLOSE_TIME >= %s AND CLOSE_TIME < %s AND CLOSE_TIME > OPEN_TIME
   AND CMD IN (0,1) AND SYMBOL <> ''
 GROUP BY LOGIN, SYMBOL
"""
            initial_shard = timedelta(days=5)

        def query_shard(shard_start: datetime, shard_end: datetime) -> list[dict[str, Any]]:
            try:
                params: tuple[Any, ...]
                if source.platform == "MT5":
                    params = (shard_start, shard_end)
                else:
                    params = (shard_start, shard_end)
                return source.query(sql, params)
            except Exception:
                if shard_end - shard_start <= timedelta(hours=6):
                    raise
                midpoint = shard_start + (shard_end - shard_start) / 2
                return query_shard(shard_start, midpoint) + query_shard(midpoint, shard_end)

        totals: dict[tuple[int, str], dict[str, float]] = defaultdict(
            lambda: {
                "closes_5d": 0.0, "closes_20d": 0.0, "closes_60d": 0.0,
                "net_5d": 0.0, "net_20d": 0.0, "net_60d": 0.0,
                "gross_profit_20d": 0.0, "gross_loss_20d": 0.0,
                "lots_20d": 0.0, "observed_spread_cost_20d": 0.0,
                "source_contract_size": 0.0,
            }
        )
        periods = (
            (start_60, start_20, False, False),
            (start_20, start_5, True, False),
            (start_5, end, True, True),
        )
        for period_start, period_end, include_20, include_5 in periods:
            shard_start = period_start
            while shard_start < period_end:
                shard_end = min(period_end, shard_start + initial_shard)
                for row in query_shard(shard_start, shard_end):
                    login = int(row["Login"])
                    source_symbol = str(row.get("Symbol") or "")
                    product = normalize_source_product(source_symbol)
                    if product is None:
                        continue
                    target = totals[(login, product)]
                    target["source_contract_size"] = max(
                        target["source_contract_size"],
                        float(row.get("source_contract_size") or product_spec(product).contract_size),
                    )
                    closes = float(row.get("closes") or 0.0)
                    net = float(row.get("net") or 0.0)
                    target["closes_60d"] += closes
                    target["net_60d"] += net
                    if include_20:
                        target["closes_20d"] += closes
                        target["net_20d"] += net
                        target["gross_profit_20d"] += float(row.get("gross_profit") or 0.0)
                        target["gross_loss_20d"] += float(row.get("gross_loss") or 0.0)
                        target["lots_20d"] += float(row.get("lots") or 0.0)
                        spread_cost = float(row.get("spread_cost") or 0.0)
                        if source.platform == "MT4":
                            spread_cost = float(row.get("lots") or 0.0) * default_roundtrip_spread_usd_per_lot(product)
                        target["observed_spread_cost_20d"] += spread_cost
                    if include_5:
                        target["closes_5d"] += closes
                        target["net_5d"] += net
                shard_start = shard_end
        return [
            {
                "Login": login,
                "product": product,
                "demo_symbol": product,
                **values,
            }
            for (login, product), values in totals.items()
        ]

    def scan_trade_features(
        self, route_maps: Mapping[str, Mapping[int, Mapping[str, Any]]], as_of: datetime
    ) -> tuple[pd.DataFrame, dict[str, int]]:
        end = as_of.astimezone(BEIJING).replace(tzinfo=None)
        start_5 = end - timedelta(days=5)
        start_20 = end - timedelta(days=20)
        start_60 = end - timedelta(days=60)
        frames: list[dict[str, Any]] = []
        ambiguous_counts: dict[str, int] = {}

        def scan(source_key: str, source: ReadOnlySource) -> tuple[str, list[dict[str, Any]]]:
            return source_key, self._trade_feature_rows(source, start_60, start_20, start_5, end)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(scan, key, source): key for key, source in self.sources.items()}
            raw_by_source: dict[str, list[dict[str, Any]]] = {}
            errors: list[str] = []
            for future in as_completed(futures):
                key = futures[future]
                try:
                    source_key, rows = future.result()
                    raw_by_source[source_key] = rows
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
            if errors:
                raise RuntimeError("All-source feature scan failed: " + "; ".join(errors))

        for source_key, routes in physical_routes().items():
            login_routes: dict[int, list[LogicalRoute]] = defaultdict(list)
            for route in routes:
                for login in route_maps[route.key]:
                    login_routes[int(login)].append(route)
            ambiguous = {login for login, matches in login_routes.items() if len(matches) != 1}
            ambiguous_counts[source_key] = len(ambiguous)
            for row in raw_by_source.get(source_key, []):
                login = int(row["Login"])
                matches = login_routes.get(login, [])
                if len(matches) != 1:
                    continue
                route = matches[0]
                crm = route_maps[route.key][login]
                frames.append(
                    {
                        **row,
                        "Login": login,
                        "account_key": account_key(route.key, login),
                        "route_key": route.key,
                        "physical_key": route.physical_key,
                        "connection": route.connection,
                        "schema": route.schema,
                        "crm_schema": route.crm_schema,
                        "server_code": route.server_code,
                        "platform": route.platform,
                        "server": route.server,
                        "status": crm["status"],
                        "mt_type_name": crm["mt_type_name"],
                    }
                )
        return pd.DataFrame(frames), ambiguous_counts

    def refresh_hourly_universe(
        self,
        universe: pd.DataFrame,
        *,
        build_as_of: datetime,
        as_of: datetime | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Refresh cached factor-ready sleeves without re-reading 60-day history."""
        as_of = as_of or datetime.now(timezone.utc)
        if build_as_of.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("Hourly discovery timestamps must be timezone-aware.")
        if as_of < build_as_of:
            raise ValueError("Hourly discovery cannot run before the daily build timestamp.")
        if "factor_ready" not in universe.columns:
            raise ValueError("Hourly discovery requires cached factor_ready evidence.")
        candidates = universe.loc[
            universe["factor_ready"].fillna(False).astype(bool)
        ].copy()
        if candidates.empty:
            return rank_hourly_universe(candidates)

        end = as_of.astimezone(BEIJING).replace(tzinfo=None)
        start_1h = end - timedelta(hours=1)
        start_4h = end - timedelta(hours=4)
        build_local = build_as_of.astimezone(BEIJING).replace(tzinfo=None)
        query_start = min(start_4h, build_local)
        recent: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "recent_net_1h_usd": 0.0,
                "recent_net_4h_usd": 0.0,
                "closed_delta_since_build_usd": 0.0,
            }
        )
        unique_accounts = candidates.drop_duplicates("account_key")
        scales = {
            str(row.account_key): float(row.money_scale)
            for row in unique_accounts.itertuples()
        }
        for source_key, group in unique_accounts.groupby("physical_key"):
            source = self.sources[str(source_key)]
            by_login = {int(row.Login): str(row.account_key) for row in group.itertuples()}
            for batch in _chunks(sorted(by_login)):
                placeholders = self._placeholders(len(batch))
                if source.platform == "MT5":
                    rows = source.query(
                        f"SELECT Login, Symbol, "
                        f"SUM(CASE WHEN Time >= %s THEN Profit + Commission + Storage + Fee ELSE 0 END) AS net_1h, "
                        f"SUM(CASE WHEN Time >= %s THEN Profit + Commission + Storage + Fee ELSE 0 END) AS net_4h, "
                        f"SUM(CASE WHEN Time >= %s THEN Profit + Commission + Storage + Fee ELSE 0 END) AS net_since_build "
                        f"FROM {source.schema}.mt5_deals WHERE Login IN ({placeholders}) "
                        f"AND Time >= %s AND Time < %s AND Action IN (0,1) AND Symbol <> '' "
                        f"GROUP BY Login, Symbol",
                        (start_1h, start_4h, build_local, *batch, query_start, end),
                    )
                else:
                    rows = source.query(
                        f"SELECT LOGIN AS Login, SYMBOL AS Symbol, "
                        f"SUM(CASE WHEN CLOSE_TIME >= %s THEN PROFIT + COMMISSION + SWAPS + TAXES ELSE 0 END) AS net_1h, "
                        f"SUM(CASE WHEN CLOSE_TIME >= %s THEN PROFIT + COMMISSION + SWAPS + TAXES ELSE 0 END) AS net_4h, "
                        f"SUM(CASE WHEN CLOSE_TIME >= %s THEN PROFIT + COMMISSION + SWAPS + TAXES ELSE 0 END) AS net_since_build "
                        f"FROM {source.schema}.mt4_trades WHERE LOGIN IN ({placeholders}) "
                        f"AND CLOSE_TIME >= %s AND CLOSE_TIME < %s AND CLOSE_TIME > OPEN_TIME "
                        f"AND CMD IN (0,1) AND SYMBOL <> '' GROUP BY LOGIN, SYMBOL",
                        (start_1h, start_4h, build_local, *batch, query_start, end),
                    )
                for item in rows:
                    product = normalize_source_product(item.get("Symbol"))
                    account = by_login.get(int(item["Login"]))
                    if product is None or account is None:
                        continue
                    key = sleeve_key(account, product)
                    scale = scales[account]
                    recent[key]["recent_net_1h_usd"] += float(item.get("net_1h") or 0.0) * scale
                    recent[key]["recent_net_4h_usd"] += float(item.get("net_4h") or 0.0) * scale
                    recent[key]["closed_delta_since_build_usd"] += float(item.get("net_since_build") or 0.0) * scale

        account_frame = candidates.drop_duplicates("account_key")
        profiles = self.current_profiles(account_frame)
        product_positions = self.current_product_positions(account_frame, as_of)
        profile_rows: list[dict[str, float | str]] = []
        for row in profiles.itertuples():
            account = str(row.account_key)
            scale = scales[account]
            equity = float(row.Equity or 0.0) * scale
            margin = float(row.Margin or 0.0) * scale
            floating = float(row.Profit or 0.0) * scale
            profile_rows.append({
                "account_key": account,
                "current_equity_usd": equity,
                "current_margin_to_equity": margin / equity if equity > 0 else float("inf"),
                "current_floating_loss_ratio": max(-floating, 0.0) / equity if equity > 0 else float("inf"),
            })
        refreshed = candidates.merge(
            pd.DataFrame(profile_rows), on="account_key", how="left", validate="many_to_one"
        )
        if product_positions.empty:
            product_positions = pd.DataFrame(columns=[
                "account_key", "product", "current_product_floating_pnl_raw",
                "current_product_hedge_ratio",
            ])
        else:
            product_positions = product_positions.copy()
            product_positions["current_product_hedge_ratio"] = (
                1.0 - product_positions["product_open_net_lots"].abs()
                / product_positions["product_open_gross_lots"].replace(0, float("nan"))
            ).fillna(0.0).clip(0.0, 1.0)
            product_positions = product_positions.rename(columns={
                "product_floating_pnl": "current_product_floating_pnl_raw",
            })
        refreshed = refreshed.merge(
            product_positions[[
                "account_key", "product", "current_product_floating_pnl_raw",
                "current_product_hedge_ratio",
            ]],
            on=["account_key", "product"], how="left", validate="one_to_one",
        )
        refreshed["current_product_floating_pnl_usd"] = [
            float(value or 0.0) * scales[str(account)]
            for account, value in zip(
                refreshed["account_key"], refreshed["current_product_floating_pnl_raw"]
            )
        ]
        refreshed["current_open_risk_multiplier"] = [
            open_risk_multiplier(float(loss), float(margin), float(hedge or 0.0))
            for loss, margin, hedge in zip(
                refreshed["current_floating_loss_ratio"],
                refreshed["current_margin_to_equity"],
                refreshed["current_product_hedge_ratio"],
            )
        ]
        for column in (
            "recent_net_1h_usd", "recent_net_4h_usd", "closed_delta_since_build_usd",
        ):
            refreshed[column] = refreshed["sleeve_key"].map(
                lambda key, name=column: recent.get(str(key), {}).get(name, 0.0)
            )
        selected, metadata = rank_hourly_universe(refreshed)
        metadata.update({
            "as_of": as_of.astimezone(BEIJING).isoformat(),
            "build_as_of": build_as_of.astimezone(BEIJING).isoformat(),
            "factor_ready_sleeves_scanned": len(refreshed),
        })
        return selected, metadata

    def current_profiles(self, frame: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for source_key, group in frame.groupby("physical_key"):
            source = self.sources[str(source_key)]
            route_by_login = {int(row.Login): row for row in group.itertuples()}
            logins = sorted(route_by_login)
            for batch in _chunks(logins):
                placeholders = self._placeholders(len(batch))
                if source.platform == "MT5":
                    result = source.query(
                        f"SELECT a.Login, a.Balance, a.Credit, a.Equity, a.Profit, a.Margin, a.MarginLevel, u.`Group` AS account_group "
                        f"FROM {source.schema}.mt5_accounts a JOIN {source.schema}.mt5_users_view u ON u.Login = a.Login "
                        f"WHERE a.Login IN ({placeholders})",
                        batch,
                    )
                    for item in result:
                        original = route_by_login[int(item["Login"])]
                        rows.append({
                            "account_key": original.account_key,
                            "Balance": item.get("Balance", 0), "Credit": item.get("Credit", 0),
                            "Equity": item.get("Equity", 0), "Profit": item.get("Profit", 0),
                            "Margin": item.get("Margin", 0), "MarginLevel": item.get("MarginLevel", 0),
                            "account_group": item.get("account_group", ""), "Currency": "",
                        })
                else:
                    result = source.query(
                        f"SELECT LOGIN AS Login, BALANCE AS Balance, CREDIT AS Credit, EQUITY AS Equity, "
                        f"(EQUITY - BALANCE - CREDIT) AS Profit, MARGIN AS Margin, MARGIN_LEVEL AS MarginLevel, "
                        f"`GROUP` AS account_group, CURRENCY AS Currency FROM {source.schema}.mt4_users_view "
                        f"WHERE LOGIN IN ({placeholders})",
                        batch,
                    )
                    for item in result:
                        original = route_by_login[int(item["Login"])]
                        rows.append({"account_key": original.account_key, **{k: v for k, v in item.items() if k != "Login"}})
        return pd.DataFrame(rows)

    def current_open_positions(self, frame: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        as_of_epoch = int(as_of.timestamp())
        for source_key, group in frame.groupby("physical_key"):
            source = self.sources[str(source_key)]
            route_by_login = {int(row.Login): row for row in group.itertuples()}
            for batch in _chunks(sorted(route_by_login)):
                placeholders = self._placeholders(len(batch))
                if source.platform == "MT5":
                    result = source.query(
                        f"SELECT Login, COUNT(*) AS open_position_count, "
                        f"SUM(VolumeExt) / 100000000.0 AS open_gross_lots, "
                        f"SUM(CASE WHEN Symbol LIKE 'XAUUSD%%' THEN VolumeExt ELSE 0 END) / 100000000.0 AS xau_gross_lots, "
                        f"SUM(CASE WHEN Symbol LIKE 'XAUUSD%%' THEN "
                        f"CASE WHEN Action=0 THEN VolumeExt ELSE -VolumeExt END ELSE 0 END) / 100000000.0 AS xau_net_lots, "
                        f"UNIX_TIMESTAMP(MIN(TimeCreate)) AS oldest_open_epoch, SUM(Profit + Storage) AS position_floating "
                        f"FROM {source.schema}.mt5_positions WHERE Login IN ({placeholders}) GROUP BY Login",
                        batch,
                    )
                else:
                    result = source.query(
                        f"SELECT LOGIN AS Login, COUNT(*) AS open_position_count, "
                        f"SUM(VOLUME) / 100.0 AS open_gross_lots, "
                        f"SUM(CASE WHEN SYMBOL LIKE 'XAUUSD%%' THEN VOLUME ELSE 0 END) / 100.0 AS xau_gross_lots, "
                        f"SUM(CASE WHEN SYMBOL LIKE 'XAUUSD%%' THEN CASE WHEN CMD=0 THEN VOLUME ELSE -VOLUME END ELSE 0 END) / 100.0 AS xau_net_lots, "
                        f"UNIX_TIMESTAMP(MIN(OPEN_TIME)) AS oldest_open_epoch, "
                        f"SUM(PROFIT + COMMISSION + SWAPS + TAXES) AS position_floating "
                        f"FROM {source.schema}.mt4_trades WHERE LOGIN IN ({placeholders}) AND CMD IN (0,1) "
                        f"AND CLOSE_TIME = '1970-01-01 00:00:00' GROUP BY LOGIN",
                        batch,
                    )
                for item in result:
                    original = route_by_login[int(item["Login"])]
                    oldest_epoch = int(item.get("oldest_open_epoch") or as_of_epoch)
                    rows.append({
                        "account_key": original.account_key,
                        "open_position_count": int(item.get("open_position_count") or 0),
                        "open_gross_lots": float(item.get("open_gross_lots") or 0.0),
                        "xau_gross_lots": float(item.get("xau_gross_lots") or 0.0),
                        "xau_net_lots": float(item.get("xau_net_lots") or 0.0),
                        "oldest_open_seconds": float(max(0, as_of_epoch - oldest_epoch)),
                        "position_floating": float(item.get("position_floating") or 0.0),
                    })
        return pd.DataFrame(rows, columns=[
            "account_key", "open_position_count", "open_gross_lots", "xau_gross_lots",
            "xau_net_lots", "oldest_open_seconds", "position_floating",
        ])

    def current_product_positions(self, frame: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
        rows: dict[tuple[str, str], dict[str, float | str]] = {}
        as_of_epoch = int(as_of.timestamp())
        unique = frame.drop_duplicates("account_key")
        for source_key, group in unique.groupby("physical_key"):
            source = self.sources[str(source_key)]
            route_by_login = {int(row.Login): row for row in group.itertuples()}
            for batch in _chunks(sorted(route_by_login)):
                placeholders = self._placeholders(len(batch))
                if source.platform == "MT5":
                    result = source.query(
                        f"SELECT Login, Symbol, COUNT(*) AS position_count, "
                        f"SUM(VolumeExt) / 100000000.0 AS gross_lots, "
                        f"SUM(CASE WHEN Action=0 THEN VolumeExt ELSE -VolumeExt END) / 100000000.0 AS net_lots, "
                        f"UNIX_TIMESTAMP(MIN(TimeCreate)) AS oldest_open_epoch, "
                        f"SUM(Profit + Storage) AS floating_pnl, MAX(ContractSize) AS source_contract_size "
                        f"FROM {source.schema}.mt5_positions WHERE Login IN ({placeholders}) "
                        f"GROUP BY Login, Symbol",
                        batch,
                    )
                else:
                    result = source.query(
                        f"SELECT LOGIN AS Login, SYMBOL AS Symbol, COUNT(*) AS position_count, "
                        f"SUM(VOLUME) / 100.0 AS gross_lots, "
                        f"SUM(CASE WHEN CMD=0 THEN VOLUME ELSE -VOLUME END) / 100.0 AS net_lots, "
                        f"UNIX_TIMESTAMP(MIN(OPEN_TIME)) AS oldest_open_epoch, "
                        f"SUM(PROFIT + COMMISSION + SWAPS + TAXES) AS floating_pnl, "
                        f"0 AS source_contract_size "
                        f"FROM {source.schema}.mt4_trades WHERE LOGIN IN ({placeholders}) "
                        f"AND CMD IN (0,1) AND CLOSE_TIME = '1970-01-01 00:00:00' "
                        f"GROUP BY LOGIN, SYMBOL",
                        batch,
                    )
                for item in result:
                    product = normalize_source_product(item.get("Symbol"))
                    if product is None:
                        continue
                    original = route_by_login[int(item["Login"])]
                    key = (str(original.account_key), product)
                    target = rows.setdefault(key, {
                        "account_key": str(original.account_key),
                        "product": product,
                        "product_open_position_count": 0.0,
                        "product_open_gross_lots": 0.0,
                        "product_open_net_lots": 0.0,
                        "product_oldest_open_seconds": 0.0,
                        "product_floating_pnl": 0.0,
                        "open_source_contract_size": product_spec(product).contract_size,
                    })
                    target["product_open_position_count"] = float(target["product_open_position_count"]) + float(item.get("position_count") or 0)
                    target["product_open_gross_lots"] = float(target["product_open_gross_lots"]) + float(item.get("gross_lots") or 0.0)
                    target["product_open_net_lots"] = float(target["product_open_net_lots"]) + float(item.get("net_lots") or 0.0)
                    target["product_oldest_open_seconds"] = max(
                        float(target["product_oldest_open_seconds"]),
                        float(max(0, as_of_epoch - int(item.get("oldest_open_epoch") or as_of_epoch))),
                    )
                    target["product_floating_pnl"] = float(target["product_floating_pnl"]) + float(item.get("floating_pnl") or 0.0)
                    target["open_source_contract_size"] = max(
                        float(target["open_source_contract_size"]),
                        float(item.get("source_contract_size") or product_spec(product).contract_size),
                    )
        return pd.DataFrame(rows.values(), columns=[
            "account_key", "product", "product_open_position_count",
            "product_open_gross_lots", "product_open_net_lots",
            "product_oldest_open_seconds", "product_floating_pnl",
            "open_source_contract_size",
        ])

    def selected_open_risk(self, as_of: datetime | None = None) -> dict[str, dict[str, float]]:
        as_of = as_of or datetime.now(timezone.utc)
        if not self.clients:
            return {}
        frame = pd.DataFrame([
            {
                "account_key": client.account_key,
                "Login": client.login,
                "physical_key": client.physical_key,
            }
            for client in self.clients.values()
        ])
        profiles = self.current_profiles(frame)
        positions = self.current_open_positions(frame, as_of)
        product_positions = self.current_product_positions(frame, as_of)
        merged = profiles.merge(positions, on="account_key", how="left", validate="one_to_one")
        position_columns = [
            "open_position_count", "open_gross_lots", "xau_gross_lots", "xau_net_lots",
            "oldest_open_seconds", "position_floating",
        ]
        for column in position_columns:
            merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0.0)
        output: dict[str, dict[str, float]] = {}
        for row in merged.itertuples():
            client = self.clients[str(row.account_key)]
            scale = client.spec.money_scale
            equity = float(row.Equity or 0.0) * scale
            margin = float(row.Margin or 0.0) * scale
            floating = float(row.Profit or 0.0) * scale
            xau_gross = float(row.xau_gross_lots)
            xau_net = float(row.xau_net_lots)
            output[str(row.account_key)] = {
                "floating_pnl_usd": floating,
                "position_floating_usd": float(row.position_floating) * scale,
                "open_position_count": float(row.open_position_count),
                "open_gross_lots": float(row.open_gross_lots),
                "xau_gross_lots": xau_gross,
                "xau_net_lots": xau_net,
                "xau_hedge_ratio": 0.0 if xau_gross <= 0 else max(0.0, 1.0 - abs(xau_net) / xau_gross),
                "oldest_open_seconds": float(row.oldest_open_seconds),
                "equity_usd": equity,
                "margin_to_equity": margin / equity if equity > 0 else float("inf"),
                "floating_loss_ratio": max(-floating, 0.0) / equity if equity > 0 else float("inf"),
                "products": {},
            }
        for row in product_positions.itertuples():
            account = str(row.account_key)
            client = self.clients.get(account)
            if client is None or str(row.product) not in client.products:
                continue
            output[account]["products"][str(row.product)] = {
                "floating_pnl_usd": float(row.product_floating_pnl) * client.spec.money_scale,
                "position_count": float(row.product_open_position_count),
                "gross_lots": float(row.product_open_gross_lots),
                "net_lots": float(row.product_open_net_lots),
                "oldest_open_seconds": float(row.product_oldest_open_seconds),
                "source_contract_size": float(row.open_source_contract_size),
            }
        return output

    def risk_history(self, frame: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
        results = self._run_physical_groups(
            frame,
            lambda _source_key, group: self._risk_history_serial(group, as_of),
            context="risk history",
        )
        frames = [result for _source_key, result in results if not result.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _risk_history_serial(self, frame: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        start = as_of.astimezone(BEIJING).replace(tzinfo=None) - timedelta(days=60)
        start_unix = int(start.replace(tzinfo=BEIJING).astimezone(timezone.utc).timestamp())
        for source_key, group in frame.groupby("physical_key"):
            source = self.sources[str(source_key)]
            route_by_login = {int(row.Login): row for row in group.itertuples()}
            batch_size = 10 if source.platform == "MT5" else 50

            def query_batch(batch: Sequence[int]) -> list[dict[str, Any]]:
                placeholders = self._placeholders(len(batch))
                try:
                    if source.platform == "MT5":
                        return source.query(
                            f"SELECT Login, MIN(Balance) AS min_balance_60d, "
                            f"MIN(Balance + Credit + Profit) AS min_equity_60d, "
                            f"MIN(CASE WHEN Margin > 0 THEN MarginLevel ELSE NULL END) AS min_margin_level_60d, "
                            f"SUM(CASE WHEN Balance < 0 THEN 1 ELSE 0 END) AS negative_balance_days_60d, "
                            f"SUM(CASE WHEN Balance + Credit + Profit < 0 THEN 1 ELSE 0 END) AS negative_equity_days_60d, "
                            f"SUM(CASE WHEN ABS(DailySOCompensation) + ABS(DailySOCompensationCredit) > 0 THEN 1 ELSE 0 END) AS so_compensation_days_60d "
                            f"FROM {source.schema}.mt5_daily_view WHERE Login IN ({placeholders}) AND Datetime >= %s GROUP BY Login",
                            (*batch, start_unix),
                        )
                    return source.query(
                        f"SELECT LOGIN AS Login, MIN(BALANCE) AS min_balance_60d, MIN(EQUITY) AS min_equity_60d, "
                        f"MIN(CASE WHEN MARGIN > 0 THEN EQUITY / MARGIN * 100 ELSE NULL END) AS min_margin_level_60d, "
                        f"SUM(CASE WHEN BALANCE < 0 THEN 1 ELSE 0 END) AS negative_balance_days_60d, "
                        f"SUM(CASE WHEN EQUITY < 0 THEN 1 ELSE 0 END) AS negative_equity_days_60d, 0 AS so_compensation_days_60d "
                        f"FROM {source.schema}.mt4_daily WHERE LOGIN IN ({placeholders}) AND TIME >= %s GROUP BY LOGIN",
                        (*batch, start),
                    )
                except Exception:
                    if len(batch) <= 1:
                        raise
                    midpoint = len(batch) // 2
                    return query_batch(batch[:midpoint]) + query_batch(batch[midpoint:])

            for batch in _chunks(sorted(route_by_login), size=batch_size):
                result = query_batch(batch)
                for item in result:
                    original = route_by_login[int(item["Login"])]
                    rows.append({"account_key": original.account_key, **{k: v for k, v in item.items() if k != "Login"}})
        return pd.DataFrame(rows)

    def holding_statistics(
        self, frame: pd.DataFrame, as_of: datetime
    ) -> dict[str, dict[str, float]]:
        results = self._run_physical_groups(
            frame.drop_duplicates("account_key"),
            lambda _source_key, group: self._holding_statistics_serial(group, as_of),
            context="holding statistics",
        )
        output: dict[str, dict[str, float]] = {}
        for _source_key, values in results:
            output.update(values)
        return output

    def _holding_statistics_serial(
        self, frame: pd.DataFrame, as_of: datetime
    ) -> dict[str, dict[str, float]]:
        output: dict[str, dict[str, float]] = {}
        start = as_of.astimezone(BEIJING).replace(tzinfo=None) - timedelta(days=20)
        unique = frame.drop_duplicates("account_key")
        for source_key, group in unique.groupby("physical_key"):
            source = self.sources[str(source_key)]
            route_by_login = {int(row.Login): row for row in group.itertuples()}
            holds: dict[tuple[int, str], list[float]] = defaultdict(list)

            def query_mt5_window(
                batch: Sequence[int], window_start: datetime, window_end: datetime
            ) -> list[dict[str, Any]]:
                placeholders = self._placeholders(len(batch))
                try:
                    return source.query(
                        f"SELECT Login, PositionID, Symbol, "
                        f"MIN(CASE WHEN Entry=0 THEN TimeMsc END) AS opened_at, "
                        f"MAX(CASE WHEN Entry IN (1,2,3) THEN TimeMsc END) AS closed_at "
                        f"FROM {source.schema}.mt5_deals WHERE Login IN ({placeholders}) "
                        f"AND Time >= %s AND Time < %s AND Action IN (0,1) "
                        f"AND Symbol <> '' GROUP BY Login, PositionID, Symbol",
                        (*batch, window_start, window_end),
                    )
                except Exception:
                    if len(batch) > 1:
                        midpoint = len(batch) // 2
                        return query_mt5_window(
                            batch[:midpoint], window_start, window_end
                        ) + query_mt5_window(
                            batch[midpoint:], window_start, window_end
                        )
                    if window_end - window_start <= timedelta(hours=6):
                        raise
                    midpoint = window_start + (window_end - window_start) / 2
                    return query_mt5_window(batch, window_start, midpoint) + query_mt5_window(
                        batch, midpoint, window_end
                    )

            def query_mt5_sharded(batch: Sequence[int]) -> list[dict[str, Any]]:
                positions: dict[tuple[int, int, str], dict[str, Any]] = {}
                window_start = start
                end = as_of.astimezone(BEIJING).replace(tzinfo=None)
                while window_start < end:
                    window_end = min(end, window_start + timedelta(days=5))
                    for item in query_mt5_window(batch, window_start, window_end):
                        key = (
                            int(item["Login"]),
                            int(item["PositionID"]),
                            str(item.get("Symbol") or ""),
                        )
                        current = positions.setdefault(
                            key,
                            {
                                "Login": key[0],
                                "PositionID": key[1],
                                "Symbol": key[2],
                                "opened_at": None,
                                "closed_at": None,
                            },
                        )
                        opened = item.get("opened_at")
                        closed = item.get("closed_at")
                        if opened is not None and (
                            current["opened_at"] is None or opened < current["opened_at"]
                        ):
                            current["opened_at"] = opened
                        if closed is not None and (
                            current["closed_at"] is None or closed > current["closed_at"]
                        ):
                            current["closed_at"] = closed
                    window_start = window_end
                result: list[dict[str, Any]] = []
                for item in positions.values():
                    opened = item["opened_at"]
                    closed = item["closed_at"]
                    if opened is None or closed is None:
                        continue
                    hold_seconds = (closed - opened).total_seconds()
                    if hold_seconds >= 0:
                        result.append({**item, "hold_seconds": hold_seconds})
                return result

            def query_mt4_window(
                login: int, window_start: datetime, window_end: datetime
            ) -> list[dict[str, Any]]:
                try:
                    return source.query(
                        f"SELECT LOGIN AS Login, TICKET AS PositionID, SYMBOL AS Symbol, "
                        f"TIMESTAMPDIFF(MICROSECOND, OPEN_TIME, CLOSE_TIME) / 1000000.0 AS hold_seconds "
                        f"FROM {source.schema}.mt4_trades WHERE LOGIN = %s "
                        f"AND CLOSE_TIME >= %s AND CLOSE_TIME < %s AND CLOSE_TIME > OPEN_TIME "
                        f"AND CMD IN (0,1) AND SYMBOL <> ''",
                        (login, window_start, window_end),
                    )
                except Exception:
                    if window_end - window_start <= timedelta(hours=6):
                        raise
                    midpoint = window_start + (window_end - window_start) / 2
                    return query_mt4_window(login, window_start, midpoint) + query_mt4_window(
                        login, midpoint, window_end
                    )

            def query_single_mt4(login: int) -> list[dict[str, Any]]:
                result: list[dict[str, Any]] = []
                window_start = start
                end = as_of.astimezone(BEIJING).replace(tzinfo=None)
                while window_start < end:
                    window_end = min(end, window_start + timedelta(days=5))
                    result.extend(query_mt4_window(login, window_start, window_end))
                    window_start = window_end
                return result

            def query_batch(batch: Sequence[int]) -> list[dict[str, Any]]:
                placeholders = self._placeholders(len(batch))
                if source.platform == "MT5":
                    return query_mt5_sharded(batch)
                try:
                    return source.query(
                        f"SELECT LOGIN AS Login, TICKET AS PositionID, SYMBOL AS Symbol, TIMESTAMPDIFF(MICROSECOND, OPEN_TIME, CLOSE_TIME) / 1000000.0 AS hold_seconds "
                        f"FROM {source.schema}.mt4_trades WHERE LOGIN IN ({placeholders}) AND CLOSE_TIME >= %s "
                        f"AND CLOSE_TIME > OPEN_TIME AND CMD IN (0,1) AND SYMBOL <> ''",
                        (*batch, start),
                    )
                except Exception:
                    if len(batch) > 1:
                        midpoint = len(batch) // 2
                        return query_batch(batch[:midpoint]) + query_batch(batch[midpoint:])
                    login = int(batch[0])
                    return query_single_mt4(login)

            for batch in _chunks(sorted(route_by_login), size=10 if source.platform == "MT5" else 50):
                result = query_batch(batch)
                for item in result:
                    value = float(item.get("hold_seconds") or 0.0)
                    product = normalize_source_product(item.get("Symbol"))
                    if product is not None and math.isfinite(value) and value >= 0:
                        holds[(int(item["Login"]), product)].append(value)
            for (login, product), values in holds.items():
                series = pd.Series(values, dtype=float)
                output[sleeve_key(str(route_by_login[login].account_key), product)] = {
                    "hold_p25_seconds": float(series.quantile(0.25)),
                    "median_hold_seconds": float(series.median()),
                    "hold_p90_seconds": float(series.quantile(0.90)),
                    "short_trade_ratio": float((series <= 10.0).mean()),
                    "holding_samples": float(len(series)),
                }
        return output

    def holding_medians(self, frame: pd.DataFrame, as_of: datetime) -> dict[str, float]:
        return {
            key: values["median_hold_seconds"]
            for key, values in self.holding_statistics(frame, as_of).items()
        }

    def build_pool(self, as_of: datetime | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
        build_started = time.perf_counter()
        build_stage_seconds: dict[str, float] = {}
        as_of = as_of or datetime.now(timezone.utc)
        stage_started = time.perf_counter()
        route_maps, route_counts = self.route_accounts()
        build_stage_seconds["route_accounts"] = time.perf_counter() - stage_started
        stage_started = time.perf_counter()
        features, ambiguous = self.scan_trade_features(route_maps, as_of)
        build_stage_seconds["trade_feature_scan"] = time.perf_counter() - stage_started
        if features.empty:
            raise RuntimeError("No supported account-product candidates were returned by the all-source scan.")
        account_frame = features.drop_duplicates("account_key")
        stage_started = time.perf_counter()
        profiles = self.current_profiles(account_frame)
        frame = features.merge(profiles, on="account_key", how="inner", validate="many_to_one")
        open_positions = self.current_open_positions(account_frame, as_of)
        frame = frame.merge(open_positions, on="account_key", how="left", validate="many_to_one")
        product_positions = self.current_product_positions(account_frame, as_of)
        frame = frame.merge(
            product_positions,
            on=["account_key", "product"],
            how="left",
            validate="one_to_one",
        )
        build_stage_seconds["current_state"] = time.perf_counter() - stage_started
        numeric = [
            "closes_5d", "closes_20d", "closes_60d", "net_5d", "net_20d", "net_60d",
            "gross_profit_20d", "gross_loss_20d", "lots_20d", "observed_spread_cost_20d",
            "source_contract_size",
            "Balance", "Credit", "Equity", "Profit", "Margin", "MarginLevel",
            "open_position_count", "open_gross_lots", "xau_gross_lots", "xau_net_lots",
            "oldest_open_seconds", "position_floating",
            "product_open_position_count", "product_open_gross_lots", "product_open_net_lots",
            "product_oldest_open_seconds", "product_floating_pnl", "open_source_contract_size",
        ]
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        frame["source_contract_size"] = frame["source_contract_size"].where(
            frame["source_contract_size"] > 0,
            frame["open_source_contract_size"],
        )
        frame["demo_contract_size"] = frame["product"].map(
            lambda product: product_spec(str(product)).contract_size
        )
        frame["source_contract_size"] = frame["source_contract_size"].where(
            frame["source_contract_size"] > 0,
            frame["demo_contract_size"],
        )
        frame["money_scale"] = [
            0.01 if _is_cent(row.Currency, row.account_group, row.mt_type_name) else 1.0
            for row in frame.itertuples()
        ]
        for column in (
            "net_5d", "net_20d", "net_60d", "gross_profit_20d", "gross_loss_20d",
            "observed_spread_cost_20d", "Balance", "Credit", "Equity", "Profit",
            "Margin", "position_floating",
        ):
            frame[f"{column}_usd"] = frame[column] * frame["money_scale"]
        frame["product_floating_pnl_usd"] = frame["product_floating_pnl"] * frame["money_scale"]
        frame["equity_pre_usd"] = frame["Equity_usd"].where(frame["Equity_usd"] > 0, frame["Balance_usd"] + frame["Credit_usd"] + frame["Profit_usd"])
        frame["floating_pnl_usd"] = frame["Profit_usd"]
        frame["floating_loss_usd"] = (-frame["floating_pnl_usd"]).clip(lower=0.0)
        frame["floating_loss_ratio"] = frame["floating_loss_usd"] / frame["equity_pre_usd"].replace(0, float("nan"))
        frame["margin_to_equity"] = frame["Margin_usd"] / frame["equity_pre_usd"].replace(0, float("nan"))
        frame["xau_hedge_ratio"] = (
            1.0 - frame["xau_net_lots"].abs() / frame["xau_gross_lots"].replace(0, float("nan"))
        ).fillna(0.0).clip(0.0, 1.0)
        frame["product_hedge_ratio"] = (
            1.0 - frame["product_open_net_lots"].abs()
            / frame["product_open_gross_lots"].replace(0, float("nan"))
        ).fillna(0.0).clip(0.0, 1.0)

        # Product-level comprehensive P/L is the first candidate gate.
        frame["comprehensive_net_5d_usd"] = frame["net_5d_usd"] + frame["product_floating_pnl_usd"]
        frame["comprehensive_net_20d_usd"] = frame["net_20d_usd"] + frame["product_floating_pnl_usd"]
        frame["quality_net_5d_usd"] = frame["comprehensive_net_5d_usd"]
        frame["quality_net_20d_usd"] = frame["comprehensive_net_20d_usd"]
        frame["pf_20d"] = (
            frame["gross_profit_20d_usd"]
            / frame["gross_loss_20d_usd"].replace(0, float("nan"))
        ).fillna(3.0).clip(upper=3.0)
        frame["stress_net_15x_20d_usd"] = frame["net_20d_usd"] - 0.5 * frame["observed_spread_cost_20d_usd"]
        frame["quality_stress_net_15x_20d_usd"] = (
            frame["stress_net_15x_20d_usd"] + frame["product_floating_pnl_usd"]
        )
        frame["ret_5d"] = frame["quality_net_5d_usd"] / frame["equity_pre_usd"].replace(0, float("nan"))
        frame["ret_20d"] = frame["quality_net_20d_usd"] / frame["equity_pre_usd"].replace(0, float("nan"))
        frame["stress_ret_20d"] = frame["quality_stress_net_15x_20d_usd"] / frame["equity_pre_usd"].replace(0, float("nan"))
        frame["stress_survival"] = (
            frame["quality_stress_net_15x_20d_usd"]
            / frame["quality_net_20d_usd"].replace(0, float("nan"))
        ).clip(-1.0, 1.0)

        positive_comprehensive = frame.loc[
            frame["comprehensive_net_20d_usd"] > 0
        ].copy()
        preliminary = positive_comprehensive.loc[
            (positive_comprehensive["equity_pre_usd"] >= 100)
            & (positive_comprehensive["closes_5d"] >= 5)
            & (positive_comprehensive["closes_20d"] >= 20)
            & (positive_comprehensive["quality_net_5d_usd"] > 0)
            & (positive_comprehensive["quality_net_20d_usd"] > 0)
            & (positive_comprehensive["quality_stress_net_15x_20d_usd"] > 0)
            & (positive_comprehensive["pf_20d"] >= 1.05)
        ].copy()
        if preliminary.empty:
            raise RuntimeError("No account-product sleeves passed the comprehensive-profit and quality gates.")
        preliminary["pre_rank"] = (
            0.40 * _percentile_rank(_winsorize(preliminary["ret_5d"]))
            + 0.35 * _percentile_rank(_winsorize(preliminary["ret_20d"]))
            + 0.25 * _percentile_rank(_winsorize(preliminary["stress_ret_20d"]))
        )

        stage_started = time.perf_counter()
        risk = self.risk_history(preliminary.drop_duplicates("account_key"), as_of)
        build_stage_seconds["risk_history"] = time.perf_counter() - stage_started
        checked = preliminary.merge(risk, on="account_key", how="left", validate="many_to_one")
        for column in (
            "min_balance_60d", "min_equity_60d", "min_margin_level_60d",
            "negative_balance_days_60d", "negative_equity_days_60d", "so_compensation_days_60d",
        ):
            checked[column] = pd.to_numeric(checked[column], errors="coerce")
        checked["risk_history_complete"] = checked[["min_balance_60d", "min_equity_60d"]].notna().all(axis=1)
        checked["hard_gate"] = (
            checked["risk_history_complete"]
            & (checked["negative_balance_days_60d"].fillna(1) == 0)
            & (checked["negative_equity_days_60d"].fillna(1) == 0)
            & (checked["so_compensation_days_60d"].fillna(1) == 0)
            & (checked["min_margin_level_60d"].isna() | (checked["min_margin_level_60d"] >= 80))
            & (checked["floating_loss_ratio"].fillna(float("inf")) < MAX_BUILD_FLOATING_LOSS_RATIO)
            & (checked["margin_to_equity"].fillna(float("inf")) < MAX_BUILD_MARGIN_TO_EQUITY)
        )
        eligible = checked.loc[checked["hard_gate"]].copy()
        if eligible["account_key"].nunique() < 10:
            raise RuntimeError(
                f"Only {eligible['account_key'].nunique()} accounts passed complete hard risk gates; need at least 10."
            )
        eligible["score_recent"] = _percentile_rank(_winsorize(eligible["ret_5d"]))
        eligible["score_medium"] = _percentile_rank(_winsorize(eligible["ret_20d"]))
        eligible["score_stress"] = _percentile_rank(_winsorize(eligible["stress_ret_20d"]))
        eligible["score_pf"] = _percentile_rank(eligible["pf_20d"].clip(0, 3))
        eligible["score_survival"] = _percentile_rank(eligible["stress_survival"])
        eligible["raw_score"] = (
            0.35 * eligible["score_recent"] + 0.25 * eligible["score_medium"]
            + 0.20 * eligible["score_stress"] + 0.10 * eligible["score_pf"]
            + 0.10 * eligible["score_survival"]
        )
        eligible["confidence"] = (eligible["closes_20d"] / 100.0).pow(0.5).clip(upper=1.0)
        eligible["is_abook"] = eligible["status"].fillna("").astype(str).str.upper().str.contains("A", regex=False)
        eligible["dynamic_score"] = 0.5 + eligible["confidence"] * (eligible["raw_score"] - 0.5) + eligible["is_abook"].astype(float) * 0.02
        eligible = eligible.sort_values(["dynamic_score", "stress_ret_20d"], ascending=False)

        stage_started = time.perf_counter()
        holding_stats = self.holding_statistics(eligible, as_of)
        build_stage_seconds["holding_statistics"] = time.perf_counter() - stage_started
        eligible["sleeve_key"] = [
            sleeve_key(str(row.account_key), str(row.product))
            for row in eligible.itertuples()
        ]
        for field in (
            "hold_p25_seconds", "median_hold_seconds", "hold_p90_seconds",
            "short_trade_ratio", "holding_samples",
        ):
            eligible[field] = eligible["sleeve_key"].map(
                lambda key, name=field: holding_stats.get(str(key), {}).get(name)
            )
        if self.factor_service is None:
            raise RuntimeError(
                "Historical factor service is required; legacy scores cannot authorize Demo execution."
            )
        stage_started = time.perf_counter()
        factor_rows = self.factor_service.evaluate(self.sources, eligible, as_of)
        build_stage_seconds["factor_evaluate"] = time.perf_counter() - stage_started
        factor_stage_seconds = getattr(self.factor_service, "last_stage_seconds", {})
        for name in ("history_load", "factor_scoring"):
            value = float(factor_stage_seconds.get(name, 0.0) or 0.0)
            build_stage_seconds[f"factor_{name}"] = max(0.0, value)
        required_factor_columns = {
            "sleeve_key", "factor_ready", "factor_base_score", "factor_gate_reasons",
            "delay_score", "mdd_20d", "mdd_60d", "current_drawdown",
            "holding_path_complete", "conservative_break_even_ms",
            "historical_delay_enabled", "delay_factor_status",
        }
        if factor_rows.empty or not required_factor_columns.issubset(factor_rows.columns):
            raise RuntimeError("Historical factor service returned incomplete factor evidence.")
        eligible = eligible.merge(
            factor_rows, on="sleeve_key", how="left", validate="one_to_one"
        )
        eligible["factor_ready"] = eligible["factor_ready"].fillna(False).astype(bool)
        eligible["legacy_dynamic_score"] = eligible["dynamic_score"]
        eligible["dynamic_score"] = (
            pd.to_numeric(eligible["factor_base_score"], errors="coerce").fillna(0.0)
            + eligible["is_abook"].astype(float) * 0.02
        ).clip(upper=1.0)
        eligible["hold_multiplier"] = eligible["median_hold_seconds"].map(
            lambda value: holding_score_multiplier(float(value)) if pd.notna(value) else 0.0
        )
        eligible["floating_risk_multiplier"] = eligible["floating_loss_ratio"].map(
            lambda value: intraday_multiplier(-float(value), 1.0)
        )
        eligible["margin_risk_multiplier"] = eligible["margin_to_equity"].map(
            lambda value: open_risk_multiplier(0.0, float(value), 0.0)
        )
        eligible["hedge_risk_multiplier"] = eligible["product_hedge_ratio"].map(
            lambda value: open_risk_multiplier(0.0, 0.0, float(value))
        )
        eligible["open_risk_multiplier"] = eligible[[
            "floating_risk_multiplier", "margin_risk_multiplier", "hedge_risk_multiplier",
        ]].min(axis=1)
        eligible["monitor_score"] = eligible["dynamic_score"] * eligible["open_risk_multiplier"]
        eligible["adjusted_score"] = eligible["monitor_score"] * eligible["hold_multiplier"]
        eligible["activity_eligible"] = (
            eligible["factor_ready"]
            & (eligible["hold_p25_seconds"] > 10.0)
            & (eligible["median_hold_seconds"] >= 60.0)
            & (eligible["median_hold_seconds"] <= 8 * 60 * 60)
            & (eligible["hold_p90_seconds"] <= 24 * 60 * 60)
            & (eligible["short_trade_ratio"] < 0.20)
            & (eligible["quality_stress_net_15x_20d_usd"] > 0)
        )
        monitor_candidates = eligible.loc[
            eligible["factor_ready"]
        ].copy()
        factor_gate_counts: dict[str, int] = {}
        for value in eligible.loc[~eligible["factor_ready"], "factor_gate_reasons"]:
            for reason in str(value or "").split("|"):
                normalized = reason.strip()
                if normalized:
                    factor_gate_counts[normalized] = factor_gate_counts.get(normalized, 0) + 1
        if monitor_candidates.empty:
            top_reasons = sorted(
                factor_gate_counts.items(), key=lambda item: (-item[1], item[0])
            )[:8]
            reason_summary = ", ".join(
                f"{reason}={count}" for reason, count in top_reasons
            ) or "none"
            raise RuntimeError(
                "No monitor sleeves passed factor readiness and hard gates; "
                f"factor_ready={int(eligible['factor_ready'].sum())}/{len(eligible)}, "
                f"top_factor_gates={reason_summary}."
            )
        ranked_universe = build_rank_universe(
            RankingCandidate(
                sleeve_key=str(row.sleeve_key),
                account_key=str(row.account_key),
                product=str(row.product),
                score=float(row.monitor_score),
                hard_eligible=True,
                activity_eligible=bool(row.activity_eligible),
                # Exact minimum-lot feasibility is rechecked with current Demo
                # margin and MAE evidence before any order is allowed.
                min_lot_feasible=True,
            )
            for row in monitor_candidates.itertuples()
        )
        selected_sleeves = {
            item.sleeve_key
            for item in ranked_universe.monitor_sleeves + ranked_universe.reserve_sleeves
        }
        pool = monitor_candidates.loc[
            monitor_candidates["sleeve_key"].isin(selected_sleeves)
        ].copy()
        monitor_accounts = set(ranked_universe.monitor_accounts)
        reserve_accounts = set(ranked_universe.reserve_accounts)
        pool["pool_tier"] = pool["account_key"].map(
            lambda key: "monitor" if str(key) in monitor_accounts else "reserve"
        )
        pool["daily_activity_eligible"] = pool["activity_eligible"].astype(bool)
        pool["activity_eligible"] = (
            pool["activity_eligible"] & pool["account_key"].isin(monitor_accounts)
        )
        require_nonempty_monitor_population(
            len(monitor_accounts), context="after product risk gates"
        )
        ranked_accounts = (
            pool.groupby("account_key", as_index=False)["adjusted_score"]
            .max()
            .sort_values("adjusted_score", ascending=False)
        )
        aliases = {
            str(row.account_key): f"C{index:03d}"
            for index, row in enumerate(ranked_accounts.itertuples(), start=1)
        }
        pool["client_alias"] = pool["account_key"].map(aliases)
        # Factor ranks determine proportional allocation after hard and
        # executable-holding gates. They must not become a second score floor.
        pool["weight_alpha"] = pool["adjusted_score"].clip(lower=0)
        active_products = {
            str(product) for product in pool.loc[pool["activity_eligible"], "product"].unique()
        }
        pool["customer_base_weight"] = 0.0
        for product, group in pool.loc[pool["activity_eligible"]].groupby("product"):
            normalized = _normalize_capped(
                {index: float(group.at[index, "weight_alpha"]) for index in group.index},
                cap=0.20,
            )
            for index, value in normalized.items():
                pool.at[index, "customer_base_weight"] = value
        product_alpha = {
            str(product): float(group["weight_alpha"].sum()) * math.sqrt(min(len(group), 30) / 30.0)
            for product, group in pool.loc[pool["activity_eligible"]].groupby("product")
        }
        product_weights, product_weight_cap_fallback = normalize_product_budget_weights(
            product_alpha, cap=0.40
        )
        pool["product_budget_weight"] = pool["product"].map(product_weights).fillna(0.0)
        pool["portfolio_base_weight"] = (
            pool["product_budget_weight"] * pool["customer_base_weight"]
        )
        pool["live_base_weight"] = pool["portfolio_base_weight"]
        reserve_activity = (
            (pool["pool_tier"] == "reserve") & pool["daily_activity_eligible"]
        )
        reserve_sleeve_counts = pool.loc[reserve_activity].groupby("account_key")["sleeve_key"].transform("count")
        pool.loc[reserve_activity, "live_base_weight"] = reserve_sleeve_counts.map(
            lambda count: min(MAX_SLEEVE_WEIGHT, MAX_CLIENT_WEIGHT / max(float(count), 1.0))
        )
        pool["pool_status"] = [
            "reserve" if tier == "reserve" else (
                "active_candidate" if activity else "monitor_only"
            )
            for tier, activity in zip(pool["pool_tier"], pool["activity_eligible"])
        ]
        pool = pool.sort_values(
            ["activity_eligible", "product_budget_weight", "adjusted_score"],
            ascending=[False, False, False],
        )
        pool["rank"] = range(1, len(pool) + 1)

        for source_key, source in self.sources.items():
            source.health.candidate_accounts = int(
                features.loc[features["physical_key"] == source_key, "account_key"].nunique()
            )
            source.health.eligible_accounts = int(
                eligible.loc[eligible["physical_key"] == source_key, "account_key"].nunique()
            )
            source.health.selected_clients = int(
                pool.loc[pool["physical_key"] == source_key, "account_key"].nunique()
            )
        build_stage_seconds["total"] = time.perf_counter() - build_started
        coverage = {
            "generated_at": datetime.now(BEIJING).isoformat(),
            "as_of": as_of.astimezone(BEIJING).isoformat(),
            "logical_routes_expected": len(ROUTES),
            "logical_routes_scanned": len(route_counts),
            "physical_sources_expected": len(self.sources),
            "physical_sources_scanned": len(self.sources),
            "route_account_counts": route_counts,
            "ambiguous_login_counts": ambiguous,
            "candidate_sleeves": int(len(features)),
            "positive_comprehensive_sleeves": int(len(positive_comprehensive)),
            "eligible_sleeves": int(len(eligible)),
            "selected_sleeves": int(len(pool)),
            "selected_accounts": int(pool["account_key"].nunique()),
            "monitor_accounts": len(monitor_accounts),
            "reserve_accounts": len(reserve_accounts),
            "monitor_sleeves": len(ranked_universe.monitor_sleeves),
            "reserve_sleeves": len(ranked_universe.reserve_sleeves),
            "coverage_products": list(ranked_universe.coverage_products),
            "product_cap_fallback_accounts": list(ranked_universe.cap_fallback_accounts),
            "selected_products": sorted(str(value) for value in pool["product"].unique()),
            "active_sleeves": int(pool["activity_eligible"].sum()),
            "active_accounts": int(
                pool.loc[pool["activity_eligible"], "account_key"].nunique()
            ),
            "active_products": sorted(active_products),
            "product_weight_cap_fallback": product_weight_cap_fallback,
            "build_stage_seconds": {
                key: round(max(0.0, float(value)), 3)
                for key, value in build_stage_seconds.items()
            },
            "sources": [source.health.public() for source in self.sources.values()],
        }
        return pool.reset_index(drop=True), eligible.reset_index(drop=True), coverage

    def selected_clients(self, pool: pd.DataFrame) -> dict[str, RoutedClient]:
        output: dict[str, RoutedClient] = {}
        for key, rows in pool.groupby("account_key", sort=False):
            row = next(rows.itertuples())
            products = {
                str(item.product): ProductSpec(
                    product=str(item.product),
                    base_weight=float(item.live_base_weight),
                    historical_net_20d_usd=float(item.net_20d_usd),
                    source_contract_size=float(item.source_contract_size),
                    demo_contract_size=float(item.demo_contract_size),
                    adjusted_score=float(item.adjusted_score),
                    median_hold_seconds=(
                        float(item.median_hold_seconds)
                        if pd.notna(item.median_hold_seconds)
                        else None
                    ),
                    activity_eligible=bool(item.activity_eligible),
                    customer_base_weight=float(item.customer_base_weight),
                    product_budget_weight=float(item.product_budget_weight),
                )
                for item in rows.itertuples()
            }
            key = str(key)
            spec = ClientSpec(
                login=key,  # type: ignore[arg-type]
                alias=str(row.client_alias),
                equity_usd=float(row.equity_pre_usd),
                base_weight=sum(product.base_weight for product in products.values()),
                money_scale=float(row.money_scale),
                adjusted_score=float(row.adjusted_score),
                is_abook=bool(row.is_abook),
                median_hold_seconds=float(row.median_hold_seconds) if pd.notna(row.median_hold_seconds) else None,
            )
            output[key] = RoutedClient(
                account_key=key, login=int(row.Login), route_key=str(row.route_key),
                physical_key=str(row.physical_key), connection=str(row.connection), schema=str(row.schema),
                crm_schema=str(row.crm_schema), server_code=int(row.server_code), platform=str(row.platform),
                server=str(row.server), spec=spec, products=products,
            )
        return output

    def highwaters(self) -> dict[str, SourceCursor]:
        result: dict[str, SourceCursor] = {}
        for source_key, mapping in self.clients_by_source_login.items():
            if not mapping:
                continue
            source = self.sources[source_key]
            if source.platform == "MT5":
                row = source.query(
                    f"SELECT Timestamp, Deal FROM {source.schema}.mt5_deals ORDER BY Timestamp DESC, Deal DESC LIMIT 1"
                )
                result[source_key] = SourceCursor(int(row[0]["Timestamp"]), int(row[0]["Deal"])) if row else SourceCursor()
            else:
                row = source.query(
                    f"SELECT MAX(TIMESTAMP) AS Timestamp, MAX(TICKET) AS Ticket FROM {source.schema}.mt4_trades"
                )
                result[source_key] = SourceCursor(int(row[0].get("Timestamp") or 0), int(row[0].get("Ticket") or 0))
        return result

    def positions_for_source(self, source_key: str) -> list[dict[str, Any]]:
        mapping = self.clients_by_source_login.get(source_key, {})
        if not mapping:
            return []
        source = self.sources[source_key]
        logins = sorted(mapping)
        rows: list[dict[str, Any]] = []
        for batch in _chunks(logins):
            placeholders = self._placeholders(len(batch))
            if source.platform == "MT5":
                raw = source.query(
                    f"SELECT Position, Login, Symbol, Action, VolumeExt / 100000000.0 AS lots, "
                    f"ContractSize, PriceOpen, PriceCurrent, Profit + Storage AS floating_pnl "
                    f"FROM {source.schema}.mt5_positions WHERE Login IN ({placeholders})",
                    batch,
                )
                for item in raw:
                    if normalize_source_product(item["Symbol"]) is None:
                        continue
                    account_key = mapping[int(item["Login"])]
                    client = self.clients.get(account_key)
                    money_scale = client.spec.money_scale if client is not None else 1.0
                    rows.append({
                        "account_key": account_key, "position_id": int(item["Position"]),
                        "symbol": item["Symbol"], "lots": float(item["lots"]) * (1 if int(item["Action"]) == 0 else -1),
                        "contract_size": float(item.get("ContractSize") or 0.0),
                        "source_open_price": float(item.get("PriceOpen") or 0.0),
                        "source_current_price": float(item.get("PriceCurrent") or 0.0),
                        "source_floating_pnl_usd": float(item.get("floating_pnl") or 0.0)
                        * money_scale,
                    })
            else:
                raw = source.query(
                    f"SELECT TICKET, LOGIN, SYMBOL, CMD, VOLUME / 100.0 AS lots, OPEN_TIME, "
                    f"OPEN_PRICE, CLOSE_PRICE, PROFIT + COMMISSION + SWAPS + TAXES AS floating_pnl "
                    f"FROM {source.schema}.mt4_trades WHERE LOGIN IN ({placeholders}) AND CMD IN (0,1) "
                    f"AND CLOSE_TIME = '1970-01-01 00:00:00'",
                    batch,
                )
                for item in raw:
                    if normalize_source_product(item["SYMBOL"]) is None:
                        continue
                    account_key = mapping[int(item["LOGIN"])]
                    client = self.clients.get(account_key)
                    money_scale = client.spec.money_scale if client is not None else 1.0
                    rows.append({
                        "account_key": account_key, "position_id": int(item["TICKET"]),
                        "symbol": item["SYMBOL"], "lots": float(item["lots"]) * (1 if int(item["CMD"]) == 0 else -1),
                        "contract_size": 0.0,
                        "source_open_price": float(item.get("OPEN_PRICE") or 0.0),
                        "source_current_price": float(item.get("CLOSE_PRICE") or 0.0),
                        "source_floating_pnl_usd": float(item.get("floating_pnl") or 0.0)
                        * money_scale,
                        "source_opened_at": (
                            mt4_source_time_to_utc(source_key, item["OPEN_TIME"]).isoformat()
                            if isinstance(item.get("OPEN_TIME"), datetime)
                            else ""
                        ),
                    })
        return rows

    def all_positions(self) -> list[dict[str, Any]]:
        selected = [key for key, mapping in self.clients_by_source_login.items() if mapping]
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(self.positions_for_source, key): key for key in selected}
            for future in as_completed(futures):
                try:
                    rows.extend(future.result())
                except Exception as exc:
                    errors.append(f"{futures[future]}: {exc}")
        if errors:
            raise RuntimeError("Source position reconciliation failed: " + "; ".join(errors))
        return rows

    def intraday_net(self, day_start_utc: datetime) -> dict[str, float]:
        start = day_start_utc.astimezone(BEIJING).replace(tzinfo=None)
        output: dict[str, float] = {}
        for source_key, mapping in self.clients_by_source_login.items():
            if not mapping:
                continue
            source = self.sources[source_key]
            logins = sorted(mapping)
            for batch in _chunks(logins):
                placeholders = self._placeholders(len(batch))
                if source.platform == "MT5":
                    rows = source.query(
                        f"SELECT Login, SUM(Profit + Commission + Storage + Fee) AS source_net "
                        f"FROM {source.schema}.mt5_deals WHERE Login IN ({placeholders}) AND Time >= %s "
                        f"AND Action IN (0,1) GROUP BY Login",
                        (*batch, start),
                    )
                else:
                    rows = source.query(
                        f"SELECT LOGIN AS Login, SUM(PROFIT + COMMISSION + SWAPS + TAXES) AS source_net "
                        f"FROM {source.schema}.mt4_trades WHERE LOGIN IN ({placeholders}) AND CLOSE_TIME >= %s "
                        f"AND CLOSE_TIME > OPEN_TIME AND CMD IN (0,1) GROUP BY LOGIN",
                        (*batch, start),
                    )
                for row in rows:
                    key = mapping[int(row["Login"])]
                    output[key] = float(row.get("source_net") or 0.0) * self.clients[key].spec.money_scale
        return output

    def intraday_product_net(self, day_start_utc: datetime) -> dict[str, float]:
        start = day_start_utc.astimezone(BEIJING).replace(tzinfo=None)
        output: dict[str, float] = defaultdict(float)
        for source_key, mapping in self.clients_by_source_login.items():
            if not mapping:
                continue
            source = self.sources[source_key]
            for batch in _chunks(sorted(mapping)):
                placeholders = self._placeholders(len(batch))
                if source.platform == "MT5":
                    rows = source.query(
                        f"SELECT Login, Symbol, SUM(Profit + Commission + Storage + Fee) AS source_net "
                        f"FROM {source.schema}.mt5_deals WHERE Login IN ({placeholders}) AND Time >= %s "
                        f"AND Action IN (0,1) GROUP BY Login, Symbol",
                        (*batch, start),
                    )
                else:
                    rows = source.query(
                        f"SELECT LOGIN AS Login, SYMBOL AS Symbol, "
                        f"SUM(PROFIT + COMMISSION + SWAPS + TAXES) AS source_net "
                        f"FROM {source.schema}.mt4_trades WHERE LOGIN IN ({placeholders}) AND CLOSE_TIME >= %s "
                        f"AND CLOSE_TIME > OPEN_TIME AND CMD IN (0,1) GROUP BY LOGIN, SYMBOL",
                        (*batch, start),
                    )
                for row in rows:
                    product = normalize_source_product(row.get("Symbol"))
                    account = mapping[int(row["Login"])]
                    if product is None or product not in self.clients[account].products:
                        continue
                    output[sleeve_key(account, product)] += (
                        float(row.get("source_net") or 0.0)
                        * self.clients[account].spec.money_scale
                    )
        return dict(output)

    def fetch_mt5_events(self, source_key: str, cursor: SourceCursor, limit: int = 1000) -> list[RoutedEvent]:
        mapping = self.clients_by_source_login.get(source_key, {})
        source = self.sources[source_key]
        if not mapping or source.platform != "MT5":
            return []
        logins = sorted(mapping)
        placeholders = self._placeholders(len(logins))
        rows = source.query(
            f"SELECT Deal, Timestamp, Login, PositionID, Action, Entry, Symbol, "
            f"VolumeExt / 100000000.0 AS lots, VolumeClosedExt / 100000000.0 AS volume_closed_lots, "
            f"Profit, Commission, Storage, Fee FROM {source.schema}.mt5_deals "
            f"WHERE Login IN ({placeholders}) AND (Timestamp > %s OR (Timestamp = %s AND Deal > %s)) "
            f"ORDER BY Timestamp, Deal LIMIT %s",
            (*logins, cursor.timestamp, cursor.timestamp, cursor.sequence, limit),
        )
        return [
            RoutedEvent(
                source_key=source_key, account_key=mapping[int(row["Login"])], login=mapping[int(row["Login"])],
                sequence=int(row["Deal"]), timestamp=int(row["Timestamp"]), position_id=int(row["PositionID"]),
                action=int(row["Action"]), entry=int(row["Entry"]), symbol=str(row["Symbol"]),
                lots=float(row["lots"]), volume_closed_lots=float(row["volume_closed_lots"]),
                profit=float(row["Profit"]), commission=float(row["Commission"]),
                storage=float(row["Storage"]), fee=float(row["Fee"]),
            )
            for row in rows
        ]

    def poll_mt5_events(self, cursors: Mapping[str, SourceCursor]) -> tuple[list[RoutedEvent], list[str]]:
        keys = [
            key for key, mapping in self.clients_by_source_login.items()
            if mapping and self.sources[key].platform == "MT5"
        ]
        events: list[RoutedEvent] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self.fetch_mt5_events, key, cursors.get(key, SourceCursor())): key
                for key in keys
            }
            for future in as_completed(futures):
                try:
                    events.extend(future.result())
                except Exception as exc:
                    errors.append(f"{futures[future]}: {exc}")
        events.sort(key=lambda event: (event.timestamp, event.source_key, event.sequence))
        return events, errors

    def poll_mt4_positions(self) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        keys = [
            key for key, mapping in self.clients_by_source_login.items()
            if mapping and self.sources[key].platform == "MT4"
        ]
        snapshots: dict[str, list[dict[str, Any]]] = {}
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(self.positions_for_source, key): key for key in keys}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    snapshots[key] = future.result()
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
        return snapshots, errors

    def health_public(self) -> list[dict[str, Any]]:
        return [self.sources[key].health.public() for key in sorted(self.sources)]

    def selected_source_staleness(self) -> float:
        ages: list[float] = []
        for key, mapping in self.clients_by_source_login.items():
            if not mapping:
                continue
            last = self.sources[key].health.last_success_monotonic
            ages.append(float("inf") if last <= 0 else time.monotonic() - last)
        return max(ages, default=float("inf"))
