from __future__ import annotations

import argparse
import json
import multiprocessing
import queue
import sys
import threading
import time
import traceback
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "problem_account_registry"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app  # noqa: E402

try:
    from scripts import run_ac_mt5_push_validation as mt5_runner  # noqa: E402
except ImportError:
    import run_ac_mt5_push_validation as mt5_runner  # noqa: E402


DEFAULT_EXCLUDED_ACTIONS = {"T", "TA", "A", "A/TA"}
DEFAULT_EXCLUDED_DATABASE_STATUSES = {"T", "TA", "A"}
MT4_COLUMNS = """
    TICKET, LOGIN, CMD, SYMBOL, VOLUME, OPEN_TIME, OPEN_PRICE, CLOSE_TIME,
    CLOSE_PRICE, COMMISSION, TAXES, SWAPS, PROFIT, SL, TP, REASON, MAGIC, COMMENT
"""
MT5_CANDIDATE_SHARD = timedelta(hours=12)
MT4_CANDIDATE_SHARD = timedelta(days=1)
MIN_CANDIDATE_SHARD = timedelta(minutes=30)
AGGREGATE_READ_TIMEOUT = 45
PROFILE_BATCH_SIZE = 10
MIN_PROFILE_BATCH_SIZE = 5
PROFILE_READ_TIMEOUT = 45
PROFILE_SEMAPHORES: dict[str, threading.Semaphore] = {}
PROFILE_SEMAPHORES_LOCK = threading.Lock()
CANDIDATE_ROW_BATCH_SIZE = 50
MIN_CANDIDATE_ROW_BATCH_SIZE = 5
TIME_FIRST_LOGIN_BATCH_SIZE = 2000
MT5_TIME_INDEX_BY_SCHEMA = {
    "mt5_export_new": "INDEX_TIME",
    "crm_vn_mt5_live2": "INDEX_TIME",
}
MT5_POSITION_INDEX_BY_SCHEMA = {
    "mt5_export_new": "INDEX_POSITIONID",
    "crm_vn_mt5_live2": "INDEX_POSITIONID",
}
SCREEN_PROCESS_BATCH_SIZE = 125
MAX_SCREEN_PROCESSES = 2
MIN_SUSPECTED_INTERVAL_NET = 50.0
MIN_ABSOLUTE_SUSPECTED_INTERVAL_NET = 100.0
MIN_SUSPECTED_INTERVAL_RETURN_PCT = 10.0
DEEP_CANDIDATE_TIMEOUT_SECONDS = 300
DEEP_HEARTBEAT_SECONDS = 10

DEEP_STAGE_LABELS = {
    "load_history": "读取全历史订单",
    "build_context": "构建推盘订单上下文",
    "finance": "复核资金与收益",
    "cross_account_sync": "比对跨账户同步交易",
    "tick_analysis": "复核报价与盈利订单",
    "score": "汇总证据与评分",
}


class DeepCandidateTimeout(RuntimeError):
    """A single remote deep check exceeded its bounded execution budget."""


@dataclass(frozen=True)
class CandidateFilters:
    require_period_profit: bool = True
    limit_orders: bool = True
    max_orders: int = 200
    require_max_lot: bool = True
    min_max_lot: float = 0.01
    require_total_profit: bool = True
    limit_deposit: bool = True
    max_deposit: float = 2000.0
    limit_active_ratio: bool = True
    max_active_ratio: float = 30.0
    exclude_handled: bool = True

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> CandidateFilters:
        return cls(
            require_period_profit=bool(args.require_period_profit),
            limit_orders=bool(args.limit_orders),
            max_orders=int(args.max_orders),
            require_max_lot=bool(args.require_max_lot),
            min_max_lot=float(args.min_max_lot),
            require_total_profit=bool(args.require_total_profit),
            limit_deposit=bool(args.limit_deposit),
            max_deposit=float(args.max_deposit),
            limit_active_ratio=bool(args.limit_active_ratio),
            max_active_ratio=float(args.max_active_ratio),
            exclude_handled=bool(args.exclude_handled),
        )

    def payload(self) -> dict:
        return {
            "requirePeriodProfit": self.require_period_profit,
            "limitOrders": self.limit_orders,
            "maxOrders": self.max_orders,
            "requireMaxLot": self.require_max_lot,
            "minMaxLot": self.min_max_lot,
            "requireTotalProfit": self.require_total_profit,
            "limitDeposit": self.limit_deposit,
            "maxDeposit": self.max_deposit,
            "limitActiveRatio": self.limit_active_ratio,
            "maxActiveRatio": self.max_active_ratio,
            "excludeHandled": self.exclude_handled,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover previously unmarked market-pushing accounts.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-orders", type=int, default=200)
    parser.add_argument("--require-period-profit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--limit-orders", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-max-lot", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-max-lot", type=float, default=0.01)
    parser.add_argument("--require-total-profit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--limit-deposit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-deposit", type=float, default=2000.0)
    parser.add_argument("--limit-active-ratio", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-active-ratio", type=float, default=30.0)
    parser.add_argument("--exclude-handled", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--small-order-priority", type=int, default=200)
    parser.add_argument("--deep-limit", type=int, default=50)
    parser.add_argument("--deep-candidate-timeout", type=int, default=DEEP_CANDIDATE_TIMEOUT_SECONDS)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs" / "push_discovery")
    return parser.parse_args()


def emit(stage: str, message: str, percent: int, **data) -> None:
    payload = {"stage": stage, "message": message, "percent": percent, **data}
    print("PROGRESS " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def excluded_logins(records: list[dict], actions: set[str] | None = None) -> set[str]:
    actions = {app.normalize_text(value).upper() for value in (actions or DEFAULT_EXCLUDED_ACTIONS)}
    return {
        app.normalize_text(record.get("账号"))
        for record in records
        if app.normalize_text(record.get("账号"))
        and app.normalize_text(record.get("建议动作")).upper() in actions
    }


def _batches(values: list[int], size: int = 200):
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def _profile_semaphore(source: dict) -> threading.Semaphore:
    key = app.normalize_text(source.get("host")) or app.normalize_text(source.get("name")) or "default"
    with PROFILE_SEMAPHORES_LOCK:
        return PROFILE_SEMAPHORES.setdefault(key, threading.Semaphore(1))


def _candidate_time_shards(source: dict, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    width = MT5_CANDIDATE_SHARD if source.get("kind") == "mt5_deals" else MT4_CANDIDATE_SHARD
    shards: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        shard_end = min(cursor + width, end)
        shards.append((cursor, shard_end))
        cursor = shard_end
    return shards


def _source_routed_logins(source: dict, cur, logins: list[int]) -> set[int]:
    """Keep only accounts assigned to this CRM/server route.

    Some exports are shared by multiple labelled servers (for example both AC
    MT4 sources).  The fact table alone therefore cannot establish which
    server owns a login.
    """
    route = source.get("account_route")
    if not isinstance(route, dict):
        return set(logins)
    schema = app.normalize_text(route.get("schema"))
    server_code = app.normalize_text(route.get("mt_server_code"))
    if not schema or not server_code:
        return set(logins)

    routed: set[int] = set()
    for batch in _batches(logins):
        placeholders = ",".join(["%s"] * len(batch))
        cur.execute(
            f"select mt_login from `{schema}`.`mt_users_account` "
            f"where mt_server_code = %s and mt_login in ({placeholders})",
            [server_code, *batch],
        )
        routed.update(
            app.mysql_int(row.get("mt_login"))
            for row in cur.fetchall()
            if app.mysql_int(row.get("mt_login")) > 0
        )
    return routed


def _candidate_profiles(
    source: dict,
    cur,
    logins: list[int],
    filters: CandidateFilters,
    as_of: datetime,
    progress: Callable[[int, int], None] | None = None,
    batch_size: int = PROFILE_BATCH_SIZE,
) -> dict[int, dict]:
    profiles: dict[int, dict] = {login: {} for login in logins}
    needs_money = filters.require_total_profit or filters.limit_deposit
    needs_lifetime = needs_money or filters.limit_active_ratio
    effective_batch_size = batch_size if needs_lifetime else 500
    batches = list(_batches(logins, effective_batch_size))

    for batch_index, batch in enumerate(batches, start=1):
        placeholders = ",".join(["%s"] * len(batch))
        if source.get("kind") == "mt5_deals":
            cur.execute(
                f"select Login, Registration, Status, `Group` as AccountGroup, Balance "
                f"from `{source['schema']}`.`mt5_users_view` where Login in ({placeholders})",
                batch,
            )
        else:
            cur.execute(
                f"select LOGIN as Login, REGDATE as Registration, STATUS as Status, "
                f"CURRENCY as Currency, `GROUP` as AccountGroup, BALANCE as Balance "
                f"from `{source['schema']}`.`mt4_users_view` where LOGIN in ({placeholders})",
                batch,
            )
        for row in cur.fetchall():
            profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)

        if not needs_lifetime:
            if progress:
                progress(batch_index, len(batches))
            continue
        if needs_money and source.get("kind") == "mt5_deals":
            cur.execute(
                f"""
                select Login,
                       sum(coalesce(Profit,0)+coalesce(Commission,0)+coalesce(Storage,0)+coalesce(Fee,0))
                           as LedgerNetRaw,
                       sum(case when Action=2 and Profit>0 and upper(coalesce(Comment,'')) like 'DEP-%%'
                           then Profit else 0 end) as DepositRaw
                from `{source['schema']}`.`{source['table']}`
                where Login in ({placeholders}) and Action >= 2
                group by Login
                """,
                batch,
            )
            for row in cur.fetchall():
                profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)
        elif needs_money:
            cur.execute(
                f"""
                select LOGIN as Login, sum(coalesce(PROFIT,0)) as LedgerNetRaw,
                       sum(case when PROFIT>0
                                and upper(coalesce(COMMENT,'')) not like '%%RST-%%'
                                and upper(coalesce(COMMENT,'')) not like '%%NEGATIVE BALANCE%%'
                                and upper(coalesce(COMMENT,'')) not like '%%ZERO BALANCE%%'
                                and upper(coalesce(COMMENT,'')) not like '%%COMP%%'
                                and upper(coalesce(COMMENT,'')) not like '%%REWARD%%'
                                and upper(coalesce(COMMENT,'')) not like '%%BONUS%%'
                                and upper(coalesce(COMMENT,'')) not like 'TFM-%%'
                                and upper(coalesce(COMMENT,'')) not like 'TFH-%%'
                                and upper(coalesce(COMMENT,'')) not like '%%INTERNAL TRANSFER%%'
                           then PROFIT else 0 end) as DepositRaw
                from `{source['schema']}`.`{source['table']}`
                where LOGIN in ({placeholders}) and CMD=6
                group by LOGIN
                """,
                batch,
            )
            for row in cur.fetchall():
                profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)

        if filters.limit_active_ratio and source.get("kind") == "mt5_deals":
            cur.execute(
                f"""
                select Login, count(distinct date(Time)) as ActiveDays
                from `{source['schema']}`.`{source['table']}`
                where Login in ({placeholders}) and Action in (0,1) and Entry=0 and PositionID<>0
                group by Login
                """,
                batch,
            )
            for row in cur.fetchall():
                profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)
        elif filters.limit_active_ratio:
            cur.execute(
                f"""
                select LOGIN as Login, count(distinct date(OPEN_TIME)) as ActiveDays
                from `{source['schema']}`.`{source['table']}`
                where LOGIN in ({placeholders}) and CMD in (0,1)
                group by LOGIN
                """,
                batch,
            )
            for row in cur.fetchall():
                profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)
        if progress:
            progress(batch_index, len(batches))

    for profile in profiles.values():
        money_meta = app.account_money_meta(
            profile.get("Currency"), profile.get("AccountGroup"), source.get("name")
        )
        scale = app.numeric_value(money_meta.get("moneyScale")) or 1.0
        registration = app.parse_trade_time(profile.get("Registration"))
        registration_days = max((as_of.date() - registration.date()).days + 1, 1) if registration else 0
        active_days = app.mysql_int(profile.get("ActiveDays"))
        if needs_money and "Balance" in profile:
            profile["TotalNetRaw"] = (
                app.numeric_value(profile.get("Balance")) - app.numeric_value(profile.get("LedgerNetRaw"))
            )
        profile.update({
            "Currency": money_meta.get("displayCurrency") or money_meta.get("currency") or "",
            "MoneyScale": scale,
            "TotalNet": app.rounded(app.numeric_value(profile.get("TotalNetRaw")) * scale),
            "DepositTotal": app.rounded(app.numeric_value(profile.get("DepositRaw")) * scale),
            "RegistrationText": app.trade_time_text(registration),
            "RegistrationDays": registration_days,
            "ActiveDays": active_days,
            "ActiveRatio": app.rounded(active_days / registration_days * 100, 2) if registration_days else None,
            "LifetimeDataAvailable": "TotalNetRaw" in profile or "ActiveDays" in profile,
        })
    return profiles


def _load_candidate_profiles(
    source: dict,
    logins: list[int],
    filters: CandidateFilters,
    as_of: datetime,
    status: Callable[[str], None] | None = None,
) -> dict[int, dict]:
    batch_size = PROFILE_BATCH_SIZE
    while True:
        display_batch_size = (
            batch_size
            if filters.require_total_profit or filters.limit_deposit or filters.limit_active_ratio
            else 500
        )
        query_source = {
            **source,
            "read_timeout": min(
                max(app.mysql_int(source.get("read_timeout"), PROFILE_READ_TIMEOUT), 1),
                PROFILE_READ_TIMEOUT,
            ),
        }
        try:
            with app.mysql_trade_connect(query_source) as conn:
                with conn.cursor() as cur:
                    return _candidate_profiles(
                        source,
                        cur,
                        logins,
                        filters,
                        as_of,
                        progress=(
                            (lambda index, total, size=display_batch_size: status(
                                f"{source['name']}资料读取 {index}/{total} 批（每批{size}账号）"
                            )) if status else None
                        ),
                        batch_size=batch_size,
                    )
        except Exception as exc:
            if not transient_mysql_failure(exc) or batch_size <= MIN_PROFILE_BATCH_SIZE:
                raise
            batch_size = max(batch_size // 2, MIN_PROFILE_BATCH_SIZE)
            if status:
                status(f"{source['name']}历史收益批次超时，缩小为每批{batch_size}账号重试")


def candidate_filter_reasons(
    candidate: dict,
    filters: CandidateFilters,
    include_lifetime: bool = True,
) -> list[str]:
    reasons: list[str] = []
    if include_lifetime and filters.require_total_profit and (
        not candidate.get("lifetimeDataAvailable") or app.numeric_value(candidate.get("totalNet")) <= 0
    ):
        reasons.append("历史交易净收益未大于0")
    if include_lifetime and filters.limit_deposit and (
        not candidate.get("lifetimeDataAvailable")
        or app.numeric_value(candidate.get("depositTotal")) > filters.max_deposit
    ):
        reasons.append("累计入金超过上限或不可用")
    active_ratio = candidate.get("activeRatio")
    if include_lifetime and filters.limit_active_ratio and (
        active_ratio is None or app.numeric_value(active_ratio) > filters.max_active_ratio
    ):
        reasons.append("活跃天数占比超过上限或不可用")
    if filters.exclude_handled and app.normalize_text(candidate.get("databaseStatus")).upper() in DEFAULT_EXCLUDED_DATABASE_STATUSES:
        reasons.append("数据库状态已处置")
    return reasons


def push_lifetime_economic_reasons(candidate: dict) -> list[str]:
    if not candidate.get("lifetimeDataAvailable"):
        return ["全历史净收益不可用"]
    if app.numeric_value(candidate.get("totalNet")) <= 0:
        return ["全历史交易净收益未形成正向经济结果"]
    return []


def _candidate_profile_payload(profile: dict) -> dict:
    return {
        "currency": profile.get("Currency", ""),
        "databaseStatus": app.normalize_text(profile.get("Status")),
        "registration": profile.get("RegistrationText", ""),
        "registrationDays": app.mysql_int(profile.get("RegistrationDays")),
        "activeDays": app.mysql_int(profile.get("ActiveDays")),
        "activeRatio": profile.get("ActiveRatio"),
        "totalNet": app.rounded(profile.get("TotalNet")),
        "depositTotal": app.rounded(profile.get("DepositTotal")),
        "lifetimeDataAvailable": bool(profile.get("LifetimeDataAvailable")),
    }


def _candidate_interval_sql(source: dict) -> str:
    if source.get("kind") == "mt5_deals":
        return f"""
            select Login,
                   count(distinct case when Entry in (1, 2, 3) and PositionID <> 0 then PositionID end) as ClosedOrders,
                   max(case when coalesce(VolumeExt, 0) > 0 then VolumeExt / 100000000.0 else Volume / 10000.0 end) as MaxLot,
                   sum(coalesce(Profit, 0) + coalesce(Commission, 0) + coalesce(Storage, 0) + coalesce(Fee, 0)) as PeriodNetRaw
            from `{source['schema']}`.`{source['table']}`
            where Action in (0, 1) and Time >= %s and Time < %s
            group by Login
        """
    return f"""
        select LOGIN as Login, count(*) as ClosedOrders, max(VOLUME / 100.0) as MaxLot,
               sum(coalesce(PROFIT, 0) + coalesce(COMMISSION, 0) + coalesce(SWAPS, 0) + coalesce(TAXES, 0)) as PeriodNetRaw
        from `{source['schema']}`.`{source['table']}`
        where CMD in (0, 1) and CLOSE_TIME >= %s and CLOSE_TIME < %s
        group by LOGIN
        having ClosedOrders >= 1
    """


def _query_candidate_interval(
    source: dict,
    start: datetime,
    end: datetime,
    status: Callable[[str], None] | None = None,
) -> list[dict]:
    query_source = {
        **source,
        "read_timeout": min(
            max(app.mysql_int(source.get("read_timeout"), AGGREGATE_READ_TIMEOUT), 1),
            AGGREGATE_READ_TIMEOUT,
        ),
    }
    try:
        with app.mysql_trade_connect(query_source) as conn:
            with conn.cursor() as cur:
                cur.execute(_candidate_interval_sql(source), [start, end])
                return list(cur.fetchall())
    except Exception as exc:
        if not transient_mysql_failure(exc) or end - start <= MIN_CANDIDATE_SHARD:
            raise
        midpoint = start + (end - start) / 2
        if status:
            status(
                f"{source['name']} {start:%m-%d %H:%M}~{end:%m-%d %H:%M}超时，"
                f"拆为{(midpoint - start).total_seconds() / 3600:g}小时重试"
            )
        return [
            *_query_candidate_interval(source, start, midpoint, status),
            *_query_candidate_interval(source, midpoint, end, status),
        ]


def _merge_candidate_rows(rows: list[dict]) -> list[dict]:
    merged: dict[int, dict] = {}
    for row in rows:
        login = app.mysql_int(row.get("Login"))
        if login <= 0:
            continue
        target = merged.setdefault(login, {
            "Login": login,
            "ClosedOrders": 0,
            "MaxShardClosedOrders": 0,
            "MaxLot": 0.0,
            "PeriodNetRaw": 0.0,
        })
        shard_orders = app.mysql_int(row.get("ClosedOrders"))
        target["ClosedOrders"] += shard_orders
        target["MaxShardClosedOrders"] = max(target["MaxShardClosedOrders"], shard_orders)
        target["MaxLot"] = max(app.numeric_value(target.get("MaxLot")), app.numeric_value(row.get("MaxLot")))
        target["PeriodNetRaw"] += app.numeric_value(row.get("PeriodNetRaw"))
    return list(merged.values())


def _window_candidate_rows(
    source: dict,
    start: datetime,
    end: datetime,
    shard_complete: Callable[[int, int], None] | None = None,
    status: Callable[[str], None] | None = None,
) -> list[dict]:
    shards = _candidate_time_shards(source, start, end)
    rows: list[dict] = []
    for index, (shard_start, shard_end) in enumerate(shards, start=1):
        rows.extend(_query_candidate_interval(source, shard_start, shard_end, status))
        if shard_complete:
            shard_complete(index, len(shards))
    return _merge_candidate_rows(rows)


def _exact_mt5_closed_orders(
    source: dict,
    cur,
    logins: list[int],
    start: datetime,
    end: datetime,
) -> dict[int, int]:
    counts: dict[int, int] = {}
    for batch in _batches(logins, 100):
        placeholders = ",".join(["%s"] * len(batch))
        cur.execute(
            f"""
            select Login, count(distinct PositionID) as ClosedOrders
            from `{source['schema']}`.`{source['table']}`
            where Login in ({placeholders}) and Action in (0,1) and Entry in (1,2,3)
              and Time >= %s and Time < %s and PositionID <> 0
            group by Login
            """,
            [*batch, start, end],
        )
        counts.update({
            app.mysql_int(row.get("Login")): app.mysql_int(row.get("ClosedOrders"))
            for row in cur.fetchall()
            if app.mysql_int(row.get("Login")) > 0
        })
    return counts


def _passes_merged_window_filters(row: dict, source: dict, filters: CandidateFilters) -> bool:
    if app.mysql_int(row.get("ClosedOrders")) < 1:
        return False
    if filters.require_period_profit and app.numeric_value(row.get("PeriodNetRaw")) <= 0:
        return False
    if filters.require_max_lot and app.numeric_value(row.get("MaxLot")) <= filters.min_max_lot:
        return False
    if not filters.limit_orders:
        return True
    if source.get("kind") != "mt5_deals":
        return app.mysql_int(row.get("ClosedOrders")) <= filters.max_orders
    return app.mysql_int(row.get("MaxShardClosedOrders")) <= filters.max_orders


def source_candidates(
    source: dict,
    start: datetime,
    end: datetime,
    filters: CandidateFilters,
    shard_complete: Callable[[int, int], None] | None = None,
    status: Callable[[str], None] | None = None,
) -> list[dict]:
    started = time.perf_counter()
    rows = [
        row for row in _window_candidate_rows(source, start, end, shard_complete, status)
        if _passes_merged_window_filters(row, source, filters)
    ]
    if status:
        status(f"{source['name']}窗口聚合完成，等待历史收益查询槽位")
    with _profile_semaphore(source):
        with app.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                logins = [app.mysql_int(row.get("Login")) for row in rows if app.mysql_int(row.get("Login")) > 0]
                routed_logins = _source_routed_logins(source, cur, logins)
                rows = [row for row in rows if app.mysql_int(row.get("Login")) in routed_logins]
                if source.get("kind") == "mt5_deals" and filters.limit_orders:
                    ambiguous = [
                        app.mysql_int(row.get("Login"))
                        for row in rows
                        if app.mysql_int(row.get("ClosedOrders")) > filters.max_orders
                    ]
                    if ambiguous:
                        if status:
                            status(f"{source['name']}精确复核{len(ambiguous)}个跨分片单数")
                        exact_counts = _exact_mt5_closed_orders(source, cur, ambiguous, start, end)
                        for row in rows:
                            login = app.mysql_int(row.get("Login"))
                            if login in exact_counts:
                                row["ClosedOrders"] = exact_counts[login]
                        rows = [row for row in rows if app.mysql_int(row.get("ClosedOrders")) <= filters.max_orders]
                retained_logins = {app.mysql_int(row.get("Login")) for row in rows}
                logins = sorted(routed_logins & retained_logins)
        if status:
            status(f"{source['name']}读取{len(logins)}个窗口候选账户资料")
        metadata_filters = CandidateFilters(
            require_period_profit=filters.require_period_profit,
            limit_orders=filters.limit_orders,
            max_orders=filters.max_orders,
            require_max_lot=filters.require_max_lot,
            min_max_lot=filters.min_max_lot,
            require_total_profit=False,
            limit_deposit=False,
            max_deposit=filters.max_deposit,
            limit_active_ratio=False,
            max_active_ratio=filters.max_active_ratio,
            exclude_handled=filters.exclude_handled,
        )
        profiles = _load_candidate_profiles(source, logins, metadata_filters, end, status)
    return [{
        "source": source["name"],
        "platform": source["platform"],
        "server": source["server"],
        "login": str(app.mysql_int(row.get("Login"))),
        "closedOrders": app.mysql_int(row.get("ClosedOrders")),
        "maxLot": app.rounded(row.get("MaxLot"), 4),
        "periodNetRaw": app.rounded(row.get("PeriodNetRaw")),
        "periodNet": app.rounded(
            app.numeric_value(row.get("PeriodNetRaw"))
            * (app.numeric_value(profiles.get(app.mysql_int(row.get("Login")), {}).get("MoneyScale")) or 1.0)
        ),
        **_candidate_profile_payload(profiles.get(app.mysql_int(row.get("Login")), {})),
        "aggregateSeconds": round(time.perf_counter() - started, 3),
    } for row in rows if app.mysql_int(row.get("Login")) > 0]


def mt4_row(source: dict, raw: dict) -> dict:
    opened = app.parse_trade_time(app.mysql_datetime_text(raw.get("OPEN_TIME")))
    closed = app.parse_trade_time(app.mysql_datetime_text(raw.get("CLOSE_TIME")))
    return {
        "id": app.normalize_text(raw.get("TICKET")),
        "source_id": source["name"],
        "data_source": "mysql",
        "platform": "MT4",
        "server": source["server"],
        "account": app.normalize_text(raw.get("LOGIN")),
        "ticket": app.normalize_text(raw.get("TICKET")),
        "open_time": app.trade_time_text(opened),
        "close_time": app.trade_time_text(closed),
        "open_time_msc": app.trade_time_text(opened),
        "close_time_msc": app.trade_time_text(closed),
        "type": "buy" if app.mysql_int(raw.get("CMD")) == 0 else "sell",
        "volume": app.normalize_mt4_volume(raw.get("VOLUME")),
        "symbol": app.normalize_text(raw.get("SYMBOL")),
        "open_price": app.numeric_value(raw.get("OPEN_PRICE")),
        "close_price": app.numeric_value(raw.get("CLOSE_PRICE")),
        "commission": app.numeric_value(raw.get("COMMISSION")),
        "taxes": app.numeric_value(raw.get("TAXES")),
        "swap": app.numeric_value(raw.get("SWAPS")),
        "profit": app.numeric_value(raw.get("PROFIT")),
        "reason": app.trade_reason_label("MT4", raw.get("REASON")),
        "reason_code": app.mysql_int(raw.get("REASON"), -1),
        "comment": app.normalize_text(raw.get("COMMENT")),
        "expert_id": app.normalize_text(raw.get("MAGIC")) if app.mysql_int(raw.get("MAGIC")) else "",
        "holding_seconds": max((closed - opened).total_seconds(), 0.0) if opened and closed else "",
    }


def _merge_grouped_rows(target: dict[str, list[dict]], source: dict[str, list[dict]]) -> None:
    for login, rows in source.items():
        target[login].extend(rows)


def _mt5_time_index(source: dict) -> str:
    return MT5_TIME_INDEX_BY_SCHEMA.get(source.get("schema"), "idx_mt5_deals_Time")


def _mt5_position_index(source: dict) -> str:
    return MT5_POSITION_INDEX_BY_SCHEMA.get(source.get("schema"), "idx_mt5_deals_PositionID")


def _qualified_mt5_deal_columns(alias: str = "deals") -> str:
    return ", ".join(
        f"{alias}.{column.strip()}"
        for column in mt5_runner.DEAL_COLUMNS.split(",")
        if column.strip()
    )


def _load_mt4_candidate_batch(
    source: dict,
    logins: list[int],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    query_source = {**source, "read_timeout": AGGREGATE_READ_TIMEOUT}
    try:
        with app.mysql_trade_connect(query_source) as conn:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(logins))
                cur.execute(
                    f"select {MT4_COLUMNS} from `{source['schema']}`.`{source['table']}` where LOGIN in ({placeholders}) and CMD in (0,1) and CLOSE_TIME >= %s and CLOSE_TIME < %s order by LOGIN, OPEN_TIME, TICKET",
                    [*logins, start, end],
                )
                for raw in cur.fetchall():
                    row = mt4_row(source, raw)
                    grouped[row["account"]].append(row)
    except Exception as exc:
        if not transient_mysql_failure(exc) or len(logins) <= MIN_CANDIDATE_ROW_BATCH_SIZE:
            raise
        midpoint = len(logins) // 2
        _merge_grouped_rows(grouped, _load_mt4_candidate_batch(source, logins[:midpoint], start, end))
        _merge_grouped_rows(grouped, _load_mt4_candidate_batch(source, logins[midpoint:], start, end))
    return grouped


def _load_mt4_candidate_time_shard(
    source: dict,
    logins: list[int],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict]]:
    """Read one close-time shard once, then retain the exact candidate accounts."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    query_source = {**source, "read_timeout": AGGREGATE_READ_TIMEOUT}
    placeholders = ",".join(["%s"] * len(logins))
    try:
        with app.mysql_trade_connect(query_source) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"select {MT4_COLUMNS} from `{source['schema']}`.`{source['table']}` "
                    f"force index (INDEX_CLOSETIME) where CLOSE_TIME >= %s and CLOSE_TIME < %s "
                    f"and LOGIN in ({placeholders}) and CMD in (0,1) order by LOGIN, OPEN_TIME, TICKET",
                    [start, end, *logins],
                )
                for raw in cur.fetchall():
                    row = mt4_row(source, raw)
                    grouped[row["account"]].append(row)
        return grouped
    except Exception as exc:
        if transient_mysql_failure(exc) and end - start > MIN_CANDIDATE_SHARD:
            midpoint = start + (end - start) / 2
            _merge_grouped_rows(grouped, _load_mt4_candidate_time_shard(source, logins, start, midpoint))
            _merge_grouped_rows(grouped, _load_mt4_candidate_time_shard(source, logins, midpoint, end))
            return grouped
        for batch in _batches(logins, CANDIDATE_ROW_BATCH_SIZE):
            _merge_grouped_rows(grouped, _load_mt4_candidate_batch(source, batch, start, end))
        return grouped


def load_mt4_candidate_rows(source: dict, candidates: list[dict], start: datetime, end: datetime) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    logins = [int(item["login"]) for item in candidates]
    for shard_start, shard_end in _candidate_time_shards(source, start, end):
        for batch in _batches(logins, TIME_FIRST_LOGIN_BATCH_SIZE):
            _merge_grouped_rows(
                grouped,
                _load_mt4_candidate_time_shard(source, batch, shard_start, shard_end),
            )
    for rows in grouped.values():
        rows.sort(key=lambda row: (
            app.parse_trade_time(row.get("open_time_msc") or row.get("open_time")) or datetime.min,
            app.mysql_int(row.get("ticket")),
        ))
    return grouped


def _load_mt5_candidate_batch(
    source: dict,
    candidate_logins: list[int],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict]]:
    deals_by_login: dict[str, list[dict]] = defaultdict(list)
    query_source = {**source, "read_timeout": AGGREGATE_READ_TIMEOUT}
    try:
        with app.mysql_trade_connect(query_source) as conn:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(candidate_logins))
                cur.execute(
                    f"select Login, PositionID from `{source['schema']}`.`{source['table']}` where Login in ({placeholders}) and Action in (0,1) and Entry in (1,2,3) and Time >= %s and Time < %s and PositionID <> 0 group by Login, PositionID",
                    [*candidate_logins, start, end],
                )
                close_pairs = {
                    (app.mysql_int(row.get("Login")), app.mysql_int(row.get("PositionID")))
                    for row in cur.fetchall()
                    if app.mysql_int(row.get("Login")) > 0 and app.mysql_int(row.get("PositionID")) > 0
                }
                position_ids = sorted({position_id for _, position_id in close_pairs})
                for position_offset in range(0, len(position_ids), 250):
                    position_batch = position_ids[position_offset:position_offset + 250]
                    position_placeholders = ",".join(["%s"] * len(position_batch))
                    cur.execute(
                        f"select {mt5_runner.DEAL_COLUMNS} from `{source['schema']}`.`{source['table']}` where PositionID in ({position_placeholders}) and Action in (0,1) and Entry in (0,1,2,3) order by Login, PositionID, Time, Deal",
                        position_batch,
                    )
                    for deal in cur.fetchall():
                        pair = (app.mysql_int(deal.get("Login")), app.mysql_int(deal.get("PositionID")))
                        if pair in close_pairs:
                            deals_by_login[str(pair[0])].append(deal)
    except Exception as exc:
        if not transient_mysql_failure(exc) or len(candidate_logins) <= MIN_CANDIDATE_ROW_BATCH_SIZE:
            raise
        midpoint = len(candidate_logins) // 2
        _merge_grouped_rows(
            deals_by_login,
            _load_mt5_candidate_batch(source, candidate_logins[:midpoint], start, end),
        )
        _merge_grouped_rows(
            deals_by_login,
            _load_mt5_candidate_batch(source, candidate_logins[midpoint:], start, end),
        )
    return deals_by_login


def _load_mt5_candidate_time_shard(
    source: dict,
    candidate_logins: list[int],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict]]:
    """Select closed positions from a bounded time index and fetch their complete deals."""
    deals_by_login: dict[str, list[dict]] = defaultdict(list)
    query_source = {**source, "read_timeout": AGGREGATE_READ_TIMEOUT}
    placeholders = ",".join(["%s"] * len(candidate_logins))
    sql = f"""
        select {_qualified_mt5_deal_columns()}
        from (
            select Login, PositionID
            from `{source['schema']}`.`{source['table']}` force index ({_mt5_time_index(source)})
            where Time >= %s and Time < %s and Login in ({placeholders})
              and Action in (0,1) and Entry in (1,2,3) and PositionID <> 0
            group by Login, PositionID
        ) closed
        join `{source['schema']}`.`{source['table']}` deals force index ({_mt5_position_index(source)})
          on deals.Login = closed.Login and deals.PositionID = closed.PositionID
        where deals.Action in (0,1) and deals.Entry in (0,1,2,3)
        order by deals.Login, deals.PositionID, deals.Time, deals.Deal
    """
    try:
        with app.mysql_trade_connect(query_source) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, [start, end, *candidate_logins])
                for deal in cur.fetchall():
                    login = str(app.mysql_int(deal.get("Login")))
                    if login != "0":
                        deals_by_login[login].append(deal)
        return deals_by_login
    except Exception as exc:
        if transient_mysql_failure(exc) and end - start > MIN_CANDIDATE_SHARD:
            midpoint = start + (end - start) / 2
            _merge_grouped_rows(
                deals_by_login,
                _load_mt5_candidate_time_shard(source, candidate_logins, start, midpoint),
            )
            _merge_grouped_rows(
                deals_by_login,
                _load_mt5_candidate_time_shard(source, candidate_logins, midpoint, end),
            )
            return deals_by_login
        for batch in _batches(candidate_logins, CANDIDATE_ROW_BATCH_SIZE):
            _merge_grouped_rows(
                deals_by_login,
                _load_mt5_candidate_batch(source, batch, start, end),
            )
        return deals_by_login


def load_mt5_candidate_rows(source: dict, candidates: list[dict], start: datetime, end: datetime) -> dict[str, list[dict]]:
    candidate_logins = [int(item["login"]) for item in candidates]
    deals_by_login: dict[str, list[dict]] = defaultdict(list)
    for shard_start, shard_end in _candidate_time_shards(source, start, end):
        for batch in _batches(candidate_logins, TIME_FIRST_LOGIN_BATCH_SIZE):
            _merge_grouped_rows(
                deals_by_login,
                _load_mt5_candidate_time_shard(source, batch, shard_start, shard_end),
            )
    for login, deals in deals_by_login.items():
        unique_deals = {
            app.mysql_int(deal.get("Deal")): deal
            for deal in deals
            if app.mysql_int(deal.get("Deal")) > 0
        }
        deals_by_login[login] = sorted(
            unique_deals.values(),
            key=lambda deal: (
                app.mysql_int(deal.get("PositionID")),
                app.mysql_datetime_text(deal.get("TimeMsc") or deal.get("Time")),
                app.mysql_int(deal.get("Deal")),
            ),
        )
    return {
        login: mt5_runner.corrected_mt5_positions(
            deals,
            source,
            login,
            app.account_money_meta(source_name=source.get("name")),
        )
        for login, deals in deals_by_login.items()
    }


def load_candidate_rows(source: dict, candidates: list[dict], start: datetime, end: datetime) -> dict[str, list[dict]]:
    if not candidates:
        return {}
    if source.get("kind") == "mt5_deals":
        return load_mt5_candidate_rows(source, candidates, start, end)
    return load_mt4_candidate_rows(source, candidates, start, end)


def load_candidate_rows_timed(
    source: dict,
    candidates: list[dict],
    start: datetime,
    end: datetime,
) -> tuple[dict[str, list[dict]], float]:
    started = time.perf_counter()
    return load_candidate_rows(source, candidates, start, end), time.perf_counter() - started


def screen_candidate(candidate: dict, rows: list[dict], small_order_priority: int) -> dict:
    if not rows:
        return {**candidate, "screenStatus": "no_rows", "initialScore": 0.0, "deepEligible": False, "routeReasons": []}
    push_context = app.toxic_build_push_context(rows)
    core_rows = push_context["rows"]
    behavior = push_context["behavior"]
    result = app.calculate_toxic_results(
        candidate["login"],
        core_rows,
        ["market_pushing"],
        "initial",
        {"available": False, "reason": "全平台发现初筛不读取资金快照"},
        push_context=push_context,
    )[0]
    initial_score = app.numeric_value(result.get("score"))
    concentration = app.numeric_value(behavior.get("concentratedCoreVolumeRatio"))
    short_hold = app.numeric_value(behavior.get("coreShortHoldVolumeRatio"))
    quiet = app.numeric_value(behavior.get("quietGapRatio"))
    ea_ratio = app.numeric_value(behavior.get("eaVolumeRatio"))
    copy_ratio = app.numeric_value(behavior.get("copyVolumeRatio"))
    strong_structure = concentration >= 70 and short_hold >= 75 and quiet >= 35
    small_strong = len(core_rows) <= 8 and concentration >= 80 and short_hold >= 70
    automation_attention = initial_score >= 20 and max(ea_ratio, copy_ratio) >= 50
    reasons = []
    if initial_score >= 40:
        reasons.append("初筛分达到40")
    if strong_structure:
        reasons.append("集中度、短持仓和动态停手同时明显")
    if small_strong:
        reasons.append("小样本但结构高度集中")
    if automation_attention:
        reasons.append("EA/跟单占比较高且结构已有风险")
    priority = initial_score
    priority += 15 if strong_structure else 0
    priority += 10 if small_strong else 0
    priority += 5 if automation_attention else 0
    priority += 5 if len(rows) <= small_order_priority else 0
    return {
        **candidate,
        "screenStatus": "ok",
        "exactOrders": len(rows),
        "analysisOrders": len(core_rows),
        "initialScore": initial_score,
        "initialLevel": result.get("level"),
        "initialConfidence": app.mysql_int(result.get("confidence")),
        "initialTriggers": result.get("triggeredRules", []),
        "concentratedCoreVolumeRatio": concentration,
        "coreShortHoldVolumeRatio": short_hold,
        "quietGapRatio": quiet,
        "eaVolumeRatio": ea_ratio,
        "copyVolumeRatio": copy_ratio,
        "deepEligible": bool(reasons),
        "routeReasons": reasons,
        "routePriority": app.rounded(priority, 2),
    }


def screen_candidate_batch(
    items: list[tuple[int, dict, list[dict]]],
    small_order_priority: int,
) -> list[tuple[int, dict | None, str]]:
    results = []
    for index, candidate, rows in items:
        try:
            results.append((index, screen_candidate(candidate, rows, small_order_priority), ""))
        except Exception as exc:
            results.append((index, None, str(exc)))
    return results


def screen_candidates(
    candidates: list[dict],
    rows_by_source: dict[str, dict[str, list[dict]]],
    small_order_priority: int,
    workers: int,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict], list[dict]]:
    items = [
        (
            index,
            candidate,
            rows_by_source.get(candidate["source"], {}).get(candidate["login"], []),
        )
        for index, candidate in enumerate(candidates)
    ]

    def sequential() -> tuple[list[dict], list[dict]]:
        output: list[dict | None] = [None] * len(items)
        errors = []
        for completed, (index, result, error) in enumerate(
            screen_candidate_batch(items, small_order_priority),
            start=1,
        ):
            output[index] = result
            if error:
                errors.append({**candidates[index], "error": error})
            if progress and (completed % 250 == 0 or completed == len(items)):
                progress(completed, len(items))
        return [result for result in output if result is not None], errors

    process_count = min(MAX_SCREEN_PROCESSES, max(workers, 1))
    if process_count <= 1 or len(items) < SCREEN_PROCESS_BATCH_SIZE * 2:
        return sequential()

    batches = [
        items[offset:offset + SCREEN_PROCESS_BATCH_SIZE]
        for offset in range(0, len(items), SCREEN_PROCESS_BATCH_SIZE)
    ]
    output: list[dict | None] = [None] * len(items)
    errors = []
    completed = 0
    try:
        with ProcessPoolExecutor(max_workers=process_count) as executor:
            futures = [
                executor.submit(screen_candidate_batch, batch, small_order_priority)
                for batch in batches
            ]
            for future in as_completed(futures):
                batch_results = future.result()
                completed += len(batch_results)
                for index, result, error in batch_results:
                    output[index] = result
                    if error:
                        errors.append({**candidates[index], "error": error})
                if progress:
                    progress(completed, len(items))
        return [result for result in output if result is not None], errors
    except Exception:
        if progress:
            progress(0, len(items))
        return sequential()


def load_deep_rows(source: dict, login: str) -> list[dict]:
    """Load all account history after a candidate passes the windowed screen."""
    if source.get("kind") == "mt5_deals":
        return mt5_runner.load_all_closed_trades(source, login)["rows"]
    rows = app.query_mysql_mt4_source(source, login, limit=None)
    return [
        row
        for row in rows
        if (closed := app.parse_trade_time(row.get("close_time"))) and closed.year > 1971
    ]


def suspected_push_interval_profit(rows: list[dict], mixed_episodes: dict | None = None) -> dict:
    """Summarize orders inside the same dynamic sessions used by push scoring."""
    session_profile = app.toxic_dynamic_push_sessions(rows)
    sessions = list(session_profile.get("sessions") or [])
    mixed_episodes = mixed_episodes or {}
    selected_ids = {
        app.mysql_int(value)
        for value in (mixed_episodes.get("confirmedSessionIds") or mixed_episodes.get("candidateSessionIds") or [])
        if app.mysql_int(value) > 0
    }
    if selected_ids:
        basis = "confirmed_coordination" if mixed_episodes.get("confirmed") else "coordinated_candidate"
        selected = [(index, items) for index, items in enumerate(sessions, start=1) if index in selected_ids]
    else:
        basis = "dynamic_concentration"
        selected = [(index, items) for index, items in enumerate(sessions, start=1) if len(items) >= 2]

    interval_rows: list[dict] = []
    flattened: list[dict] = []
    for session_index, items in selected:
        current_rows = [row for _, row in items]
        if not current_rows:
            continue
        flattened.extend(current_rows)
        opened = [app.parse_trade_time(row.get("open_time_msc") or row.get("open_time")) for row in current_rows]
        opened = [value for value in opened if value]
        closed = [app.parse_trade_time(row.get("close_time_msc") or row.get("close_time")) for row in current_rows]
        closed = [value for value in closed if value]
        gross_profit = sum(app.numeric_value(row.get("profit")) for row in current_rows)
        net_profit = sum(app.toxic_trade_net(row) for row in current_rows)
        interval_rows.append({
            "session": session_index,
            "start": app.trade_time_text(min(opened)) if opened else "",
            "end": app.trade_time_text(max(closed or opened)) if closed or opened else "",
            "orders": len(current_rows),
            "volume": app.rounded(sum(max(app.numeric_value(row.get("volume")), 0.0) for row in current_rows), 4),
            "grossProfit": app.rounded(gross_profit),
            "netProfit": app.rounded(net_profit),
            "costs": app.rounded(net_profit - gross_profit),
        })

    gross_profit = sum(app.numeric_value(row.get("profit")) for row in flattened)
    net_profit = sum(app.toxic_trade_net(row) for row in flattened)
    total_volume = sum(max(app.numeric_value(row.get("volume")), 0.0) for row in flattened)
    return {
        "available": bool(flattened),
        "basis": basis if flattened else "none",
        "confirmed": bool(flattened and mixed_episodes.get("confirmed")),
        "intervalCount": len(interval_rows),
        "orders": len(flattened),
        "orderRatio": app.rounded(len(flattened) / len(rows) * 100, 1) if rows else 0,
        "volume": app.rounded(total_volume, 4),
        "grossProfit": app.rounded(gross_profit),
        "netProfit": app.rounded(net_profit),
        "costs": app.rounded(net_profit - gross_profit),
        "winningOrders": sum(app.toxic_trade_net(row) > 0 for row in flattened),
        "losingOrders": sum(app.toxic_trade_net(row) < 0 for row in flattened),
        "intervals": interval_rows,
    }


def push_economic_evidence(candidate: dict, suspected_intervals: dict) -> dict:
    total_net = app.numeric_value(candidate.get("totalNet"))
    deposit_total = max(app.numeric_value(candidate.get("depositTotal")), 0.0)
    interval_net = app.numeric_value(suspected_intervals.get("netProfit"))
    interval_return_pct = interval_net / deposit_total * 100 if deposit_total > 0 else None
    absolute_qualified = interval_net >= MIN_ABSOLUTE_SUSPECTED_INTERVAL_NET
    relative_qualified = bool(
        deposit_total > 0
        and interval_net >= MIN_SUSPECTED_INTERVAL_NET
        and interval_return_pct is not None
        and interval_return_pct >= MIN_SUSPECTED_INTERVAL_RETURN_PCT
    )

    if not candidate.get("lifetimeDataAvailable"):
        reason = "全历史净收益不可用，无法确认高风险高回报"
    elif total_net <= 0:
        reason = "全历史交易净收益不为正"
    elif not suspected_intervals.get("available") or interval_net <= 0:
        reason = "疑似推盘区间没有形成正净收益"
    elif not (absolute_qualified or relative_qualified):
        if interval_return_pct is None:
            reason = (
                f"疑似区间净收益仅{app.rounded(interval_net)}，且入金基数不可用；"
                f"未达到{app.rounded(MIN_ABSOLUTE_SUSPECTED_INTERVAL_NET)}的绝对收益门槛"
            )
        else:
            reason = (
                f"疑似区间净收益{app.rounded(interval_net)}、约占入金{app.rounded(interval_return_pct, 1)}%；"
                f"未达到{app.rounded(MIN_ABSOLUTE_SUSPECTED_INTERVAL_NET)}，也未同时达到"
                f"{app.rounded(MIN_SUSPECTED_INTERVAL_NET)}和{app.rounded(MIN_SUSPECTED_INTERVAL_RETURN_PCT, 1)}%"
            )
    else:
        reason = "疑似区间已形成与资金规模相符的正向经济结果"

    return {
        "qualified": bool(
            candidate.get("lifetimeDataAvailable")
            and total_net > 0
            and suspected_intervals.get("available")
            and interval_net > 0
            and (absolute_qualified or relative_qualified)
        ),
        "reason": reason,
        "totalNet": app.rounded(total_net),
        "depositTotal": app.rounded(deposit_total),
        "intervalNet": app.rounded(interval_net),
        "intervalReturnPct": app.rounded(interval_return_pct, 1) if interval_return_pct is not None else None,
        "absoluteQualified": absolute_qualified,
        "relativeQualified": relative_qualified,
        "minimumIntervalNet": MIN_SUSPECTED_INTERVAL_NET,
        "minimumAbsoluteIntervalNet": MIN_ABSOLUTE_SUSPECTED_INTERVAL_NET,
        "minimumIntervalReturnPct": MIN_SUSPECTED_INTERVAL_RETURN_PCT,
    }


def deep_candidate(
    candidate: dict,
    source: dict,
    progress: Callable[[str], None] | None = None,
) -> dict:
    def stage(name: str) -> None:
        if progress:
            progress(name)

    started = time.perf_counter()
    stage("load_history")
    rows = load_deep_rows(source, candidate["login"])
    if not rows:
        raise RuntimeError("账号全历史没有可检测订单")
    stage("build_context")
    push_context = app.toxic_build_push_context(rows)
    core_rows = push_context["rows"]
    metrics = app.trade_metrics(core_rows)
    stage("finance")
    finance = app.toxic_finance_summary(candidate["login"], core_rows, metrics)
    original_loader = app.toxic_sync_candidates_for_source

    def source_aware_loader(
        candidate_source: dict,
        excluded_login: str,
        target_seconds: set[str],
        target_symbols: set[str] | None = None,
        target_directions: set[str] | None = None,
    ) -> list[dict]:
        effective_exclusion = excluded_login if candidate_source.get("server") == source.get("server") else "0"
        return original_loader(candidate_source, effective_exclusion, target_seconds, target_symbols, target_directions)

    app.toxic_sync_candidates_for_source = source_aware_loader
    try:
        stage("cross_account_sync")
        sync = app.toxic_cross_account_sync(candidate["login"], core_rows)
    finally:
        app.toxic_sync_candidates_for_source = original_loader
    stage("tick_analysis")
    tick = app.toxic_winning_ticks(candidate["login"], core_rows)
    stage("score")
    result = app.calculate_toxic_results(
        candidate["login"],
        core_rows,
        ["market_pushing"],
        "deep",
        finance,
        tick,
        sync,
        push_context=push_context,
    )[0]
    chain = result.get("evidenceChain") or {}
    suspected_intervals = suspected_push_interval_profit(core_rows, result.get("mixedEpisodes"))
    economic_evidence = push_economic_evidence(candidate, suspected_intervals)
    return {
        **candidate,
        "deepScope": "all_history",
        "screeningWindowOrders": app.mysql_int(candidate.get("exactOrders") or candidate.get("closedOrders")),
        "deepOrders": len(rows),
        "deepAnalysisOrders": len(core_rows),
        "deepScore": app.numeric_value(result.get("score")),
        "deepLevel": result.get("level"),
        "deepConfidence": app.mysql_int(result.get("confidence")),
        "headline": chain.get("headline") or result.get("summary"),
        "reasoning": chain.get("reasoning") or "",
        "triggeredRules": result.get("triggeredRules", []),
        "limitations": result.get("limitations", []),
        "scoreBasis": chain.get("scoreBasis") or {},
        "suspectedPushIntervals": suspected_intervals,
        "economicEvidence": economic_evidence,
        "tickAvailable": bool(tick.get("available")),
        "tickAnalyzedOrders": app.mysql_int(tick.get("analyzedOrders")),
        "coordinatedMatchedRatio": app.numeric_value(sync.get("coordinatedMatchedRatio")),
        "coordinatedCloseRatio": app.numeric_value(sync.get("coordinatedCloseRatio")),
        "recurringPeerAccounts": app.mysql_int(sync.get("recurringPeerAccounts")),
        "suspectedAccomplices": (result.get("suspectedAccomplices") or [])[:10],
        "deepElapsedSeconds": round(time.perf_counter() - started, 2),
    }


def _deep_candidate_child(
    candidate: dict,
    source: dict,
    event_queue,
    result_queue,
) -> None:
    """Run one deep check outside the discovery process so it can be terminated safely."""
    try:
        result = deep_candidate(candidate, source, progress=lambda name: event_queue.put({"stage": name}))
        result_queue.put({"result": result})
    except BaseException as exc:
        result_queue.put({
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        })


def run_deep_candidate_bounded(
    candidate: dict,
    source: dict,
    *,
    timeout_seconds: int,
    progress: Callable[[str, float, bool], None],
) -> dict:
    """Run one candidate with stage heartbeats and a hard, recoverable process boundary."""
    context = multiprocessing.get_context("spawn")
    event_queue = context.Queue()
    result_queue = context.Queue()
    process = context.Process(
        target=_deep_candidate_child,
        args=(candidate, source, event_queue, result_queue),
        name=f"push-deep-{candidate['login']}",
    )
    process.start()
    started = time.monotonic()
    current_stage = "load_history"
    next_heartbeat = started
    outcome: dict | None = None
    try:
        while process.is_alive() or outcome is None:
            while True:
                try:
                    event = event_queue.get_nowait()
                except queue.Empty:
                    break
                stage_name = str(event.get("stage") or "")
                if stage_name in DEEP_STAGE_LABELS:
                    current_stage = stage_name
                    progress(current_stage, time.monotonic() - started, False)
            try:
                outcome = result_queue.get_nowait()
            except queue.Empty:
                pass
            if outcome is not None:
                break
            elapsed = time.monotonic() - started
            if elapsed >= timeout_seconds:
                process.terminate()
                process.join(timeout=5)
                raise DeepCandidateTimeout(
                    f"深检超过{timeout_seconds}秒：当前阶段{DEEP_STAGE_LABELS[current_stage]}"
                )
            if time.monotonic() >= next_heartbeat:
                progress(current_stage, elapsed, True)
                next_heartbeat = time.monotonic() + DEEP_HEARTBEAT_SECONDS
            process.join(timeout=0.25)
        if outcome.get("error"):
            raise RuntimeError(str(outcome["error"]))
        result = outcome.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("深检子进程未返回结果")
        return result
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        event_queue.close()
        result_queue.close()


def transient_mysql_failure(exc: Exception) -> bool:
    args = getattr(exc, "args", ())
    try:
        code = int(args[0]) if args else 0
    except (TypeError, ValueError):
        code = 0
    return code in {1205, 2006, 2013}


def main() -> int:
    args = parse_args()
    filters = CandidateFilters.from_args(args)
    if not (1 <= args.days <= 30):
        raise ValueError("days must be between 1 and 30")
    if not (1 <= args.max_orders <= 1000):
        raise ValueError("max-orders must be between 1 and 1000")
    if not (0 <= args.min_max_lot <= 100_000):
        raise ValueError("min-max-lot must be between 0 and 100000")
    if not (0 <= args.max_deposit <= 10_000_000):
        raise ValueError("max-deposit must be between 0 and 10000000")
    if not (0 <= args.max_active_ratio <= 100):
        raise ValueError("max-active-ratio must be between 0 and 100")
    if not (1 <= args.deep_limit <= 300):
        raise ValueError("deep-limit must be between 1 and 300")
    if not (30 <= args.deep_candidate_timeout <= 900):
        raise ValueError("deep-candidate-timeout must be between 30 and 900 seconds")
    if not (1 <= args.workers <= 8):
        raise ValueError("workers must be between 1 and 8")

    end = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    start = end - timedelta(days=args.days)
    run_id = f"push_discovery_{end:%Y%m%d_%H%M%S}_utc"
    output_dir = args.output_root.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    sources = list(app.MYSQL_SOURCES)
    source_map = {source["name"]: source for source in sources}
    known_excluded = excluded_logins(app.load_records()) if filters.exclude_handled else set()
    all_started = time.perf_counter()
    failures: list[dict] = []
    emit("aggregate", f"正在汇总{len(sources)}个服务器近{args.days}天活跃账户", 5)

    candidates: list[dict] = []
    aggregate_total_shards = sum(len(_candidate_time_shards(source, start, end)) for source in sources)
    aggregate_completed_shards = 0
    aggregate_completed_sources = 0
    aggregate_progress = 5
    aggregate_lock = threading.Lock()

    def callbacks(source_name: str):
        def shard_complete(index: int, total: int) -> None:
            nonlocal aggregate_completed_shards, aggregate_progress
            with aggregate_lock:
                aggregate_completed_shards += 1
                aggregate_progress = 5 + round(
                    aggregate_completed_shards / max(aggregate_total_shards, 1) * 10
                )
                emit(
                    "aggregate",
                    f"候选聚合：{source_name} 分片 {index}/{total}（全平台 {aggregate_completed_shards}/{aggregate_total_shards}）",
                    aggregate_progress,
                )

        def status(message: str) -> None:
            with aggregate_lock:
                emit("aggregate", message, aggregate_progress)

        return shard_complete, status

    with ThreadPoolExecutor(max_workers=min(args.workers, len(sources))) as executor:
        futures = {}
        for source in sources:
            shard_complete, status = callbacks(source["name"])
            futures[executor.submit(
                source_candidates,
                source,
                start,
                end,
                filters,
                shard_complete,
                status,
            )] = source
        for future in as_completed(futures):
            source = futures[future]
            try:
                candidates.extend(future.result())
            except Exception as exc:
                failures.append({"stage": "aggregate", "source": source["name"], "error": str(exc)})
            with aggregate_lock:
                aggregate_completed_sources += 1
                aggregate_progress = max(
                    aggregate_progress,
                    15 + round(aggregate_completed_sources / max(len(sources), 1) * 10),
                )
                emit(
                    "aggregate",
                    f"服务器聚合完成 {aggregate_completed_sources}/{len(sources)}：{source['name']}",
                    aggregate_progress,
                )
    emit("aggregate", f"候选聚合完成，正在应用账户限制（{len(candidates)}个窗口候选）", 25)
    before_exclusion = len(candidates)
    excluded_candidates: list[dict] = []
    excluded_by_reason: dict[str, int] = defaultdict(int)
    retained: list[dict] = []
    for candidate in candidates:
        reasons = candidate_filter_reasons(candidate, filters, include_lifetime=False)
        if filters.exclude_handled and candidate["login"] in known_excluded:
            reasons.append("本地台账已处置")
        if reasons:
            excluded_candidates.append({**candidate, "filterReasons": reasons})
            for reason in set(reasons):
                excluded_by_reason[reason] += 1
        else:
            retained.append(candidate)
    candidates = retained
    candidates.sort(key=lambda row: (row["source"], app.mysql_int(row["login"])))
    write_json(output_dir / "candidates.json", candidates)
    write_json(output_dir / "excluded_candidates.json", excluded_candidates)
    reason_text = "，".join(f"{reason} {count}个" for reason, count in excluded_by_reason.items()) or "未启用额外限制"
    emit(
        "screen",
        f"窗口候选{before_exclusion}个，基础限制后保留{len(candidates)}个（{reason_text}），开始结构初筛",
        27,
        candidates=len(candidates),
        excluded=before_exclusion - len(candidates),
        excludedByReason=dict(excluded_by_reason),
    )

    by_source: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        by_source[candidate["source"]].append(candidate)
    rows_by_source: dict[str, dict[str, list[dict]]] = {}
    with ThreadPoolExecutor(max_workers=min(args.workers, len(by_source))) as executor:
        futures = {
            executor.submit(
                load_candidate_rows_timed,
                source_map[source_name],
                source_candidates_rows,
                start,
                end,
            ): source_name
            for source_name, source_candidates_rows in by_source.items()
        }
        for index, future in enumerate(as_completed(futures), start=1):
            source_name = futures[future]
            try:
                rows_by_source[source_name], elapsed = future.result()
                loaded_orders = sum(len(rows) for rows in rows_by_source[source_name].values())
                message = (
                    f"订单读取完成 {index}/{len(by_source)}：{source_name} "
                    f"{len(rows_by_source[source_name])}账号/{loaded_orders}单/{elapsed:.1f}s"
                )
            except Exception as exc:
                rows_by_source[source_name] = {}
                failures.append({"stage": "load_rows", "source": source_name, "error": str(exc)})
                message = f"订单读取失败 {index}/{len(by_source)}：{source_name}"
            emit("screen", message, 27 + round(index / len(by_source) * 23))

    def screen_progress(completed: int, total: int) -> None:
        if completed == 0:
            emit("screen", "结构初筛并行不可用，已回退串行计算", 50)
            return
        emit(
            "screen",
            f"结构初筛 {completed}/{total}",
            50 + round(completed / max(total, 1) * 10),
        )

    screened, screen_failures = screen_candidates(
        candidates,
        rows_by_source,
        args.small_order_priority,
        args.workers,
        screen_progress,
    )
    failures.extend({"stage": "screen", **failure} for failure in screen_failures)
    screened.sort(key=lambda row: (-app.numeric_value(row.get("routePriority")), row["server"], app.mysql_int(row["login"])))
    for rank, row in enumerate(screened, start=1):
        row["screenRank"] = rank
    eligible = [row for row in screened if row.get("deepEligible")]
    structural_eligible = len(eligible)
    lifetime_profiled = 0
    unprofiled_structural = 0
    needs_lifetime_filters = True
    if needs_lifetime_filters and eligible:
        structural_candidates = eligible
        lifetime_retained: list[dict] = []
        profile_chunk_size = max(25, min(args.deep_limit * 2, 200))
        profile_lock = threading.Lock()

        def profile_status(message: str) -> None:
            with profile_lock:
                emit("profile", message, 60 + round(lifetime_profiled / len(structural_candidates) * 2))

        for offset in range(0, len(structural_candidates), profile_chunk_size):
            chunk = structural_candidates[offset:offset + profile_chunk_size]
            emit(
                "profile",
                f"按结构排名应用历史限制 {offset + 1}-{offset + len(chunk)}/{len(structural_candidates)}",
                60 + round(lifetime_profiled / len(structural_candidates) * 2),
            )
            chunk_by_source: dict[str, list[dict]] = defaultdict(list)
            for candidate in chunk:
                chunk_by_source[candidate["source"]].append(candidate)
            profiles_by_source: dict[str, dict[int, dict]] = {}
            profile_filters = CandidateFilters(
                require_period_profit=filters.require_period_profit,
                limit_orders=filters.limit_orders,
                max_orders=filters.max_orders,
                require_max_lot=filters.require_max_lot,
                min_max_lot=filters.min_max_lot,
                require_total_profit=True,
                limit_deposit=True,
                max_deposit=filters.max_deposit,
                limit_active_ratio=filters.limit_active_ratio,
                max_active_ratio=filters.max_active_ratio,
                exclude_handled=filters.exclude_handled,
            )
            with ThreadPoolExecutor(max_workers=min(args.workers, len(chunk_by_source))) as executor:
                futures = {
                    executor.submit(
                        _load_candidate_profiles,
                        source_map[source_name],
                        [app.mysql_int(row["login"]) for row in source_candidates_rows],
                        profile_filters,
                        end,
                        profile_status,
                    ): source_name
                    for source_name, source_candidates_rows in chunk_by_source.items()
                }
                for future in as_completed(futures):
                    source_name = futures[future]
                    try:
                        profiles_by_source[source_name] = future.result()
                    except Exception as exc:
                        profiles_by_source[source_name] = {}
                        failures.append({"stage": "profile", "source": source_name, "error": str(exc)})

            for candidate in chunk:
                profile = profiles_by_source.get(candidate["source"], {}).get(app.mysql_int(candidate["login"]), {})
                candidate.update(_candidate_profile_payload(profile))
                reasons = candidate_filter_reasons(candidate, filters)
                if not filters.require_total_profit:
                    reasons.extend(push_lifetime_economic_reasons(candidate))
                if reasons:
                    excluded_candidates.append({**candidate, "filterReasons": reasons})
                    for reason in set(reasons):
                        excluded_by_reason[reason] += 1
                else:
                    lifetime_retained.append(candidate)
            lifetime_profiled += len(chunk)
            if len(lifetime_retained) >= args.deep_limit:
                break
        eligible = lifetime_retained
        unprofiled_structural = max(structural_eligible - lifetime_profiled, 0)

    selected = eligible[: args.deep_limit]
    write_json(output_dir / "excluded_candidates.json", excluded_candidates)
    write_json(output_dir / "screened.json", screened)
    write_json(output_dir / "deep_candidates.json", selected)
    emit(
        "deep",
        f"结构命中{structural_eligible}个，按排名画像{lifetime_profiled or structural_eligible}个，"
        f"历史限制后{len(eligible)}个，本轮深检前{len(selected)}个",
        62,
        screened=len(screened),
        eligible=len(eligible),
        selected=len(selected),
    )

    app.toxic_cached_tick_mapping = lambda login, report_symbol: None
    deep_checked_results: list[dict] = []
    deep_results: list[dict] = []
    economic_rejections: list[dict] = []
    for index, candidate in enumerate(selected, start=1):
        deep_progress = 62 + round((index - 1) / max(len(selected), 1) * 34)

        def report_deep_stage(stage: str, elapsed: float, heartbeat: bool) -> None:
            suffix = "，仍在读取" if heartbeat else ""
            emit(
                "deep",
                f"深检 {index}/{len(selected)}：{candidate['server']}/{candidate['login']} "
                f"{DEEP_STAGE_LABELS[stage]}（{elapsed:.0f}秒）{suffix}",
                deep_progress,
                candidateIndex=index,
                candidateTotal=len(selected),
                candidateServer=candidate["server"],
                candidateLogin=candidate["login"],
                deepStage=stage,
                deepElapsedSeconds=round(elapsed, 1),
                heartbeat=heartbeat,
            )

        try:
            result = run_deep_candidate_bounded(
                candidate,
                source_map[candidate["source"]],
                timeout_seconds=args.deep_candidate_timeout,
                progress=report_deep_stage,
            )
            deep_checked_results.append(result)
            if result.get("economicEvidence", {}).get("qualified"):
                deep_results.append(result)
                economic_status = "经济证据通过"
            else:
                economic_rejections.append(result)
                economic_status = "经济证据不足，未列入结果"
            write_json(output_dir / "deep_results_checkpoint.json", deep_checked_results)
            message = (
                f"深检 {index}/{len(selected)}：{result['server']}/{result['login']} "
                f"{result['initialScore']}→{result['deepScore']}，{economic_status}"
            )
        except Exception as exc:
            failures.append({
                "stage": "deep",
                **candidate,
                "error": str(exc),
                "recoverable": isinstance(exc, DeepCandidateTimeout),
                "timeoutSeconds": args.deep_candidate_timeout if isinstance(exc, DeepCandidateTimeout) else 0,
            })
            message = f"深检 {index}/{len(selected)} 失败：{candidate['server']}/{candidate['login']}"
        emit("deep", message, 62 + round(index / max(len(selected), 1) * 34))
    deep_results.sort(key=lambda row: (-app.numeric_value(row.get("deepScore")), -app.numeric_value(row.get("routePriority"))))
    for rank, row in enumerate(deep_results, start=1):
        row["deepRank"] = rank
    write_json(output_dir / "deep_results.json", deep_results)
    write_json(output_dir / "economic_rejections.json", economic_rejections)
    write_json(output_dir / "failures.json", failures)
    summary = {
        "runId": run_id,
        "windowStartUtc": start.isoformat(sep=" "),
        "windowEndUtc": end.isoformat(sep=" "),
        "days": args.days,
        "maxOrders": args.max_orders,
        "smallOrderPriority": args.small_order_priority,
        "deepLimit": args.deep_limit,
        "deepScope": "all_history",
        "filters": filters.payload(),
        "excludedActions": sorted(DEFAULT_EXCLUDED_ACTIONS) if filters.exclude_handled else [],
        "excludedDatabaseStatuses": sorted(DEFAULT_EXCLUDED_DATABASE_STATUSES) if filters.exclude_handled else [],
        "sources": [source["name"] for source in sources],
        "aggregateCandidates": before_exclusion,
        "excludedKnownAccounts": before_exclusion - len(candidates),
        "excludedByReason": dict(excluded_by_reason),
        "screenedAccounts": len(screened),
        "structuralEligible": structural_eligible,
        "lifetimeProfiled": lifetime_profiled,
        "unprofiledStructural": unprofiled_structural,
        "deepEligible": len(eligible),
        "deepSelected": len(selected),
        "deepCompleted": len(deep_checked_results),
        "economicQualified": len(deep_results),
        "economicallyRejected": len(economic_rejections),
        "economicRules": {
            "requirePositiveLifetimeNet": True,
            "minimumIntervalNet": MIN_SUSPECTED_INTERVAL_NET,
            "minimumAbsoluteIntervalNet": MIN_ABSOLUTE_SUSPECTED_INTERVAL_NET,
            "minimumIntervalReturnPct": MIN_SUSPECTED_INTERVAL_RETURN_PCT,
        },
        "deepPending": unprofiled_structural + max(len(eligible) - len(selected), 0),
        "score60Plus": sum(app.numeric_value(row.get("deepScore")) >= 60 for row in deep_results),
        "score75Plus": sum(app.numeric_value(row.get("deepScore")) >= 75 for row in deep_results),
        "failures": len(failures),
        "elapsedSeconds": round(time.perf_counter() - all_started, 1),
        "outputDir": str(output_dir),
    }
    write_json(output_dir / "summary.json", summary)
    emit("done", "全平台推盘发现完成", 100, summary=summary)
    print("RESULT " + str(output_dir / "summary.json"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
