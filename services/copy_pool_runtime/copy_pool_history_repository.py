"""Bounded read-only history loader for all-route copy-pool factor evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

import pandas as pd

from copy_delay_replay_domain import PositionLifecycle
from copy_pool_equity_reconstruction import (
    AccountMoneyEvent,
    DailyEquityAnchor,
    PositionFloatingSnapshot,
    PositionInterval,
    ReconstructedEquity,
    reconstruct_intraday_equity,
)
from copy_pool_factor_domain import TradeHoldingObservation
from copy_pool_history_adapter import (
    build_mt4_equity_points,
    build_mt4_lifecycles,
    build_mt5_equity_points,
    build_mt5_lifecycles,
    holding_observations_from_lifecycles,
    holding_observations_from_snapshot_paths,
)
from copy_product_catalog import normalize_source_product, product_spec


DB_TIMEZONE = timezone(timedelta(hours=8))
MT5_EXTERNAL_ACTIONS = frozenset({2, 3, 4, 5, 6, 8, 15, 16})
MT5_SO_ACTIONS = frozenset({15, 16})
TRANSIENT_QUERY_ERROR_CODES = frozenset({1205, 2006, 2013})
DAILY_LOGIN_BATCH_SIZE = 10
TRADE_LOGIN_BATCH_SIZE = 25
CURRENT_LOGIN_BATCH_SIZE = 50
SNAPSHOT_ID_BATCH_SIZE = 100
ANCHOR_INITIAL_LOOKBACK_DAYS = 7
ANCHOR_MAX_LOOKBACK_DAYS = 2_048


class ReadOnlyHistorySource(Protocol):
    platform: str
    schema: str

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...

    def reset_connection(self) -> None: ...


@dataclass(frozen=True)
class SleeveHistoryBundle:
    account_key: str
    product: str
    lifecycles: tuple[PositionLifecycle, ...]
    holdings: tuple[TradeHoldingObservation, ...]
    holding_path_complete: bool = False


@dataclass(frozen=True)
class AccountHistoryBundle:
    account_key: str
    equity: ReconstructedEquity
    stop_out_compensation: bool


@dataclass(frozen=True)
class SourceHistoryBundle:
    accounts: Mapping[str, AccountHistoryBundle]
    sleeves: Mapping[str, SleeveHistoryBundle]


def _chunks(values: Sequence[int], size: int = 50) -> Iterable[Sequence[int]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _placeholders(count: int) -> str:
    if count <= 0:
        raise ValueError("At least one login is required")
    return ",".join(["%s"] * count)


def _is_transient_query_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    code = exc.args[0] if exc.args else None
    if isinstance(code, int) and code in TRANSIENT_QUERY_ERROR_CODES:
        return True
    return False


def _reset_failed_source(source: ReadOnlyHistorySource) -> None:
    reset = getattr(source, "reset_connection", None)
    if callable(reset):
        reset()


def _query_bisected(
    source: ReadOnlyHistorySource,
    sql_template: str,
    values: Sequence[int],
    trailing_params: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    if not values:
        return []
    sql = sql_template.format(marks=_placeholders(len(values)))
    try:
        return source.query(sql, (*values, *trailing_params))
    except Exception as exc:
        if not _is_transient_query_error(exc) or len(values) == 1:
            raise
        _reset_failed_source(source)
        middle = len(values) // 2
        return [
            *_query_bisected(source, sql_template, values[:middle], trailing_params),
            *_query_bisected(source, sql_template, values[middle:], trailing_params),
        ]


def _query_in_chunks(
    source: ReadOnlyHistorySource,
    sql_template: str,
    values: Sequence[int],
    trailing_params: Sequence[Any] = (),
    *,
    chunk_size: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in _chunks(values, size=chunk_size):
        rows.extend(_query_bisected(source, sql_template, batch, trailing_params))
    return rows


def _query_pre_window_anchors(
    source: ReadOnlyHistorySource,
    sql_template: str,
    logins: Sequence[int],
    cutoff: datetime,
    *,
    login_field: str,
    time_value: Callable[[Mapping[str, Any]], Any],
    query_time: Callable[[datetime], Any],
) -> list[dict[str, Any]]:
    """Find the nearest prior row through bounded indexed Login/time windows."""
    unresolved = set(int(login) for login in logins)
    anchors: list[dict[str, Any]] = []
    upper = cutoff
    elapsed_days = 0
    window_days = ANCHOR_INITIAL_LOOKBACK_DAYS
    while unresolved and elapsed_days < ANCHOR_MAX_LOOKBACK_DAYS:
        next_elapsed = min(
            ANCHOR_MAX_LOOKBACK_DAYS, elapsed_days + window_days
        )
        lower = cutoff - timedelta(days=next_elapsed)
        try:
            rows = _query_in_chunks(
                source,
                sql_template,
                sorted(unresolved),
                (query_time(lower), query_time(upper)),
                chunk_size=DAILY_LOGIN_BATCH_SIZE,
            )
        except Exception as exc:
            if not _is_transient_query_error(exc):
                raise
            _reset_failed_source(source)
            rows = _query_in_chunks(
                source,
                sql_template,
                sorted(unresolved),
                (query_time(lower), query_time(upper)),
                chunk_size=DAILY_LOGIN_BATCH_SIZE,
            )
        latest: dict[int, dict[str, Any]] = {}
        for row in rows:
            login = int(row[login_field])
            current = latest.get(login)
            if current is None or time_value(row) > time_value(current):
                latest[login] = row
        anchors.extend(latest.values())
        unresolved.difference_update(latest)
        upper = lower
        elapsed_days = next_elapsed
        window_days *= 2
    return anchors


def _db_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value))
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=DB_TIMEZONE)
    return value.astimezone(timezone.utc)


def _sleeve_key(account_key: str, product: str) -> str:
    return f"{account_key}|{product}"


class ReadOnlyPoolHistoryRepository:
    """Loads only candidate Login/time ranges and indexed Position/Ticket snapshots."""

    def load_source(
        self,
        source: ReadOnlyHistorySource,
        candidates: pd.DataFrame,
        as_of: datetime,
    ) -> SourceHistoryBundle:
        if candidates.empty:
            return SourceHistoryBundle({}, {})
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        account_rows = candidates.drop_duplicates("account_key")
        login_to_account = {
            int(row.Login): str(row.account_key) for row in account_rows.itertuples()
        }
        money_scale = {
            str(row.account_key): float(row.money_scale) for row in account_rows.itertuples()
        }
        logins = sorted(login_to_account)
        start = as_of.astimezone(timezone.utc) - timedelta(days=61)
        if source.platform == "MT5":
            return self._load_mt5(source, candidates, login_to_account, money_scale, logins, start, as_of)
        return self._load_mt4(source, candidates, login_to_account, money_scale, logins, start, as_of)

    def _load_mt5(
        self,
        source: ReadOnlyHistorySource,
        candidates: pd.DataFrame,
        login_to_account: Mapping[int, str],
        money_scale: Mapping[str, float],
        logins: Sequence[int],
        start: datetime,
        as_of: datetime,
    ) -> SourceHistoryBundle:
        daily_rows: list[dict[str, Any]] = []
        deal_rows: list[dict[str, Any]] = []
        current_rows: list[dict[str, Any]] = []
        start_db = start.astimezone(DB_TIMEZONE).replace(tzinfo=None)
        end_db = as_of.astimezone(DB_TIMEZONE).replace(tzinfo=None)
        daily_rows.extend(_query_in_chunks(
                source,
                f"SELECT Login, Timestamp, Balance, Credit, ProfitEquity, DailyBalance, DailyCredit, "
                f"DailyCharge, DailyCorrection, DailyBonus, DailyAgent, DailySOCompensation, "
                f"DailySOCompensationCredit FROM {source.schema}.mt5_daily_view "
                f"WHERE Login IN ({{marks}}) AND Datetime >= %s AND Datetime < %s",
                logins,
                (int(start.timestamp()), int(as_of.timestamp())),
                chunk_size=DAILY_LOGIN_BATCH_SIZE,
            ))
        daily_rows.extend(_query_pre_window_anchors(
            source,
            f"SELECT history.Login, history.Timestamp, history.Balance, history.Credit, "
            f"history.ProfitEquity, history.DailyBalance, history.DailyCredit, "
            f"history.DailyCharge, history.DailyCorrection, history.DailyBonus, "
            f"history.DailyAgent, history.DailySOCompensation, "
            f"history.DailySOCompensationCredit "
            f"FROM {source.schema}.mt5_daily_view history "
            f"WHERE history.Login IN ({{marks}}) AND history.Datetime >= %s "
            f"AND history.Datetime < %s",
            logins,
            start,
            login_field="Login",
            time_value=lambda row: int(row["Timestamp"]),
            query_time=lambda value: int(value.timestamp()),
        ))
        deal_rows.extend(_query_in_chunks(
                source,
                f"SELECT Login, Deal, PositionID, TimeMsc, Action, Entry, Symbol, Volume, VolumeExt, "
                f"Price, Profit, Commission, Storage, Fee, ContractSize, RateProfit "
                f"FROM {source.schema}.mt5_deals WHERE Login IN ({{marks}}) "
                f"AND Time >= %s AND Time < %s ORDER BY Login, TimeMsc, Deal",
                logins, (start_db, end_db), chunk_size=TRADE_LOGIN_BATCH_SIZE,
            ))
        current_rows.extend(_query_in_chunks(
                source,
                f"SELECT Login, Balance, Credit, Equity FROM {source.schema}.mt5_accounts "
                f"WHERE Login IN ({{marks}})",
                logins, chunk_size=CURRENT_LOGIN_BATCH_SIZE,
            ))

        by_account_deals: dict[str, list[dict[str, Any]]] = {key: [] for key in login_to_account.values()}
        position_to_account: dict[int, str] = {}
        for row in deal_rows:
            account_key = login_to_account.get(int(row["Login"]))
            if account_key is None:
                continue
            item = dict(row)
            item["TimeMscEpoch"] = int(_db_utc(item["TimeMsc"]).timestamp() * 1000)
            by_account_deals[account_key].append(item)
            if int(item.get("Action", -1)) in (0, 1) and int(item.get("PositionID") or 0):
                position_to_account[int(item["PositionID"])] = account_key

        snapshot_rows: list[dict[str, Any]] = []
        positions = sorted(position_to_account)
        snapshot_rows.extend(_query_in_chunks(
                source,
                f"SELECT Position, TimeModify, Profit, Storage FROM {source.schema}.mt5_positions_snap "
                f"WHERE Position IN ({{marks}}) AND TimeModify >= %s AND TimeModify < %s "
                f"ORDER BY Position, TimeModify",
                positions, (start_db, end_db), chunk_size=SNAPSHOT_ID_BATCH_SIZE,
            ))

        return self._assemble_mt5(
            candidates, login_to_account, money_scale, by_account_deals,
            daily_rows, current_rows, snapshot_rows, position_to_account, as_of,
        )

    def _assemble_mt5(
        self,
        candidates: pd.DataFrame,
        login_to_account: Mapping[int, str],
        money_scale: Mapping[str, float],
        by_account_deals: Mapping[str, list[dict[str, Any]]],
        daily_rows: list[dict[str, Any]],
        current_rows: list[dict[str, Any]],
        snapshot_rows: list[dict[str, Any]],
        position_to_account: Mapping[int, str],
        as_of: datetime,
    ) -> SourceHistoryBundle:
        daily_by_account: dict[str, list[dict[str, Any]]] = {key: [] for key in login_to_account.values()}
        for row in daily_rows:
            key = login_to_account.get(int(row["Login"]))
            if key is not None:
                daily_by_account[key].append(row)
        current_by_account = {
            login_to_account[int(row["Login"])]: row
            for row in current_rows if int(row["Login"]) in login_to_account
        }
        snapshots_by_account: dict[str, list[PositionFloatingSnapshot]] = {
            key: [] for key in login_to_account.values()
        }
        for row in snapshot_rows:
            key = position_to_account.get(int(row["Position"]))
            if key is None:
                continue
            snapshots_by_account[key].append(PositionFloatingSnapshot(
                timestamp=_db_utc(row["TimeModify"]),
                position_id=str(row["Position"]),
                floating_usd=(float(row.get("Profit") or 0.0) + float(row.get("Storage") or 0.0)) * money_scale[key],
            ))

        accounts: dict[str, AccountHistoryBundle] = {}
        sleeves: dict[str, SleeveHistoryBundle] = {}
        wanted_products = {
            str(key): {str(value) for value in group["product"]}
            for key, group in candidates.groupby("account_key")
        }
        for account_key, rows in by_account_deals.items():
            scale = money_scale[account_key]
            lifecycles = build_mt5_lifecycles(
                rows, account_key=account_key,
                product_resolver=normalize_source_product, money_scale=scale,
            )
            path_map: dict[str, list[tuple[datetime, float]]] = {}
            for snapshot in snapshots_by_account.get(account_key, ()):
                path_map.setdefault(snapshot.position_id, []).append(
                    (snapshot.timestamp, snapshot.floating_usd)
                )
            for product in wanted_products.get(account_key, set()):
                selected = tuple(item for item in lifecycles if item.product == product)
                holdings, holding_complete = holding_observations_from_snapshot_paths(
                    selected, path_map
                )
                sleeves[_sleeve_key(account_key, product)] = SleeveHistoryBundle(
                    account_key, product, selected, holdings, holding_complete
                )
            intervals = tuple(
                PositionInterval(
                    str(item.position_id),
                    datetime.fromtimestamp(item.events[0].time_msc / 1000, tz=timezone.utc),
                    datetime.fromtimestamp(item.events[-1].time_msc / 1000, tz=timezone.utc),
                )
                for item in lifecycles if item.events
            )
            ordered_daily = sorted(daily_by_account.get(account_key, []), key=lambda row: int(row["Timestamp"]))
            equity_points = build_mt5_equity_points(ordered_daily, money_scale=scale)
            anchors = [
                DailyEquityAnchor(
                    point.timestamp,
                    (float(row.get("Balance") or 0.0) + float(row.get("Credit") or 0.0)) * scale,
                    point.equity_usd,
                    point.external_cashflow_usd,
                )
                for row, point in zip(ordered_daily, equity_points)
            ]
            last_daily = anchors[-1].timestamp if anchors else as_of.astimezone(timezone.utc)
            money_events: list[AccountMoneyEvent] = []
            stop_out = any(int(row.get("Action", -1)) in MT5_SO_ACTIONS for row in rows)
            for row in rows:
                timestamp = _db_utc(row["TimeMsc"])
                action = int(row.get("Action", -1))
                value = sum(float(row.get(name) or 0.0) for name in ("Profit", "Commission", "Storage", "Fee")) * scale
                external = value if action in MT5_EXTERNAL_ACTIONS and timestamp > last_daily else 0.0
                money_events.append(AccountMoneyEvent(timestamp, int(row.get("Deal") or 0), value, external))
            current = current_by_account.get(account_key)
            if current is not None:
                anchors.append(DailyEquityAnchor(
                    as_of.astimezone(timezone.utc),
                    (float(current.get("Balance") or 0.0) + float(current.get("Credit") or 0.0)) * scale,
                    float(current.get("Equity") or 0.0) * scale,
                ))
            equity = reconstruct_intraday_equity(
                anchors, money_events, intervals, snapshots_by_account.get(account_key, ())
            )
            accounts[account_key] = AccountHistoryBundle(account_key, equity, stop_out)
        return SourceHistoryBundle(accounts, sleeves)

    def _load_mt4(
        self,
        source: ReadOnlyHistorySource,
        candidates: pd.DataFrame,
        login_to_account: Mapping[int, str],
        money_scale: Mapping[str, float],
        logins: Sequence[int],
        start: datetime,
        as_of: datetime,
    ) -> SourceHistoryBundle:
        daily_rows: list[dict[str, Any]] = []
        trade_rows: list[dict[str, Any]] = []
        current_rows: list[dict[str, Any]] = []
        start_db = start.astimezone(DB_TIMEZONE).replace(tzinfo=None)
        end_db = as_of.astimezone(DB_TIMEZONE).replace(tzinfo=None)
        daily_rows.extend(_query_in_chunks(
                source,
                f"SELECT LOGIN, TIME, BALANCE, CREDIT, DEPOSIT, EQUITY FROM {source.schema}.mt4_daily "
                f"WHERE LOGIN IN ({{marks}}) AND TIME >= %s AND TIME < %s ORDER BY LOGIN, TIME",
                logins, (start_db, end_db), chunk_size=DAILY_LOGIN_BATCH_SIZE,
            ))
        daily_rows.extend(_query_pre_window_anchors(
            source,
            f"SELECT history.LOGIN, history.TIME, history.BALANCE, history.CREDIT, "
            f"history.DEPOSIT, history.EQUITY FROM {source.schema}.mt4_daily history "
            f"WHERE history.LOGIN IN ({{marks}}) AND history.TIME >= %s "
            f"AND history.TIME < %s",
            logins,
            start,
            login_field="LOGIN",
            time_value=lambda row: _db_utc(row["TIME"]),
            query_time=lambda value: value.astimezone(DB_TIMEZONE).replace(tzinfo=None),
        ))
        trade_rows.extend(_query_in_chunks(
                source,
                f"SELECT TICKET, LOGIN, CMD, SYMBOL, VOLUME, OPEN_TIME, OPEN_PRICE, CLOSE_TIME, "
                f"CLOSE_PRICE, PROFIT, COMMISSION, SWAPS, TAXES FROM {source.schema}.mt4_trades "
                f"WHERE LOGIN IN ({{marks}}) AND CMD IN (0,1) AND CLOSE_TIME >= %s AND CLOSE_TIME < %s "
                f"AND CLOSE_TIME > OPEN_TIME ORDER BY LOGIN, CLOSE_TIME, TICKET",
                logins, (start_db, end_db), chunk_size=TRADE_LOGIN_BATCH_SIZE,
            ))
        current_rows.extend(_query_in_chunks(
                source,
                f"SELECT LOGIN, BALANCE, CREDIT, EQUITY FROM {source.schema}.mt4_users_view "
                f"WHERE LOGIN IN ({{marks}})",
                logins, chunk_size=CURRENT_LOGIN_BATCH_SIZE,
            ))

        by_account_trades: dict[str, list[dict[str, Any]]] = {key: [] for key in login_to_account.values()}
        ticket_to_account: dict[int, str] = {}
        for row in trade_rows:
            key = login_to_account.get(int(row["LOGIN"]))
            if key is None:
                continue
            item = dict(row)
            item["OPEN_TIME"] = _db_utc(item["OPEN_TIME"])
            item["CLOSE_TIME"] = _db_utc(item["CLOSE_TIME"])
            by_account_trades[key].append(item)
            ticket_to_account[int(item["TICKET"])] = key

        snapshot_rows: list[dict[str, Any]] = []
        snapshot_rows.extend(_query_in_chunks(
                source,
                f"SELECT TICKET, TimeModify, PROFIT, COMMISSION, SWAPS, TAXES "
                f"FROM {source.schema}.mt4_trades_snap WHERE TICKET IN ({{marks}}) "
                f"AND TimeModify >= %s AND TimeModify < %s ORDER BY TICKET, TimeModify",
                sorted(ticket_to_account), (start_db, end_db),
                chunk_size=SNAPSHOT_ID_BATCH_SIZE,
            ))

        daily_by_account: dict[str, list[dict[str, Any]]] = {key: [] for key in login_to_account.values()}
        for row in daily_rows:
            key = login_to_account.get(int(row["LOGIN"]))
            if key is not None:
                item = dict(row)
                item["TIME"] = _db_utc(item["TIME"])
                daily_by_account[key].append(item)
        current_by_account = {
            login_to_account[int(row["LOGIN"])]: row
            for row in current_rows if int(row["LOGIN"]) in login_to_account
        }
        snapshots_by_account: dict[str, list[PositionFloatingSnapshot]] = {key: [] for key in login_to_account.values()}
        for row in snapshot_rows:
            key = ticket_to_account.get(int(row["TICKET"]))
            if key is not None:
                snapshots_by_account[key].append(PositionFloatingSnapshot(
                    _db_utc(row["TimeModify"]), str(row["TICKET"]),
                    sum(float(row.get(name) or 0.0) for name in ("PROFIT", "COMMISSION", "SWAPS", "TAXES")) * money_scale[key],
                ))

        wanted_products = {
            str(key): {str(value) for value in group["product"]}
            for key, group in candidates.groupby("account_key")
        }
        accounts: dict[str, AccountHistoryBundle] = {}
        sleeves: dict[str, SleeveHistoryBundle] = {}
        for account_key, rows in by_account_trades.items():
            scale = money_scale[account_key]
            lifecycles = build_mt4_lifecycles(
                rows, account_key=account_key, product_resolver=normalize_source_product,
                contract_size_resolver=lambda product: product_spec(product).contract_size,
                money_scale=scale,
            )
            path_map: dict[str, list[tuple[datetime, float]]] = {}
            for snapshot in snapshots_by_account.get(account_key, ()):
                path_map.setdefault(snapshot.position_id, []).append(
                    (snapshot.timestamp, snapshot.floating_usd)
                )
            for product in wanted_products.get(account_key, set()):
                selected = tuple(item for item in lifecycles if item.product == product)
                holdings, holding_complete = holding_observations_from_snapshot_paths(
                    selected, path_map
                )
                sleeves[_sleeve_key(account_key, product)] = SleeveHistoryBundle(
                    account_key, product, selected, holdings, holding_complete
                )
            intervals = tuple(
                PositionInterval(
                    str(item.position_id),
                    datetime.fromtimestamp(item.events[0].time_msc / 1000, tz=timezone.utc),
                    datetime.fromtimestamp(item.events[-1].time_msc / 1000, tz=timezone.utc),
                ) for item in lifecycles
            )
            ordered_daily = daily_by_account.get(account_key, [])
            points = build_mt4_equity_points(ordered_daily, money_scale=scale)
            anchors = [
                DailyEquityAnchor(
                    point.timestamp,
                    (float(row.get("BALANCE") or 0.0) + float(row.get("CREDIT") or 0.0)) * scale,
                    point.equity_usd,
                    point.external_cashflow_usd,
                ) for row, point in zip(ordered_daily, points)
            ]
            money_events = [
                AccountMoneyEvent(
                    _db_utc(row["CLOSE_TIME"]), int(row["TICKET"]),
                    sum(float(row.get(name) or 0.0) for name in ("PROFIT", "COMMISSION", "SWAPS", "TAXES")) * scale,
                ) for row in rows
            ]
            current = current_by_account.get(account_key)
            if current is not None:
                anchors.append(DailyEquityAnchor(
                    as_of.astimezone(timezone.utc),
                    (float(current.get("BALANCE") or 0.0) + float(current.get("CREDIT") or 0.0)) * scale,
                    float(current.get("EQUITY") or 0.0) * scale,
                ))
            accounts[account_key] = AccountHistoryBundle(
                account_key,
                reconstruct_intraday_equity(anchors, money_events, intervals, snapshots_by_account.get(account_key, ())),
                False,
            )
        return SourceHistoryBundle(accounts, sleeves)
