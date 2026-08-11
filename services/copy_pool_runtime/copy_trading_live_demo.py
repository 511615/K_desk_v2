from __future__ import annotations

import argparse
import csv
import json
import math
import os
import signal
import statistics
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import MetaTrader5 as mt5
import pandas as pd
import pymysql

import copy_trading_demo
from copy_trading_live_core import (
    ClientSpec,
    DealCursor,
    DealEvent,
    SourcePortfolio,
    canonical_symbol,
    datetime_to_filetime,
    drawdown_throttle,
    filetime_to_datetime,
    friday_policy,
    guarded_execution_target,
    holding_score_multiplier,
    hysteresis_target,
    is_abook_status,
    normalize_with_cap,
    position_lot_cap,
    server_time_from_utc,
)


BEIJING = timezone(timedelta(hours=8))
ALLOWED_SERVER = "ACCMGlobal-Demo"
ALLOWED_SYMBOL = "XAUUSD"
SOURCE_SYMBOL = "XAUUSD.G"
MAGIC = 26_072_801
COMMENT = "COPYPOOL_DEMO_V1"
INDEPENDENT_COMMENT_PREFIX = "CPV2:"
DB_SCHEMA = "crm_vn_mt5_live2"
SPREAD_CAP_PRICE = 1.00
QUOTE_MAX_AGE_SECONDS = 2.0
DB_OPEN_BLOCK_SECONDS = 3.0
DB_FLATTEN_SECONDS = 30.0
COOLDOWN_SECONDS = 2 * 60 * 60
RECOVERY_SHADOW_SECONDS = 10 * 60
RECONCILE_SECONDS = 10.0
ORDER_RECONCILE_SECONDS = 5.0
MAX_DEVIATION_POINTS = 50
LATENCY_GATE_WINDOW = 30
MIN_LATENCY_GATE_SAMPLES = 20
DEMO_ACCOUNT_SNAPSHOT_SECONDS = 5.0
DEMO_ACCOUNT_HISTORY_CACHE_SECONDS = 10.0
DEMO_ACCOUNT_HISTORY_DAYS = 30
DEMO_ACCOUNT_HISTORY_LIMIT = 200

EVENT_PUBLIC_COLUMNS = (
    "event_id", "time_beijing", "client_alias", "source_side", "source_entry",
    "source_lots", "product", "effective_weight", "raw_target_lots",
    "desired_target_lots", "actual_strategy_lots", "gross_long_lots",
    "gross_short_lots", "db_latency_seconds", "phase", "reason",
)
ORDER_PUBLIC_COLUMNS = (
    "order_event", "time_beijing", "action", "before_lots", "target_lots",
    "after_lots", "bid", "ask", "spread_price", "quote_age_seconds", "retcode", "comment",
)
TIMELINE_PUBLIC_COLUMNS = (
    "time_beijing", "phase", "risk_profile", "account_login", "equity_usd", "position_cap_lots",
    "active_weights", "raw_target_lots", "desired_target_lots", "actual_strategy_lots",
    "gross_long_lots", "gross_short_lots", "spread_price", "db_latency_p95_seconds",
    "strategy_marked_pnl_usd", "cycle_pnl_usd", "reconcile_streak",
    "pending_source_snapshot_count", "duplicate_events",
)


@dataclass(frozen=True)
class RiskProfile:
    name: str
    hard_max_lots: float
    lot_step: float = 0.01
    enter_lots: float = 0.01
    exit_lots: float = 0.005
    stress_move_usd_per_unit: float | None = None
    risk_fraction: float | None = None
    margin_fraction: float | None = None
    cycle_stop_usd: float | None = None
    cycle_stop_fraction: float | None = None
    daily_stop_usd: float | None = None
    daily_stop_fraction: float | None = None
    equity_floor_usd: float | None = None
    minimum_start_balance_usd: float | None = None

    def cycle_loss_limit(self, reference_equity_usd: float) -> float:
        if self.cycle_stop_usd is not None:
            return self.cycle_stop_usd
        assert self.cycle_stop_fraction is not None
        return reference_equity_usd * self.cycle_stop_fraction

    def daily_loss_limit(self, reference_equity_usd: float) -> float:
        if self.daily_stop_usd is not None:
            return self.daily_stop_usd
        assert self.daily_stop_fraction is not None
        return reference_equity_usd * self.daily_stop_fraction


RISK_PROFILES = {
    "Micro": RiskProfile(
        name="Micro",
        hard_max_lots=0.01,
        cycle_stop_usd=20.0,
        daily_stop_usd=60.0,
    ),
    "Capital10k": RiskProfile(
        name="Capital10k",
        hard_max_lots=0.05,
        stress_move_usd_per_unit=20.0,
        risk_fraction=0.01,
        margin_fraction=0.10,
        cycle_stop_fraction=0.015,
        daily_stop_fraction=0.03,
        equity_floor_usd=9_500.0,
        minimum_start_balance_usd=9_500.0,
    ),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def beijing_now() -> datetime:
    return utc_now().astimezone(BEIJING)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    try:
        for attempt in range(5):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def csv_schema_archive_path(path: Path) -> Path:
    """Return an unused, same-directory archive path for an incompatible public CSV."""
    stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    candidate = path.with_name(f"{path.stem}.schema-mismatch-{stamp}{path.suffix}")
    sequence = 1
    while candidate.exists():
        candidate = path.with_name(
            f"{path.stem}.schema-mismatch-{stamp}-{sequence}{path.suffix}"
        )
        sequence += 1
    return candidate


def ensure_csv_schema(path: Path, fieldnames: Iterable[str]) -> Path | None:
    """Upgrade additive headers in place; rotate incompatible public CSVs."""
    expected = tuple(fieldnames)
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    header = rows[0] if rows else []
    data_rows = rows[1:]
    matches_schema = tuple(header) == expected and all(
        len(row) == len(expected) for row in data_rows
    )
    if matches_schema:
        return None
    archive_path = csv_schema_archive_path(path)
    path.replace(archive_path)
    additive = (
        bool(header)
        and len(set(header)) == len(header)
        and set(header).issubset(expected)
        and all(len(row) == len(header) for row in data_rows)
    )
    if additive:
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=expected)
            writer.writeheader()
            for values in data_rows:
                legacy = dict(zip(header, values))
                writer.writerow({column: legacy.get(column, "") for column in expected})
    return archive_path


def append_csv(
    path: Path,
    row: Mapping[str, Any],
    *,
    fieldnames: Iterable[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(fieldnames) if fieldnames is not None else tuple(row.keys())
    unexpected = set(row) - set(columns)
    if unexpected:
        raise ValueError(f"CSV row contains unexpected fields: {sorted(unexpected)}")
    normalized_row = {column: row.get(column, "") for column in columns}
    ensure_csv_schema(path, columns)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if not exists:
            writer.writeheader()
        writer.writerow(normalized_row)


def csv_data_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _row in csv.DictReader(handle))


def recent_csv_latencies(path: Path, limit: int = LATENCY_GATE_WINDOW) -> list[float]:
    if limit <= 0 or not path.exists() or path.stat().st_size == 0:
        return []
    values: deque[float] = deque(maxlen=limit)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                value = float(row["db_latency_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value) and value >= 0:
                values.append(value)
    return list(values)


def percentile_95(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


class ReadOnlyDb:
    def __init__(self) -> None:
        self.connection: pymysql.Connection | None = None
        self.logins: tuple[int, ...] = ()

    def connect(self) -> None:
        self.close()
        required = ["COPY_DB_HOST", "COPY_DB_PORT", "COPY_DB_USER", "COPY_DB_PASSWORD"]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing database environment variables: {', '.join(missing)}")
        self.connection = pymysql.connect(
            host=os.environ["COPY_DB_HOST"],
            port=int(os.environ["COPY_DB_PORT"]),
            user=os.environ["COPY_DB_USER"],
            password=os.environ["COPY_DB_PASSWORD"],
            database=DB_SCHEMA,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            connect_timeout=8,
            read_timeout=5,
            write_timeout=5,
        )

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _execute(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if self.connection is None:
            self.connect()
        assert self.connection is not None
        self.connection.ping(reconnect=True)
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    @staticmethod
    def _placeholders(count: int) -> str:
        if count <= 0:
            raise ValueError("At least one client login is required.")
        return ",".join(["%s"] * count)

    def set_logins(self, logins: Iterable[int]) -> None:
        self.logins = tuple(sorted({int(login) for login in logins}))

    def highwater(self) -> DealCursor:
        placeholders = self._placeholders(len(self.logins))
        rows = self._execute(
            f"SELECT Timestamp, Deal FROM {DB_SCHEMA}.mt5_deals FORCE INDEX (IDX_mt5_deals_Timestamp) "
            f"WHERE Login IN ({placeholders}) AND Action IN (0,1) "
            "ORDER BY Timestamp DESC, Deal DESC LIMIT 1",
            self.logins,
        )
        if not rows:
            return DealCursor()
        return DealCursor(int(rows[0]["Timestamp"]), int(rows[0]["Deal"]))

    def positions(self) -> list[dict[str, Any]]:
        placeholders = self._placeholders(len(self.logins))
        return self._execute(
            f"SELECT Position, Login, Symbol, Action, VolumeExt / 100000000.0 AS lots "
            f"FROM {DB_SCHEMA}.mt5_positions WHERE Login IN ({placeholders}) "
            "ORDER BY Login, Position",
            self.logins,
        )

    def intraday_net(self, trading_day_start_utc: datetime) -> dict[int, float]:
        placeholders = self._placeholders(len(self.logins))
        start_tick = datetime_to_filetime(trading_day_start_utc)
        rows = self._execute(
            f"SELECT Login, SUM(Profit + Commission + Storage + Fee) AS source_net "
            f"FROM {DB_SCHEMA}.mt5_deals FORCE INDEX (IDX_mt5_deals_Timestamp) "
            f"WHERE Login IN ({placeholders}) AND Timestamp >= %s AND Action IN (0,1) "
            "GROUP BY Login",
            (*self.logins, start_tick),
        )
        return {int(row["Login"]): float(row["source_net"] or 0.0) for row in rows}

    def fetch_deals(self, cursor: DealCursor, limit: int = 1000) -> list[DealEvent]:
        placeholders = self._placeholders(len(self.logins))
        rows = self._execute(
            f"SELECT Deal, Timestamp, Login, PositionID, Action, Entry, Symbol, "
            "VolumeExt / 100000000.0 AS lots, "
            "VolumeClosedExt / 100000000.0 AS volume_closed_lots, "
            "Profit, Commission, Storage, Fee "
            f"FROM {DB_SCHEMA}.mt5_deals FORCE INDEX (IDX_mt5_deals_Timestamp) "
            f"WHERE Login IN ({placeholders}) AND Action IN (0,1) "
            "AND (Timestamp > %s OR (Timestamp = %s AND Deal > %s)) "
            "ORDER BY Timestamp, Deal LIMIT %s",
            (*self.logins, cursor.timestamp, cursor.timestamp, cursor.deal, limit),
        )
        return [
            DealEvent(
                deal=int(row["Deal"]),
                timestamp=int(row["Timestamp"]),
                login=int(row["Login"]),
                position_id=int(row["PositionID"]),
                action=int(row["Action"]),
                entry=int(row["Entry"]),
                symbol=str(row["Symbol"]),
                lots=float(row["lots"]),
                volume_closed_lots=float(row["volume_closed_lots"]),
                profit=float(row["Profit"]),
                commission=float(row["Commission"]),
                storage=float(row["Storage"]),
                fee=float(row["Fee"]),
            )
            for row in rows
        ]

    def holding_medians(self, days: int = 20) -> dict[int, float]:
        placeholders = self._placeholders(len(self.logins))
        threshold = datetime_to_filetime(utc_now() - timedelta(days=days))
        rows = self._execute(
            f"SELECT Login, PositionID, Entry, TimeMsc "
            f"FROM {DB_SCHEMA}.mt5_deals FORCE INDEX (IDX_mt5_deals_Timestamp) "
            f"WHERE Login IN ({placeholders}) AND Timestamp >= %s AND Action IN (0,1) "
            "ORDER BY Login, PositionID, TimeMsc LIMIT 200000",
            (*self.logins, threshold),
        )
        grouped: dict[tuple[int, int], list[tuple[int, datetime]]] = {}
        for row in rows:
            grouped.setdefault((int(row["Login"]), int(row["PositionID"])), []).append(
                (int(row["Entry"]), row["TimeMsc"])
            )
        durations: dict[int, list[float]] = {}
        for (login, _position), events in grouped.items():
            opens = [stamp for entry, stamp in events if entry == 0]
            closes = [stamp for entry, stamp in events if entry in (1, 2, 3)]
            if not opens or not closes:
                continue
            seconds = (max(closes) - min(opens)).total_seconds()
            if seconds >= 0:
                durations.setdefault(login, []).append(seconds)
        return {
            login: float(statistics.median(values))
            for login, values in durations.items()
            if values
        }


class Mt5Executor:
    IDENTITY_STABLE_SAMPLES = 3
    IDENTITY_POLL_ATTEMPTS = 100
    IDENTITY_POLL_SECONDS = 0.1

    def __init__(
        self,
        terminal_path: Path,
        risk_profile: RiskProfile,
        expected_login: int | None = None,
    ) -> None:
        self.terminal_path = terminal_path
        self.risk_profile = risk_profile
        self.expected_login = int(expected_login) if expected_login is not None else None
        if self.expected_login is not None and self.expected_login <= 0:
            raise ValueError("Expected Demo Login must be positive.")
        self.approved_login: int | None = None
        self._demo_history_cached_at = 0.0
        self._demo_history_cache: list[dict[str, Any]] = []

    @staticmethod
    def _is_strategy_row(row: Any) -> bool:
        comment = str(getattr(row, "comment", "") or "")
        return int(getattr(row, "magic", 0)) == MAGIC and (
            comment == COMMENT or comment.startswith(INDEPENDENT_COMMENT_PREFIX)
        )

    def initialize(self) -> None:
        if not mt5.initialize(path=str(self.terminal_path), timeout=10_000):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None:
            raise RuntimeError(f"MT5 state unavailable: {mt5.last_error()}")
        if self.expected_login is not None and (
            int(getattr(account, "login", 0) or 0) != self.expected_login
            or str(getattr(account, "server", "")) != ALLOWED_SERVER
            or int(getattr(account, "trade_mode", -1)) != 0
        ):
            if not mt5.login(self.expected_login, server=ALLOWED_SERVER):
                raise RuntimeError(
                    f"Selecting approved Demo Login {self.expected_login} failed: {mt5.last_error()}"
                )
            account = self._wait_for_expected_account()
            if account is None:
                raise RuntimeError(
                    "MT5 login did not select the approved Demo account: "
                    f"expected Login {self.expected_login} on {ALLOWED_SERVER}."
                )
        if account.server != ALLOWED_SERVER or int(account.trade_mode) != 0:
            raise RuntimeError("Refusing to run: the connected account is not the approved Demo server.")
        login = int(account.login)
        if self.expected_login is not None and login != self.expected_login:
            raise RuntimeError(
                f"Refusing to run: expected Demo Login {self.expected_login}, received {login}."
            )
        if login <= 0:
            raise RuntimeError("Refusing to run: the connected Demo account has no valid Login.")
        self.approved_login = login
        if int(account.margin_mode) != 2:
            raise RuntimeError("Refusing to run: the approved test requires a hedging account.")
        if not terminal.connected:
            raise RuntimeError("MT5 terminal is disconnected.")
        symbol = mt5.symbol_info(ALLOWED_SYMBOL)
        if symbol is None or int(symbol.trade_mode) != 4:
            raise RuntimeError(f"{ALLOWED_SYMBOL} is not fully tradable.")
        if not symbol.visible and not mt5.symbol_select(ALLOWED_SYMBOL, True):
            raise RuntimeError(f"Unable to select {ALLOWED_SYMBOL}.")
        if float(symbol.volume_min) > self.risk_profile.lot_step + 1e-9:
            raise RuntimeError("Broker minimum volume exceeds the configured lot step.")
        if abs(float(symbol.volume_step) - self.risk_profile.lot_step) > 1e-9:
            raise RuntimeError("Broker volume step does not match the risk profile.")

    def _wait_for_expected_account(self) -> Any | None:
        assert self.expected_login is not None
        stable_samples = 0
        stable_account: Any | None = None
        for attempt in range(self.IDENTITY_POLL_ATTEMPTS):
            candidate = mt5.account_info()
            matches = candidate is not None and (
                int(getattr(candidate, "login", 0) or 0) == self.expected_login
                and str(getattr(candidate, "server", "")) == ALLOWED_SERVER
                and int(getattr(candidate, "trade_mode", -1)) == 0
            )
            if matches:
                stable_samples += 1
                stable_account = candidate
                if stable_samples >= self.IDENTITY_STABLE_SAMPLES:
                    return stable_account
            else:
                stable_samples = 0
                stable_account = None
            if attempt + 1 < self.IDENTITY_POLL_ATTEMPTS:
                time.sleep(self.IDENTITY_POLL_SECONDS)
        return None

    def shutdown(self) -> None:
        mt5.shutdown()

    def configure_symbols(self, symbols: Iterable[str]) -> dict[str, dict[str, float]]:
        configured: dict[str, dict[str, float]] = {}
        for symbol_name in sorted(set(symbols)):
            symbol = self.symbol(symbol_name)
            if int(symbol.trade_mode) != 4:
                raise RuntimeError(f"{symbol_name} is not fully tradable on the approved Demo.")
            if not symbol.visible and not mt5.symbol_select(symbol_name, True):
                raise RuntimeError(f"Unable to select {symbol_name} on the approved Demo.")
            configured[symbol_name] = {
                "volume_min": float(symbol.volume_min),
                "volume_step": float(symbol.volume_step),
                "volume_max": float(symbol.volume_max),
                "contract_size": float(symbol.trade_contract_size),
            }
        return configured

    def account(self) -> Any:
        value = mt5.account_info()
        if value is None:
            raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
        actual_login = int(getattr(value, "login", 0) or 0)
        if self.approved_login is None:
            raise RuntimeError("MT5 account identity is unavailable before initialization.")
        if (
            actual_login != self.approved_login
            or str(getattr(value, "server", "")) != ALLOWED_SERVER
            or int(getattr(value, "trade_mode", -1)) != 0
        ):
            raise RuntimeError(
                "MT5 account identity changed during execution: "
                f"expected Login {self.approved_login} on {ALLOWED_SERVER}, "
                f"received Login {actual_login} on {getattr(value, 'server', '')}."
            )
        return value

    @staticmethod
    def _utc_iso_from_seconds(value: Any) -> str:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return ""

    @staticmethod
    def _utc_iso_from_milliseconds(value: Any) -> str:
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return ""

    @staticmethod
    def _deal_entry_label(value: Any) -> str:
        labels = {
            int(getattr(mt5, "DEAL_ENTRY_IN", 0)): "IN",
            int(getattr(mt5, "DEAL_ENTRY_OUT", 1)): "OUT",
            int(getattr(mt5, "DEAL_ENTRY_INOUT", 2)): "INOUT",
            int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)): "OUT_BY",
        }
        return labels.get(int(value), "UNKNOWN")

    @staticmethod
    def _trade_side(value: Any) -> str:
        return "BUY" if int(value) == int(getattr(mt5, "DEAL_TYPE_BUY", 0)) else "SELL"

    def demo_account_snapshot(
        self,
        *,
        history_days: int = DEMO_ACCOUNT_HISTORY_DAYS,
        history_limit: int = DEMO_ACCOUNT_HISTORY_LIMIT,
    ) -> dict[str, Any]:
        self.account()
        positions_raw = mt5.positions_get()
        if positions_raw is None:
            raise RuntimeError(f"MT5 positions_get failed: {mt5.last_error()}")
        positions = [
            {
                "ticket": int(getattr(position, "ticket", 0) or 0),
                "position_id": int(
                    getattr(position, "identifier", 0)
                    or getattr(position, "ticket", 0)
                    or 0
                ),
                "product": str(getattr(position, "symbol", "") or ""),
                "side": self._trade_side(getattr(position, "type", 0)),
                "lots": float(getattr(position, "volume", 0.0) or 0.0),
                "open_price": float(getattr(position, "price_open", 0.0) or 0.0),
                "current_price": float(getattr(position, "price_current", 0.0) or 0.0),
                "stop_loss": float(getattr(position, "sl", 0.0) or 0.0),
                "take_profit": float(getattr(position, "tp", 0.0) or 0.0),
                "floating_pnl_usd": float(getattr(position, "profit", 0.0) or 0.0),
                "swap_usd": float(getattr(position, "swap", 0.0) or 0.0),
                "opened_at": self._utc_iso_from_seconds(getattr(position, "time", 0)),
                "strategy_owned": self._is_strategy_row(position),
            }
            for position in positions_raw
            if (
                str(getattr(position, "symbol", "") or "")
                and self._is_strategy_row(position)
            )
        ]
        positions.sort(key=lambda row: (row["opened_at"], row["ticket"]), reverse=True)

        now_monotonic = time.monotonic()
        if now_monotonic - self._demo_history_cached_at >= DEMO_ACCOUNT_HISTORY_CACHE_SECONDS:
            now = utc_now()
            deals_raw = mt5.history_deals_get(now - timedelta(days=max(1, history_days)), now)
            if deals_raw is None:
                raise RuntimeError(f"MT5 history_deals_get failed: {mt5.last_error()}")
            trade_types = {
                int(getattr(mt5, "DEAL_TYPE_BUY", 0)),
                int(getattr(mt5, "DEAL_TYPE_SELL", 1)),
            }
            deals = []
            for deal in deals_raw:
                if (
                    int(getattr(deal, "type", -1)) not in trade_types
                    or not str(getattr(deal, "symbol", "") or "")
                    or not self._is_strategy_row(deal)
                ):
                    continue
                profit = float(getattr(deal, "profit", 0.0) or 0.0)
                commission = float(getattr(deal, "commission", 0.0) or 0.0)
                swap = float(getattr(deal, "swap", 0.0) or 0.0)
                fee = float(getattr(deal, "fee", 0.0) or 0.0)
                deals.append({
                    "deal_ticket": int(getattr(deal, "ticket", 0) or 0),
                    "order_ticket": int(getattr(deal, "order", 0) or 0),
                    "position_id": int(getattr(deal, "position_id", 0) or 0),
                    "time": self._utc_iso_from_milliseconds(getattr(deal, "time_msc", 0)),
                    "product": str(getattr(deal, "symbol", "") or ""),
                    "entry": self._deal_entry_label(getattr(deal, "entry", -1)),
                    "side": self._trade_side(getattr(deal, "type", 0)),
                    "lots": float(getattr(deal, "volume", 0.0) or 0.0),
                    "price": float(getattr(deal, "price", 0.0) or 0.0),
                    "profit_usd": profit,
                    "commission_usd": commission,
                    "swap_usd": swap,
                    "fee_usd": fee,
                    "net_pnl_usd": profit + commission + swap + fee,
                    "strategy_owned": self._is_strategy_row(deal),
                })
            deals.sort(key=lambda row: (row["time"], row["deal_ticket"]), reverse=True)
            self._demo_history_cache = deals[:max(1, history_limit)]
            self._demo_history_cached_at = now_monotonic

        verified = self.account()
        return {
            "updated_at_beijing": beijing_now().isoformat(),
            "account": {
                "login": int(verified.login),
                "server": str(verified.server),
                "currency": str(getattr(verified, "currency", "USD") or "USD"),
                "balance_usd": float(getattr(verified, "balance", 0.0) or 0.0),
                "equity_usd": float(getattr(verified, "equity", 0.0) or 0.0),
                "margin_usd": float(getattr(verified, "margin", 0.0) or 0.0),
                "free_margin_usd": float(getattr(verified, "margin_free", 0.0) or 0.0),
                "margin_level_percent": float(getattr(verified, "margin_level", 0.0) or 0.0),
            },
            "positions": positions,
            "deals": list(self._demo_history_cache),
        }

    @staticmethod
    def terminal() -> Any:
        value = mt5.terminal_info()
        if value is None:
            raise RuntimeError(f"MT5 terminal_info failed: {mt5.last_error()}")
        return value

    @staticmethod
    def tick(symbol: str = ALLOWED_SYMBOL) -> Any:
        value = mt5.symbol_info_tick(symbol)
        if value is None:
            raise RuntimeError(f"MT5 tick unavailable for {symbol}: {mt5.last_error()}")
        return value

    @staticmethod
    def symbol(symbol: str = ALLOWED_SYMBOL) -> Any:
        value = mt5.symbol_info(symbol)
        if value is None:
            raise RuntimeError(f"MT5 symbol unavailable for {symbol}: {mt5.last_error()}")
        return value

    @staticmethod
    def strategy_positions(symbol: str = ALLOWED_SYMBOL) -> tuple[Any, ...]:
        return tuple(
            position
            for position in (mt5.positions_get(symbol=symbol) or ())
            if Mt5Executor._is_strategy_row(position)
        )

    @staticmethod
    def all_strategy_positions() -> tuple[Any, ...]:
        return tuple(
            position
            for position in (mt5.positions_get() or ())
            if Mt5Executor._is_strategy_row(position)
        )

    @staticmethod
    def strategy_positions_by_comment(comment: str, symbol: str | None = None) -> tuple[Any, ...]:
        rows = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        return tuple(
            position
            for position in (rows or ())
            if Mt5Executor._is_strategy_row(position)
            and str(position.comment) == comment
        )

    def signed_position_by_comment(self, comment: str, symbol: str) -> float:
        return sum(
            float(position.volume)
            * (1.0 if int(position.type) == mt5.POSITION_TYPE_BUY else -1.0)
            for position in self.strategy_positions_by_comment(comment, symbol)
        )

    def wait_for_comment_position(
        self,
        comment: str,
        symbol: str,
        expected: float,
    ) -> tuple[Any, ...]:
        deadline = time.monotonic() + ORDER_RECONCILE_SECONDS
        while time.monotonic() < deadline:
            positions = self.strategy_positions_by_comment(comment, symbol)
            actual = sum(
                float(position.volume)
                * (1.0 if int(position.type) == mt5.POSITION_TYPE_BUY else -1.0)
                for position in positions
            )
            if abs(actual - expected) < 1e-9:
                return positions
            time.sleep(0.2)
        raise RuntimeError(
            f"MT5 {symbol} independent position {comment} did not reconcile to "
            f"{expected:+.2f} lots within five seconds."
        )

    @staticmethod
    def position_by_ticket(ticket: int) -> Any | None:
        rows = mt5.positions_get(ticket=int(ticket)) or ()
        return rows[0] if rows else None

    @staticmethod
    def foreign_positions(symbol: str = ALLOWED_SYMBOL) -> tuple[Any, ...]:
        return tuple(
            position
            for position in (mt5.positions_get(symbol=symbol) or ())
            if not Mt5Executor._is_strategy_row(position)
        )

    @staticmethod
    def all_foreign_positions(symbols: Iterable[str] | None = None) -> tuple[Any, ...]:
        allowed = set(symbols or ())
        return tuple(
            position
            for position in (mt5.positions_get() or ())
            if (not allowed or str(position.symbol) in allowed)
            and not Mt5Executor._is_strategy_row(position)
        )

    @staticmethod
    def pending_orders(symbol: str = ALLOWED_SYMBOL) -> tuple[Any, ...]:
        return tuple(mt5.orders_get(symbol=symbol) or ())

    @staticmethod
    def all_pending_orders(symbols: Iterable[str] | None = None) -> tuple[Any, ...]:
        allowed = set(symbols or ())
        return tuple(
            order
            for order in (mt5.orders_get() or ())
            if not allowed or str(order.symbol) in allowed
        )

    def signed_position(self, symbol: str = ALLOWED_SYMBOL) -> float:
        return round(
            sum(
                float(position.volume) if int(position.type) == mt5.POSITION_TYPE_BUY else -float(position.volume)
                for position in self.strategy_positions(symbol)
            ),
            8,
        )

    def signed_positions(self) -> dict[str, float]:
        output: dict[str, float] = {}
        for position in self.all_strategy_positions():
            symbol = str(position.symbol)
            output[symbol] = output.get(symbol, 0.0) + (
                float(position.volume)
                if int(position.type) == mt5.POSITION_TYPE_BUY
                else -float(position.volume)
            )
        return {symbol: round(value, 8) for symbol, value in output.items() if abs(value) > 1e-12}

    def gross_position(self, symbol: str = ALLOWED_SYMBOL) -> float:
        return round(sum(float(position.volume) for position in self.strategy_positions(symbol)), 8)

    def gross_all_positions(self) -> float:
        return round(sum(float(position.volume) for position in self.all_strategy_positions()), 8)

    def has_internal_hedge(self, symbol: str = ALLOWED_SYMBOL) -> bool:
        sides = {int(position.type) for position in self.strategy_positions(symbol)}
        return len(sides) > 1

    def has_any_internal_hedge(self) -> bool:
        return any(self.has_internal_hedge(symbol) for symbol in self.signed_positions())

    def quote_state(self, symbol: str = ALLOWED_SYMBOL) -> tuple[float, float, float]:
        tick = self.tick(symbol)
        spread = float(tick.ask) - float(tick.bid)
        age = max(0.0, time.time() - float(tick.time_msc) / 1000.0)
        return float(tick.bid), float(tick.ask), age

    def marked_pnl(self, trading_day_start_utc: datetime) -> float:
        deals = mt5.history_deals_get(trading_day_start_utc, utc_now()) or ()
        realized = sum(
            float(deal.profit)
            + float(deal.commission)
            + float(deal.swap)
            + float(deal.fee)
            for deal in deals
            if self._is_strategy_row(deal)
        )
        floating = sum(
            float(position.profit) + float(getattr(position, "swap", 0.0))
            for position in self.all_strategy_positions()
        )
        return realized + floating

    def pnl_by_comment(
        self, trading_day_start_utc: datetime
    ) -> dict[str, dict[str, float]]:
        output: dict[str, dict[str, float]] = {}
        for deal in mt5.history_deals_get(trading_day_start_utc, utc_now()) or ():
            if not self._is_strategy_row(deal):
                continue
            comment = str(deal.comment)
            target = output.setdefault(comment, {"realized": 0.0, "floating": 0.0})
            target["realized"] += (
                float(deal.profit)
                + float(deal.commission)
                + float(deal.swap)
                + float(deal.fee)
            )
        for position in self.all_strategy_positions():
            comment = str(position.comment)
            target = output.setdefault(comment, {"realized": 0.0, "floating": 0.0})
            target["floating"] += float(position.profit) + float(
                getattr(position, "swap", 0.0)
            )
        return output

    def margin_per_lot(self, signed_side: float = 1.0, symbol: str = ALLOWED_SYMBOL) -> float:
        tick = self.tick(symbol)
        order_type = mt5.ORDER_TYPE_BUY if signed_side >= 0 else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if signed_side >= 0 else tick.bid)
        value = mt5.order_calc_margin(order_type, symbol, 1.0, price)
        if value is None or float(value) <= 0:
            raise RuntimeError(f"MT5 margin calculation failed: {mt5.last_error()}")
        return float(value)

    def stress_loss_per_lot(self, symbol: str, move_fraction: float) -> float:
        tick = self.tick(symbol)
        open_price = float(tick.ask)
        close_price = max(float(self.symbol(symbol).point), open_price * (1.0 - move_fraction))
        value = mt5.order_calc_profit(
            mt5.ORDER_TYPE_BUY,
            symbol,
            1.0,
            open_price,
            close_price,
        )
        if value is None:
            raise RuntimeError(f"MT5 stress calculation failed for {symbol}: {mt5.last_error()}")
        return abs(float(value))

    def spread_cost_usd_per_lot(
        self,
        symbol: str,
        bid: float | None = None,
        ask: float | None = None,
    ) -> float:
        """Convert one-lot bid/ask spread cost into the Demo account currency."""
        if bid is None or ask is None:
            tick = self.tick(symbol)
            bid, ask = float(tick.bid), float(tick.ask)
        if not (float(ask) >= float(bid) > 0):
            raise RuntimeError(f"Invalid quote for spread conversion: {symbol}")
        info = self.symbol(symbol)
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
        tick_values = (
            float(getattr(info, "trade_tick_value_loss", 0.0) or 0.0),
            float(getattr(info, "trade_tick_value_profit", 0.0) or 0.0),
        )
        if tick_size > 0 and max(tick_values) > 0:
            return (
                max(0.0, float(ask) - float(bid))
                / tick_size
                * max(tick_values)
            )
        values = (
            mt5.order_calc_profit(
                mt5.ORDER_TYPE_BUY, symbol, 1.0, float(ask), float(bid)
            ),
            mt5.order_calc_profit(
                mt5.ORDER_TYPE_SELL, symbol, 1.0, float(bid), float(ask)
            ),
        )
        if any(value is None for value in values):
            raise RuntimeError(
                f"MT5 spread conversion failed for {symbol}: {mt5.last_error()}"
            )
        return max(abs(float(value)) for value in values)

    def _filling_mode(self, symbol: str = ALLOWED_SYMBOL) -> int:
        flags = int(self.symbol(symbol).filling_mode)
        if flags & 2:
            return mt5.ORDER_FILLING_IOC
        if flags & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def _send(self, request: dict[str, Any]) -> Any:
        check = mt5.order_check(request)
        if check is None or int(check.retcode) != 0:
            raise RuntimeError(f"MT5 order_check rejected request: {check or mt5.last_error()}")
        result = mt5.order_send(request)
        accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL}
        if result is None or int(result.retcode) not in accepted:
            raise RuntimeError(f"MT5 order_send failed: {result or mt5.last_error()}")
        return result

    def close_position(self, position: Any, volume: float | None = None) -> Any:
        symbol = str(position.symbol)
        tick = self.tick(symbol)
        is_buy = int(position.type) == mt5.POSITION_TYPE_BUY
        close_volume = float(position.volume) if volume is None else float(volume)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "position": int(position.ticket),
            "volume": close_volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": float(tick.bid if is_buy else tick.ask),
            "deviation": MAX_DEVIATION_POINTS,
            "magic": MAGIC,
            "comment": str(getattr(position, "comment", "") or COMMENT),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(symbol),
        }
        return self._send(request)

    def close_all(self, symbol: str = ALLOWED_SYMBOL) -> list[Any]:
        return [self.close_position(position) for position in self.strategy_positions(symbol)]

    def close_all_symbols(self) -> list[Any]:
        return [self.close_position(position) for position in self.all_strategy_positions()]

    def open_position(
        self,
        signed_lots: float,
        symbol_name: str = ALLOWED_SYMBOL,
        hard_cap_lots: float | None = None,
        comment: str = COMMENT,
    ) -> Any:
        symbol = self.symbol(symbol_name)
        volume = abs(float(signed_lots))
        step = float(symbol.volume_step)
        normalized = round(round(volume / step) * step, 8)
        hard_cap = self.risk_profile.hard_max_lots if hard_cap_lots is None else float(hard_cap_lots)
        if (
            volume < float(symbol.volume_min) - 1e-9
            or abs(volume - normalized) > 1e-9
            or volume > hard_cap + 1e-9
            or volume > float(symbol.volume_max) + 1e-9
        ):
            raise ValueError(
                f"Requested volume {volume:.2f} is outside the {self.risk_profile.name} Demo guard."
            )
        tick = self.tick(symbol_name)
        is_buy = signed_lots > 0
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol_name,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": float(tick.ask if is_buy else tick.bid),
            "deviation": MAX_DEVIATION_POINTS,
            "magic": MAGIC,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(symbol_name),
        }
        return self._send(request)

    def move_to(
        self,
        target: float,
        symbol: str = ALLOWED_SYMBOL,
        hard_cap_lots: float | None = None,
    ) -> list[Any]:
        results: list[Any] = []
        current = self.signed_position(symbol)
        if abs(current - target) < 1e-9:
            return results
        if current * target < -1e-12:
            results.extend(self.close_all(symbol))
            self.wait_for_position(0.0, symbol)
            current = 0.0
        if abs(target) < 1e-9:
            results.extend(self.close_all(symbol))
            self.wait_for_position(0.0, symbol)
            return results
        delta = round(target - current, 8)
        if current * target >= 0 and abs(target) < abs(current) - 1e-9:
            remaining = abs(delta)
            for position in reversed(self.strategy_positions(symbol)):
                if remaining <= 1e-9:
                    break
                close_volume = min(float(position.volume), remaining)
                results.append(self.close_position(position, close_volume))
                remaining = round(remaining - close_volume, 8)
            if remaining > 1e-9:
                raise RuntimeError("Unable to reduce the complete strategy volume.")
            self.wait_for_position(target, symbol)
            return results
        if abs(delta) > 1e-9:
            results.append(self.open_position(delta, symbol, hard_cap_lots))
            self.wait_for_position(target, symbol)
        return results

    def wait_for_position(self, expected: float, symbol: str = ALLOWED_SYMBOL) -> None:
        deadline = time.monotonic() + ORDER_RECONCILE_SECONDS
        while time.monotonic() < deadline:
            if abs(self.signed_position(symbol) - expected) < 1e-9:
                return
            time.sleep(0.2)
        raise RuntimeError(
            f"MT5 {symbol} position did not reconcile to {expected:+.2f} lots within five seconds."
        )

    def wait_for_no_strategy_positions(self) -> None:
        deadline = time.monotonic() + ORDER_RECONCILE_SECONDS
        while time.monotonic() < deadline:
            if not self.all_strategy_positions():
                return
            time.sleep(0.2)
        remaining = [int(position.ticket) for position in self.all_strategy_positions()]
        raise RuntimeError(
            "MT5 strategy tickets did not fully close within five seconds: "
            f"{remaining[:10]}"
        )


def adjusted_clients(
    pool: pd.DataFrame, holding_medians: Mapping[int, float]
) -> tuple[dict[int, ClientSpec], pd.DataFrame]:
    work = pool.copy()
    work["is_abook"] = work["mt_type_name"].map(is_abook_status)
    work["median_hold_seconds"] = work["Login"].map(holding_medians)
    work["hold_multiplier"] = work["median_hold_seconds"].map(holding_score_multiplier)
    work["adjusted_score"] = (
        work["dynamic_score"] + 0.02 * work["is_abook"].astype(float)
    ).clip(upper=1.0)
    work = work.loc[work["hold_multiplier"] > 0].copy()
    raw = {
        int(row.Login): max(float(row.adjusted_score) - 0.55, 0.0) ** 1.5
        * float(row.hold_multiplier)
        for row in work.itertuples(index=False)
    }
    weights = normalize_with_cap(raw)
    work["live_base_weight"] = work["Login"].map(weights).fillna(0.0)
    work = work.loc[work["live_base_weight"] > 0].copy()
    clients = {
        int(row.Login): ClientSpec(
            login=int(row.Login),
            alias=str(row.client_alias),
            equity_usd=float(row.equity_pre_usd),
            base_weight=float(row.live_base_weight),
            money_scale=float(row.money_scale),
            adjusted_score=float(row.adjusted_score),
            is_abook=bool(row.is_abook),
            median_hold_seconds=(
                float(row.median_hold_seconds)
                if pd.notna(row.median_hold_seconds)
                else None
            ),
        )
        for row in work.itertuples(index=False)
    }
    return clients, work


def trading_day_start_utc(now: datetime) -> datetime:
    server_now = server_time_from_utc(now)
    server_midnight = server_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return server_midnight.astimezone(timezone.utc)


def trading_day_key(now: datetime) -> str:
    return server_time_from_utc(now).date().isoformat()


class LiveService:
    event_public_columns = EVENT_PUBLIC_COLUMNS
    order_public_columns = ORDER_PUBLIC_COLUMNS
    timeline_public_columns = TIMELINE_PUBLIC_COLUMNS

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.profile = RISK_PROFILES[args.risk_profile]
        self.output_dir = args.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.private_state_path = self.output_dir / "runtime_state_private.json"
        self.private_routes_path = self.output_dir / "client_routes_private.json"
        self.status_path = self.output_dir / "status.json"
        self.demo_account_path = self.output_dir / "demo_account_public.json"
        self.event_path = self.output_dir / "events_public.csv"
        self.order_path = self.output_dir / "orders_public.csv"
        self.pool_path = self.output_dir / "pool_public.csv"
        self.timeline_path = self.output_dir / "status_timeline_public.csv"
        self._ensure_public_csv_schemas()
        self.db = ReadOnlyDb()
        self.mt = Mt5Executor(
            args.terminal,
            self.profile,
            expected_login=getattr(args, "demo_login", None),
        )
        self.clients: dict[int, ClientSpec] = {}
        self.pool_frame = pd.DataFrame()
        self.portfolio: SourcePortfolio | None = None
        self.phase = "starting"
        self.running = True
        self.last_db_success = time.monotonic()
        self.last_reconcile = 0.0
        self.reconcile_streak = 0
        self.latencies: list[float] = []
        self.shadow_started = time.monotonic()
        self.required_shadow_seconds = args.shadow_minutes * 60.0
        self.current_target = 0.0
        self.event_counter = csv_data_rows(self.event_path)
        self.order_counter = csv_data_rows(self.order_path)
        self.cooldown_until: datetime | None = None
        self.cycle_baseline_pnl = 0.0
        self.cycle_reference_equity = 0.0
        self.daily_reference_equity = 0.0
        self.daily_hard_stop = False
        self.last_error = ""
        self.last_pool_reload_day = ""
        self.last_timeline_write = 0.0
        self.last_demo_account_write = 0.0
        self.pending_source_snapshot: dict[tuple[int, int, str], float] | None = None
        self.pending_source_snapshot_count = 0
        self.external_position_conflict = False
        self.external_position_count = 0
        self.pending_order_conflict = False
        self._last_public_status: dict[str, Any] | None = None

    def _ensure_public_csv_schemas(self) -> None:
        ensure_csv_schema(self.event_path, self.event_public_columns)
        ensure_csv_schema(self.order_path, self.order_public_columns)
        ensure_csv_schema(self.timeline_path, self.timeline_public_columns)

    def _append_event_csv(self, row: Mapping[str, Any]) -> None:
        append_csv(self.event_path, row, fieldnames=self.event_public_columns)

    def _append_order_csv(self, row: Mapping[str, Any]) -> None:
        append_csv(self.order_path, row, fieldnames=self.order_public_columns)

    def _append_timeline_csv(self, row: Mapping[str, Any]) -> None:
        append_csv(self.timeline_path, row, fieldnames=self.timeline_public_columns)

    def cycle_loss_limit(self) -> float:
        return self.profile.cycle_loss_limit(max(self.cycle_reference_equity, 1.0))

    def daily_loss_limit(self) -> float:
        return self.profile.daily_loss_limit(max(self.daily_reference_equity, 1.0))

    def position_cap(self, cycle_pnl_usd: float = 0.0) -> float:
        if self.profile.stress_move_usd_per_unit is None:
            base_cap = self.profile.hard_max_lots
        else:
            account = self.mt.account()
            symbol = self.mt.symbol()
            assert self.profile.risk_fraction is not None
            assert self.profile.margin_fraction is not None
            margin_per_lot = max(self.mt.margin_per_lot(1.0), self.mt.margin_per_lot(-1.0))
            base_cap = position_lot_cap(
                reference_equity_usd=max(self.cycle_reference_equity, 1.0),
                current_equity_usd=float(account.equity),
                hard_cap_lots=self.profile.hard_max_lots,
                stress_move_usd_per_unit=self.profile.stress_move_usd_per_unit,
                contract_size=float(symbol.trade_contract_size),
                risk_fraction=self.profile.risk_fraction,
                margin_per_lot_usd=margin_per_lot,
                margin_fraction=self.profile.margin_fraction,
                lot_step=self.profile.lot_step,
            )
        throttle = drawdown_throttle(cycle_pnl_usd, self.cycle_loss_limit())
        units = math.floor(base_cap * throttle / self.profile.lot_step + 1e-12)
        return round(max(0, units) * self.profile.lot_step, 8)

    def target_for_raw(
        self, raw_target: float, current_target: float, cycle_pnl_usd: float = 0.0
    ) -> float:
        return hysteresis_target(
            raw_target,
            current_target,
            max_lots=self.position_cap(cycle_pnl_usd),
            enter_lots=self.profile.enter_lots,
            exit_lots=self.profile.exit_lots,
            lot_step=self.profile.lot_step,
        )

    def log(self, message: str) -> None:
        stamp = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{stamp}] {message}", flush=True)

    def load_pool(self) -> None:
        pool, _ = copy_trading_demo.build_pool(self.args.input_dir)
        self.db.set_logins(int(login) for login in pool["Login"])
        medians = self.db.holding_medians()
        clients, adjusted = adjusted_clients(pool, medians)
        if len(clients) < 10:
            raise RuntimeError(f"Only {len(clients)} clients remain after holding-time gates.")
        self.clients = clients
        self.pool_frame = adjusted
        self.db.set_logins(clients)
        public = adjusted[
            [
                "client_alias",
                "dynamic_score",
                "adjusted_score",
                "is_abook",
                "median_hold_seconds",
                "hold_multiplier",
                "live_base_weight",
                "equity_pre_usd",
            ]
        ].copy()
        public.to_csv(self.pool_path, index=False, encoding="utf-8-sig")
        atomic_json(
            self.private_routes_path,
            {
                "generated_at": beijing_now().isoformat(),
                "clients": [
                    {
                        "alias": client.alias,
                        "login": client.login,
                        "platform": "MT5",
                        "server": "DBG GB MT5 Live2",
                    }
                    for client in clients.values()
                ],
            },
        )
        self.log(
            f"Loaded {len(clients)} anonymous clients; risk budget="
            f"{sum(client.base_weight for client in clients.values()):.4f}."
        )

    def bootstrap(self) -> None:
        restored_cursor = DealCursor()
        saved: dict[str, Any] = {}
        if self.private_state_path.exists():
            try:
                saved = json.loads(self.private_state_path.read_text(encoding="utf-8"))
                cursor = saved.get("cursor", {})
                restored_cursor = DealCursor(
                    int(cursor.get("timestamp", 0)), int(cursor.get("deal", 0))
                )
                self.log(
                    "Restored the private cursor; current source positions will remain authoritative."
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.log(f"Private state could not be restored and will be rebuilt: {exc}")
        highwater = self.db.highwater()
        rows = self.db.positions()
        self.portfolio = SourcePortfolio(self.clients)
        self.portfolio.replace_positions(rows)
        if restored_cursor > highwater:
            self.log("Saved cursor was ahead of the database high-water mark; using the database mark.")
        self.portfolio.cursor = highwater
        self.portfolio.set_intraday_net(self.db.intraday_net(trading_day_start_utc(utc_now())))
        self.latencies = recent_csv_latencies(self.event_path)
        account = self.mt.account()
        if (
            self.profile.minimum_start_balance_usd is not None
            and float(account.balance) < self.profile.minimum_start_balance_usd
        ):
            raise RuntimeError(
                f"{self.profile.name} requires at least "
                f"{self.profile.minimum_start_balance_usd:.2f} USD balance."
            )
        saved_profile = saved.get("risk_profile")
        saved_day = saved.get("trading_day")
        current_day = trading_day_key(utc_now())
        if saved_profile == self.profile.name and saved_day == current_day:
            self.cycle_baseline_pnl = float(saved.get("cycle_baseline_pnl", 0.0))
            self.cycle_reference_equity = float(
                saved.get("cycle_reference_equity", float(account.equity))
            )
            self.daily_reference_equity = float(
                saved.get("daily_reference_equity", float(account.equity))
            )
            self.daily_hard_stop = bool(saved.get("daily_hard_stop", False))
            cooldown_text = saved.get("cooldown_until")
            self.cooldown_until = (
                datetime.fromisoformat(cooldown_text) if cooldown_text else None
            )
        else:
            self.cycle_baseline_pnl = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
            self.cycle_reference_equity = float(account.equity)
            self.daily_reference_equity = float(account.equity)
            self.daily_hard_stop = False
            self.cooldown_until = None
        raw_target, _gross_long, _gross_short = self.portfolio.target(
            ALLOWED_SYMBOL, float(account.equity)
        )
        marked = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
        cycle = marked - self.cycle_baseline_pnl
        self.current_target = self.target_for_raw(raw_target, 0.0, cycle)
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
        self.last_pool_reload_day = trading_day_key(utc_now())
        self.persist_private_state()

    def persist_private_state(self) -> None:
        if self.portfolio is None:
            return
        payload = {
            "cursor": asdict(self.portfolio.cursor),
            "positions": [
                {
                    "login": login,
                    "position_id": position_id,
                    "product": product,
                    "lots": lots,
                }
                for (login, position_id, product), lots in self.portfolio.positions.items()
            ],
            "intraday_net_usd": self.portfolio.intraday_net_usd,
            "risk_profile": self.profile.name,
            "trading_day": trading_day_key(utc_now()),
            "cycle_baseline_pnl": self.cycle_baseline_pnl,
            "cycle_reference_equity": self.cycle_reference_equity,
            "daily_reference_equity": self.daily_reference_equity,
            "daily_hard_stop": self.daily_hard_stop,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "saved_at": beijing_now().isoformat(),
        }
        atomic_json(self.private_state_path, payload)

    def public_status(self) -> dict[str, Any]:
        assert self.portfolio is not None
        account = self.mt.account()
        bid, ask, quote_age = self.mt.quote_state()
        raw, gross_long, gross_short = self.portfolio.target(
            ALLOWED_SYMBOL, float(account.equity)
        )
        marked = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
        cycle = marked - self.cycle_baseline_pnl
        cap = self.position_cap(cycle)
        return {
            "updated_at_beijing": beijing_now().isoformat(),
            "phase": self.phase,
            "server": account.server,
            "account_login": int(account.login),
            "symbol": ALLOWED_SYMBOL,
            "risk_profile": self.profile.name,
            "balance_usd": float(account.balance),
            "equity_usd": float(account.equity),
            "position_cap_lots": cap,
            "hard_max_lots": self.profile.hard_max_lots,
            "cycle_loss_limit_usd": self.cycle_loss_limit(),
            "daily_loss_limit_usd": self.daily_loss_limit(),
            "equity_floor_usd": self.profile.equity_floor_usd,
            "clients": len(self.clients),
            "active_weights": sum(self.portfolio.effective_weights.values()),
            "raw_target_lots": raw,
            "desired_target_lots": self.current_target,
            "actual_strategy_lots": self.mt.signed_position(),
            "gross_long_lots": gross_long,
            "gross_short_lots": gross_short,
            "bid": bid,
            "ask": ask,
            "spread_price": ask - bid,
            "quote_age_seconds": quote_age,
            "db_seconds_since_success": time.monotonic() - self.last_db_success,
            "db_latency_window_events": len(self.latencies[-LATENCY_GATE_WINDOW:]),
            "db_latency_p95_seconds": percentile_95(
                self.latencies[-LATENCY_GATE_WINDOW:]
            ),
            "reconcile_streak": self.reconcile_streak,
            "pending_source_snapshot_count": self.pending_source_snapshot_count,
            "duplicate_events": self.portfolio.duplicate_events,
            "strategy_marked_pnl_usd": marked,
            "cycle_pnl_usd": cycle,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "daily_hard_stop": self.daily_hard_stop,
            "terminal_trade_allowed": bool(self.mt.terminal().trade_allowed),
            "live_execution_authorized": bool(self.args.enable_live_trading),
            "external_position_conflict": self.external_position_conflict,
            "external_position_count": getattr(self, "external_position_count", 0),
            "pending_order_conflict": self.pending_order_conflict,
            "last_error": self.last_error,
        }

    def write_status(self) -> None:
        try:
            status = self.public_status()
            self._last_public_status = dict(status)
        except Exception as exc:
            # A transient terminal identity/IPC failure must not stop the
            # heartbeat. Keep the last verified account snapshot and publish
            # a fresh error state instead of silently freezing status.json.
            self.last_error = f"status_snapshot_failed: {type(exc).__name__}: {exc}"
            status = dict(self._last_public_status or {})
            status.update({
                "updated_at_beijing": beijing_now().isoformat(),
                "phase": self.phase,
                "last_error": self.last_error,
                "status_stale": True,
            })
        now_monotonic = time.monotonic()
        if (
            now_monotonic - self.last_demo_account_write >= DEMO_ACCOUNT_SNAPSHOT_SECONDS
            or not self.demo_account_path.is_file()
        ):
            try:
                atomic_json(self.demo_account_path, self.mt.demo_account_snapshot())
                self.last_demo_account_write = now_monotonic
            except Exception as exc:
                ledger_error = f"demo_account_snapshot_failed: {type(exc).__name__}: {exc}"
                self.log(ledger_error)
                status["demo_account_snapshot_stale"] = True
                if not status.get("last_error"):
                    status["last_error"] = ledger_error
        atomic_json(self.status_path, status)
        timeline_keys = {
            "updated_at_beijing", "phase", "risk_profile", "account_login",
            "equity_usd", "position_cap_lots", "active_weights", "raw_target_lots",
            "desired_target_lots", "actual_strategy_lots", "gross_long_lots",
            "gross_short_lots", "spread_price", "db_latency_p95_seconds",
            "strategy_marked_pnl_usd", "cycle_pnl_usd", "reconcile_streak",
            "pending_source_snapshot_count", "duplicate_events",
        }
        if time.monotonic() - self.last_timeline_write >= 5.0 and timeline_keys <= status.keys():
            self._append_timeline_csv(
                {
                    "time_beijing": status["updated_at_beijing"],
                    "phase": status["phase"],
                    "risk_profile": status["risk_profile"],
                    "account_login": status["account_login"],
                    "equity_usd": status["equity_usd"],
                    "position_cap_lots": status["position_cap_lots"],
                    "active_weights": status["active_weights"],
                    "raw_target_lots": status["raw_target_lots"],
                    "desired_target_lots": status["desired_target_lots"],
                    "actual_strategy_lots": status["actual_strategy_lots"],
                    "gross_long_lots": status["gross_long_lots"],
                    "gross_short_lots": status["gross_short_lots"],
                    "spread_price": status["spread_price"],
                    "db_latency_p95_seconds": status["db_latency_p95_seconds"],
                    "strategy_marked_pnl_usd": status["strategy_marked_pnl_usd"],
                    "cycle_pnl_usd": status["cycle_pnl_usd"],
                    "reconcile_streak": status["reconcile_streak"],
                    "pending_source_snapshot_count": status["pending_source_snapshot_count"],
                    "duplicate_events": status["duplicate_events"],
                },
            )
            self.last_timeline_write = time.monotonic()

    def reconcile_sources(self) -> None:
        assert self.portfolio is not None
        before = self.portfolio.comparable_positions()
        rows = self.db.positions()
        check = SourcePortfolio(self.clients)
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
                self.portfolio.replace_positions(rows)
                self.pending_source_snapshot = None
                self.pending_source_snapshot_count = 0
                self.log(
                    "Persistent source-position drift corrected after three matching snapshots."
                )
        self.last_reconcile = time.monotonic()
        self.last_db_success = time.monotonic()

    def shadow_ready(self) -> bool:
        elapsed = time.monotonic() - self.shadow_started
        return elapsed >= self.required_shadow_seconds and self.operational_gates_ready()

    def operational_gates_ready(self) -> bool:
        latency_window = self.latencies[-LATENCY_GATE_WINDOW:]
        p95 = percentile_95(latency_window)
        return (
            self.reconcile_streak >= 3
            and self.pending_source_snapshot_count == 0
            and self.portfolio is not None
            and self.portfolio.duplicate_events == 0
            and len(latency_window) >= MIN_LATENCY_GATE_SAMPLES
            and p95 is not None
            and p95 < 2.0
        )

    def quote_allows_open(self) -> bool:
        bid, ask, age = self.mt.quote_state()
        return (
            ask >= bid > 0
            and ask - bid <= SPREAD_CAP_PRICE
            and age <= QUOTE_MAX_AGE_SECONDS
            and time.monotonic() - self.last_db_success <= DB_OPEN_BLOCK_SECONDS
            and self.operational_gates_ready()
        )

    def refresh_mt5_conflicts(self) -> bool:
        foreign_positions = tuple(self.mt.foreign_positions())
        self.external_position_count = len(foreign_positions)
        # Foreign/manual positions are observed but isolated from strategy
        # sizing, P/L, ownership and execution through Magic/comment filters.
        self.external_position_conflict = False
        self.pending_order_conflict = bool(self.mt.pending_orders())
        if self.pending_order_conflict:
            self.last_error = (
                "Exposure conflict detected (XAUUSD pending order); "
                "new risk is blocked."
            )
            return True
        if self.last_error.startswith("Exposure conflict detected ("):
            self.last_error = ""
        return False

    def log_order(self, action: str, before: float, target: float, result: Any | None) -> None:
        self.order_counter += 1
        bid, ask, age = self.mt.quote_state()
        self._append_order_csv(
            {
                "order_event": f"O{self.order_counter:06d}",
                "time_beijing": beijing_now().isoformat(),
                "action": action,
                "before_lots": before,
                "target_lots": target,
                "after_lots": self.mt.signed_position(),
                "bid": bid,
                "ask": ask,
                "spread_price": ask - bid,
                "quote_age_seconds": age,
                "retcode": int(result.retcode) if result is not None else "",
                "comment": str(result.comment) if result is not None else "",
            },
        )

    def flatten(self, reason: str) -> None:
        before = self.mt.signed_position()
        results = self.mt.close_all()
        self.mt.wait_for_position(0.0)
        self.current_target = 0.0
        self.log_order(f"FLATTEN:{reason}", before, 0.0, results[-1] if results else None)
        self.log(f"Strategy position flattened: {reason}.")

    def execution_hard_stop(self, before: float, reason: str, error: Exception) -> None:
        result: Any | None = None
        try:
            results = self.mt.close_all()
            self.mt.wait_for_position(0.0)
            result = results[-1] if results else None
        except Exception as flatten_error:
            self.log(f"Emergency strategy flatten failed: {flatten_error}")
        self.current_target = 0.0
        self.phase = "execution_hard_stop"
        self.log_order(f"HARD_STOP:{reason}", before, 0.0, result)
        self.log(f"Execution hard stop: {error}")

    def execute_target(
        self, desired: float, reason: str, allow_new_exposure: bool = True
    ) -> None:
        before = self.mt.signed_position()
        if abs(before - desired) < 1e-9:
            return
        conflict = self.refresh_mt5_conflicts()
        can_open = (
            allow_new_exposure
            and not conflict
            and self.quote_allows_open()
        )
        immediate_target = guarded_execution_target(before, desired, can_open)
        if abs(before - immediate_target) < 1e-9:
            return
        action = reason
        if abs(immediate_target - desired) >= 1e-9:
            action = f"{reason}:CLOSE_ONLY"
        try:
            results = self.mt.move_to(immediate_target)
            self.log_order(
                action,
                before,
                immediate_target,
                results[-1] if results else None,
            )
        except Exception as exc:
            self.execution_hard_stop(before, reason, exc)
            raise

    def reconcile_mt5_target(self) -> None:
        if self.phase != "live":
            return
        policy = friday_policy(server_time_from_utc(utc_now()))
        if policy == "flatten":
            if abs(self.mt.signed_position()) > 1e-9:
                self.flatten("friday_fallback")
            return
        self.execute_target(
            self.current_target,
            "TARGET_RECONCILE",
            allow_new_exposure=policy == "normal",
        )

    def apply_event(self, event: DealEvent) -> None:
        assert self.portfolio is not None
        if not self.portfolio.apply_deal(event):
            return
        latency = max(0.0, (utc_now() - filetime_to_datetime(event.timestamp)).total_seconds())
        self.latencies.append(latency)
        client = self.clients[event.login]
        account = self.mt.account()
        raw, gross_long, gross_short = self.portfolio.target(
            ALLOWED_SYMBOL, float(account.equity)
        )
        marked = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
        cycle = marked - self.cycle_baseline_pnl
        desired = self.target_for_raw(raw, self.current_target, cycle)
        self.current_target = desired
        self.event_counter += 1
        self._append_event_csv(
            {
                "event_id": f"E{self.event_counter:07d}",
                "time_beijing": filetime_to_datetime(event.timestamp).astimezone(BEIJING).isoformat(),
                "client_alias": client.alias,
                "source_side": "BUY" if event.action == 0 else "SELL",
                "source_entry": event.entry,
                "source_lots": event.lots,
                "product": canonical_symbol(event.symbol),
                "effective_weight": self.portfolio.effective_weights[event.login],
                "raw_target_lots": raw,
                "desired_target_lots": desired,
                "actual_strategy_lots": self.mt.signed_position(),
                "gross_long_lots": gross_long,
                "gross_short_lots": gross_short,
                "db_latency_seconds": latency,
                "phase": self.phase,
                "reason": "dynamic net target updated from an anonymous pool execution",
            },
        )
        if self.phase == "live":
            policy = friday_policy(server_time_from_utc(utc_now()))
            if policy == "flatten":
                self.flatten("friday_fallback")
            else:
                self.execute_target(
                    desired,
                    f"SOURCE:{client.alias}",
                    allow_new_exposure=policy == "normal",
                )

    def risk_check(self) -> None:
        policy = friday_policy(server_time_from_utc(utc_now()))
        if policy == "flatten" and abs(self.mt.signed_position()) > 1e-9:
            self.flatten("friday_fallback")
        current_day = trading_day_key(utc_now())
        if current_day != self.last_pool_reload_day:
            server_now = server_time_from_utc(utc_now())
            if (server_now.hour, server_now.minute) >= (0, 15):
                self.daily_hard_stop = False
                self.daily_reference_equity = float(self.mt.account().equity)
        day_start = trading_day_start_utc(utc_now())
        account = self.mt.account()
        marked = self.mt.marked_pnl(day_start)
        cycle = marked - self.cycle_baseline_pnl
        if (
            self.profile.equity_floor_usd is not None
            and float(account.equity) <= self.profile.equity_floor_usd
        ):
            if abs(self.mt.signed_position()) > 1e-9:
                self.flatten("equity_floor")
            self.daily_hard_stop = True
            self.phase = "equity_floor_stop"
            return
        if marked <= -self.daily_loss_limit():
            if abs(self.mt.signed_position()) > 1e-9:
                self.flatten("daily_loss_stop")
            self.daily_hard_stop = True
            self.phase = "daily_stop"
            return
        if self.phase == "live" and cycle <= -self.cycle_loss_limit():
            self.flatten("cycle_loss_stop")
            self.cooldown_until = utc_now() + timedelta(seconds=COOLDOWN_SECONDS)
            self.phase = "cooldown"
        if self.phase == "cooldown" and self.cooldown_until is not None:
            if utc_now() >= self.cooldown_until:
                self.phase = "recovery_shadow"
                self.shadow_started = time.monotonic()
                self.required_shadow_seconds = RECOVERY_SHADOW_SECONDS
                self.reconcile_streak = 0
        if self.phase == "recovery_shadow" and self.shadow_ready():
            self.cycle_baseline_pnl = marked
            self.cycle_reference_equity = float(account.equity)
            self.phase = "live"
        if self.portfolio is not None and self.phase not in {
            "daily_stop",
            "equity_floor_stop",
            "execution_hard_stop",
        }:
            raw, _gross_long, _gross_short = self.portfolio.target(
                ALLOWED_SYMBOL, float(account.equity)
            )
            self.current_target = self.target_for_raw(raw, self.current_target, cycle)

    def maybe_daily_rebuild(self) -> None:
        current_day = trading_day_key(utc_now())
        server_now = server_time_from_utc(utc_now())
        if current_day == self.last_pool_reload_day:
            return
        if (server_now.hour, server_now.minute) < (0, 15):
            return
        if abs(self.mt.signed_position()) > 1e-9:
            self.flatten("daily_pool_rebuild")
        self.load_pool()
        self.bootstrap()
        self.phase = "recovery_shadow"
        self.shadow_started = time.monotonic()
        self.required_shadow_seconds = RECOVERY_SHADOW_SECONDS
        self.reconcile_streak = 0
        self.last_pool_reload_day = current_day
        self.log("Daily pool reload completed; ten-minute recovery shadow started.")

    def maybe_transition_live(self) -> None:
        if self.args.mode == "Shadow":
            return
        if self.phase == "armed_waiting_autotrading" and not self.operational_gates_ready():
            self.phase = "shadow"
            self.log("Operational gates regressed; returning to shadow mode.")
            return
        if self.phase == "shadow" and self.shadow_ready():
            if self.args.enable_live_trading and bool(self.mt.terminal().trade_allowed):
                self.phase = "live"
                self.cycle_baseline_pnl = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
                self.cycle_reference_equity = float(self.mt.account().equity)
                self.log("Shadow gates passed; staged live execution is active.")
                self.execute_target(self.current_target, "STAGED_START")
            else:
                self.phase = "armed_waiting_autotrading"
                self.log(
                    "Shadow gates passed; waiting for explicit launcher authorization and MT5 trade capability."
                )
        if (
            self.phase == "armed_waiting_autotrading"
            and self.args.enable_live_trading
            and bool(self.mt.terminal().trade_allowed)
        ):
            self.phase = "live"
            self.cycle_baseline_pnl = self.mt.marked_pnl(trading_day_start_utc(utc_now()))
            self.cycle_reference_equity = float(self.mt.account().equity)
            self.log("MT5 AutoTrading verified; live Demo execution is active.")
            self.execute_target(self.current_target, "STAGED_START")

    def run(self) -> None:
        self.db.connect()
        self.load_pool()
        self.mt.initialize()
        account = self.mt.account()
        if (
            self.profile.minimum_start_balance_usd is not None
            and float(account.balance) < self.profile.minimum_start_balance_usd
        ):
            raise RuntimeError(
                f"{self.profile.name} refuses account balance {float(account.balance):.2f} USD."
            )
        existing_strategy = self.mt.strategy_positions()
        existing_signed = self.mt.signed_position()
        if (
            self.mt.has_internal_hedge()
            or self.mt.gross_position() > self.profile.hard_max_lots + 1e-9
            or abs(existing_signed) > self.profile.hard_max_lots + 1e-9
        ):
            raise RuntimeError(
                f"Existing strategy exposure exceeds the {self.profile.name} Demo guard."
            )
        if existing_strategy:
            self.log(
                f"Recovered existing strategy position at {existing_signed:+.2f} lots; "
                "the current source target will be authoritative."
            )
        self.refresh_mt5_conflicts()
        self.bootstrap()
        startup_cap = self.position_cap(0.0)
        if abs(existing_signed) > startup_cap + 1e-9:
            reduced_target = math.copysign(startup_cap, existing_signed) if startup_cap else 0.0
            self.execute_target(
                reduced_target,
                "STARTUP_RISK_REDUCTION",
                allow_new_exposure=False,
            )
        self.log(
            f"Service started in {self.phase} mode; profile={self.profile.name}, "
            f"shadow={self.required_shadow_seconds:.0f}s, poll={self.args.poll_ms}ms."
        )
        started = time.monotonic()
        try:
            while self.running:
                if self.args.run_seconds and time.monotonic() - started >= self.args.run_seconds:
                    break
                try:
                    assert self.portfolio is not None
                    deals = self.db.fetch_deals(self.portfolio.cursor)
                    self.last_db_success = time.monotonic()
                    for event in deals:
                        if canonical_symbol(event.symbol) == ALLOWED_SYMBOL:
                            self.apply_event(event)
                    if time.monotonic() - self.last_reconcile >= RECONCILE_SECONDS:
                        self.reconcile_sources()
                    self.maybe_daily_rebuild()
                    self.maybe_transition_live()
                    self.risk_check()
                    self.refresh_mt5_conflicts()
                    self.reconcile_mt5_target()
                    if time.monotonic() - self.last_db_success >= DB_FLATTEN_SECONDS:
                        if abs(self.mt.signed_position()) > 1e-9:
                            self.flatten("database_outage")
                    self.persist_private_state()
                    self.write_status()
                    self.last_error = ""
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self.log(self.last_error)
                    if time.monotonic() - self.last_db_success >= DB_FLATTEN_SECONDS:
                        try:
                            if abs(self.mt.signed_position()) > 1e-9:
                                self.flatten("database_or_runtime_outage")
                        except Exception as flatten_error:
                            self.log(f"Emergency flatten failed: {flatten_error}")
                    time.sleep(min(2.0, self.args.poll_ms / 1000.0 * 2))
                    try:
                        self.db.connect()
                    except Exception:
                        pass
                time.sleep(self.args.poll_ms / 1000.0)
        finally:
            self.persist_private_state()
            try:
                self.write_status()
            except Exception:
                pass
            self.db.close()
            self.mt.shutdown()
            self.log("Service stopped.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dynamic anonymous-pool MT5 Demo copier.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--demo-login", type=int)
    parser.add_argument(
        "--risk-profile",
        choices=tuple(RISK_PROFILES),
        default="Micro",
    )
    parser.add_argument("--mode", choices=("Shadow", "StagedLive", "Live"), default="StagedLive")
    parser.add_argument("--shadow-minutes", type=float, default=30.0)
    parser.add_argument("--poll-ms", type=int, default=500)
    parser.add_argument("--run-seconds", type=float, default=0.0)
    parser.add_argument(
        "--enable-live-trading",
        action="store_true",
        help="Explicitly authorize Demo orders after the staged gates pass.",
    )
    args = parser.parse_args()
    if args.shadow_minutes < 0:
        parser.error("--shadow-minutes must be nonnegative")
    if args.poll_ms < 250 or args.poll_ms > 10_000:
        parser.error("--poll-ms must be between 250 and 10000")
    if args.demo_login is not None and args.demo_login <= 0:
        parser.error("--demo-login must be positive")
    return args


def main() -> None:
    args = parse_args()
    service = LiveService(args)

    def stop_service(_signum: int, _frame: Any) -> None:
        service.running = False

    signal.signal(signal.SIGINT, stop_service)
    signal.signal(signal.SIGTERM, stop_service)
    service.run()


if __name__ == "__main__":
    main()
