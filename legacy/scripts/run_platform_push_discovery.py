from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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
) -> dict[int, dict]:
    profiles: dict[int, dict] = {login: {} for login in logins}
    needs_money = filters.require_total_profit or filters.limit_deposit
    needs_lifetime = needs_money or filters.limit_active_ratio

    for batch in _batches(logins):
        placeholders = ",".join(["%s"] * len(batch))
        if source.get("kind") == "mt5_deals":
            cur.execute(
                f"select Login, Registration, Status, `Group` as AccountGroup "
                f"from `{source['schema']}`.`mt5_users_view` where Login in ({placeholders})",
                batch,
            )
        else:
            cur.execute(
                f"select LOGIN as Login, REGDATE as Registration, STATUS as Status, "
                f"CURRENCY as Currency, `GROUP` as AccountGroup "
                f"from `{source['schema']}`.`mt4_users_view` where LOGIN in ({placeholders})",
                batch,
            )
        for row in cur.fetchall():
            profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)

        if source.get("kind") == "mt5_deals" and needs_money:
            cur.execute(
                f"""
                select daily.Login, daily.Currency, daily.`Group` as AccountGroup
                from `{source['schema']}`.`mt5_daily_view` daily
                inner join (
                    select Login, max(Datetime) as LatestDatetime
                    from `{source['schema']}`.`mt5_daily_view`
                    where Login in ({placeholders})
                    group by Login
                ) latest on latest.Login = daily.Login and latest.LatestDatetime = daily.Datetime
                """,
                batch,
            )
            for row in cur.fetchall():
                profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)

        if not needs_lifetime:
            continue
        if source.get("kind") == "mt5_deals":
            cur.execute(
                f"""
                select Login,
                       sum(case when Action in (0,1)
                           then coalesce(Profit,0)+coalesce(Commission,0)+coalesce(Storage,0)+coalesce(Fee,0)
                           else 0 end) as TotalNetRaw,
                       sum(case when Action=2 and Profit>0 and upper(coalesce(Comment,'')) like 'DEP-%%'
                           then Profit else 0 end) as DepositRaw,
                       count(distinct case when Action in (0,1) and Entry=0 and PositionID<>0
                           then date(Time) end) as ActiveDays
                from `{source['schema']}`.`{source['table']}`
                where Login in ({placeholders}) and Action in (0,1,2)
                group by Login
                """,
                batch,
            )
        else:
            cur.execute(
                f"""
                select LOGIN as Login,
                       sum(case when CMD in (0,1) and CLOSE_TIME>'1971-01-01'
                           then coalesce(PROFIT,0)+coalesce(COMMISSION,0)+coalesce(SWAPS,0)+coalesce(TAXES,0)
                           else 0 end) as TotalNetRaw,
                       sum(case when CMD=6 and PROFIT>0
                                and upper(coalesce(COMMENT,'')) not like '%%RST-%%'
                                and upper(coalesce(COMMENT,'')) not like '%%NEGATIVE BALANCE%%'
                                and upper(coalesce(COMMENT,'')) not like '%%ZERO BALANCE%%'
                                and upper(coalesce(COMMENT,'')) not like '%%COMP%%'
                                and upper(coalesce(COMMENT,'')) not like '%%REWARD%%'
                                and upper(coalesce(COMMENT,'')) not like '%%BONUS%%'
                                and upper(coalesce(COMMENT,'')) not like 'TFM-%%'
                                and upper(coalesce(COMMENT,'')) not like 'TFH-%%'
                                and upper(coalesce(COMMENT,'')) not like '%%INTERNAL TRANSFER%%'
                           then PROFIT else 0 end) as DepositRaw,
                       count(distinct case when CMD in (0,1) then date(OPEN_TIME) end) as ActiveDays
                from `{source['schema']}`.`{source['table']}`
                where LOGIN in ({placeholders}) and CMD in (0,1,6)
                group by LOGIN
                """,
                batch,
            )
        for row in cur.fetchall():
            profiles.setdefault(app.mysql_int(row.get("Login")), {}).update(row)

    for profile in profiles.values():
        money_meta = app.account_money_meta(
            profile.get("Currency"), profile.get("AccountGroup"), source.get("name")
        )
        scale = app.numeric_value(money_meta.get("moneyScale")) or 1.0
        registration = app.parse_trade_time(profile.get("Registration"))
        registration_days = max((as_of.date() - registration.date()).days + 1, 1) if registration else 0
        active_days = app.mysql_int(profile.get("ActiveDays"))
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


def candidate_filter_reasons(candidate: dict, filters: CandidateFilters) -> list[str]:
    reasons: list[str] = []
    if filters.require_total_profit and (
        not candidate.get("lifetimeDataAvailable") or app.numeric_value(candidate.get("totalNet")) <= 0
    ):
        reasons.append("历史交易净收益未大于0")
    if filters.limit_deposit and (
        not candidate.get("lifetimeDataAvailable")
        or app.numeric_value(candidate.get("depositTotal")) > filters.max_deposit
    ):
        reasons.append("累计入金超过上限或不可用")
    active_ratio = candidate.get("activeRatio")
    if filters.limit_active_ratio and (
        active_ratio is None or app.numeric_value(active_ratio) > filters.max_active_ratio
    ):
        reasons.append("活跃天数占比超过上限或不可用")
    if filters.exclude_handled and app.normalize_text(candidate.get("databaseStatus")).upper() in DEFAULT_EXCLUDED_DATABASE_STATUSES:
        reasons.append("数据库状态已处置")
    return reasons


def source_candidates(
    source: dict,
    start: datetime,
    end: datetime,
    filters: CandidateFilters,
) -> list[dict]:
    having = ["ClosedOrders >= 1"]
    parameters: list[object] = [start, end]
    if filters.limit_orders:
        having.append("ClosedOrders <= %s")
        parameters.append(filters.max_orders)
    if filters.require_max_lot:
        having.append("MaxLot > %s")
        parameters.append(filters.min_max_lot)
    if filters.require_period_profit:
        having.append("PeriodNetRaw > 0")
    having_sql = " and ".join(having)
    if source.get("kind") == "mt5_deals":
        sql = f"""
            select Login,
                   count(distinct case when Entry in (1, 2, 3) and PositionID <> 0 then PositionID end) as ClosedOrders,
                   max(case when coalesce(VolumeExt, 0) > 0 then VolumeExt / 100000000.0 else Volume / 10000.0 end) as MaxLot,
                   sum(coalesce(Profit, 0) + coalesce(Commission, 0) + coalesce(Storage, 0) + coalesce(Fee, 0)) as PeriodNetRaw
            from `{source['schema']}`.`{source['table']}`
            where Action in (0, 1) and Time >= %s and Time < %s
            group by Login
            having {having_sql}
        """
    else:
        sql = f"""
            select LOGIN as Login, count(*) as ClosedOrders, max(VOLUME / 100.0) as MaxLot,
                   sum(coalesce(PROFIT, 0) + coalesce(COMMISSION, 0) + coalesce(SWAPS, 0) + coalesce(TAXES, 0)) as PeriodNetRaw
            from `{source['schema']}`.`{source['table']}`
            where CMD in (0, 1) and CLOSE_TIME >= %s and CLOSE_TIME < %s
            group by LOGIN
            having {having_sql}
        """
    started = time.perf_counter()
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, parameters)
            rows = cur.fetchall()
            logins = [app.mysql_int(row.get("Login")) for row in rows if app.mysql_int(row.get("Login")) > 0]
            routed_logins = _source_routed_logins(source, cur, logins)
            rows = [row for row in rows if app.mysql_int(row.get("Login")) in routed_logins]
            logins = sorted(routed_logins)
            profiles = _candidate_profiles(source, cur, logins, filters, end)
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
        "currency": profiles.get(app.mysql_int(row.get("Login")), {}).get("Currency", ""),
        "databaseStatus": app.normalize_text(profiles.get(app.mysql_int(row.get("Login")), {}).get("Status")),
        "registration": profiles.get(app.mysql_int(row.get("Login")), {}).get("RegistrationText", ""),
        "registrationDays": app.mysql_int(profiles.get(app.mysql_int(row.get("Login")), {}).get("RegistrationDays")),
        "activeDays": app.mysql_int(profiles.get(app.mysql_int(row.get("Login")), {}).get("ActiveDays")),
        "activeRatio": profiles.get(app.mysql_int(row.get("Login")), {}).get("ActiveRatio"),
        "totalNet": app.rounded(profiles.get(app.mysql_int(row.get("Login")), {}).get("TotalNet")),
        "depositTotal": app.rounded(profiles.get(app.mysql_int(row.get("Login")), {}).get("DepositTotal")),
        "lifetimeDataAvailable": bool(profiles.get(app.mysql_int(row.get("Login")), {}).get("LifetimeDataAvailable")),
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


def load_mt4_candidate_rows(source: dict, candidates: list[dict], start: datetime, end: datetime) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    logins = [int(item["login"]) for item in candidates]
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            for offset in range(0, len(logins), 250):
                batch = logins[offset:offset + 250]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(
                    f"select {MT4_COLUMNS} from `{source['schema']}`.`{source['table']}` where LOGIN in ({placeholders}) and CMD in (0,1) and CLOSE_TIME >= %s and CLOSE_TIME < %s order by LOGIN, OPEN_TIME, TICKET",
                    [*batch, start, end],
                )
                for raw in cur.fetchall():
                    row = mt4_row(source, raw)
                    grouped[row["account"]].append(row)
    return grouped


def load_mt5_candidate_rows(source: dict, candidates: list[dict], start: datetime, end: datetime) -> dict[str, list[dict]]:
    candidate_logins = [int(item["login"]) for item in candidates]
    deals_by_login: dict[str, list[dict]] = defaultdict(list)
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            for offset in range(0, len(candidate_logins), 100):
                batch = candidate_logins[offset:offset + 100]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(
                    f"select Login, PositionID from `{source['schema']}`.`{source['table']}` where Login in ({placeholders}) and Action in (0,1) and Entry in (1,2,3) and Time >= %s and Time < %s and PositionID <> 0 group by Login, PositionID",
                    [*batch, start, end],
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


def deep_candidate(candidate: dict, source: dict) -> dict:
    started = time.perf_counter()
    rows = load_deep_rows(source, candidate["login"])
    if not rows:
        raise RuntimeError("账号全历史没有可检测订单")
    push_context = app.toxic_build_push_context(rows)
    core_rows = push_context["rows"]
    metrics = app.trade_metrics(core_rows)
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
        sync = app.toxic_cross_account_sync(candidate["login"], core_rows)
    finally:
        app.toxic_sync_candidates_for_source = original_loader
    tick = app.toxic_winning_ticks(candidate["login"], core_rows)
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
        "tickAvailable": bool(tick.get("available")),
        "tickAnalyzedOrders": app.mysql_int(tick.get("analyzedOrders")),
        "coordinatedMatchedRatio": app.numeric_value(sync.get("coordinatedMatchedRatio")),
        "coordinatedCloseRatio": app.numeric_value(sync.get("coordinatedCloseRatio")),
        "recurringPeerAccounts": app.mysql_int(sync.get("recurringPeerAccounts")),
        "suspectedAccomplices": (result.get("suspectedAccomplices") or [])[:10],
        "deepElapsedSeconds": round(time.perf_counter() - started, 2),
    }


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
    aggregate_retries: list[tuple[dict, Exception]] = []
    with ThreadPoolExecutor(max_workers=min(args.workers, len(sources))) as executor:
        futures = {executor.submit(source_candidates, source, start, end, filters): source for source in sources}
        for index, future in enumerate(as_completed(futures), start=1):
            source = futures[future]
            try:
                candidates.extend(future.result())
            except Exception as exc:
                if transient_mysql_failure(exc):
                    aggregate_retries.append((source, exc))
                else:
                    failures.append({"stage": "aggregate", "source": source["name"], "error": str(exc)})
            emit("aggregate", f"收益候选聚合 {index}/{len(sources)} 个服务器", 5 + round(index / len(sources) * 12))
    for retry_index, (source, initial_exc) in enumerate(aggregate_retries, start=1):
        emit(
            "aggregate",
            f"聚合查询超时，低并发重试 {retry_index}/{len(aggregate_retries)}：{source['name']}",
            17,
        )
        retry_source = {**source, "read_timeout": max(app.mysql_int(source.get("read_timeout"), 90), 240)}
        try:
            candidates.extend(source_candidates(retry_source, start, end, filters))
        except Exception as exc:
            failures.append({
                "stage": "aggregate",
                "source": source["name"],
                "attempts": 2,
                "initialError": str(initial_exc),
                "error": str(exc),
            })
    before_exclusion = len(candidates)
    excluded_candidates: list[dict] = []
    excluded_by_reason: dict[str, int] = defaultdict(int)
    retained: list[dict] = []
    for candidate in candidates:
        reasons = candidate_filter_reasons(candidate, filters)
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
        f"窗口候选{before_exclusion}个，限制后保留{len(candidates)}个（{reason_text}），开始结构初筛",
        20,
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
            executor.submit(load_candidate_rows, source_map[source_name], source_candidates_rows, start, end): source_name
            for source_name, source_candidates_rows in by_source.items()
        }
        for index, future in enumerate(as_completed(futures), start=1):
            source_name = futures[future]
            try:
                rows_by_source[source_name] = future.result()
            except Exception as exc:
                rows_by_source[source_name] = {}
                failures.append({"stage": "load_rows", "source": source_name, "error": str(exc)})
            emit("screen", f"批量订单读取 {index}/{len(by_source)} 个服务器", 20 + round(index / len(by_source) * 25))

    screened = []
    for index, candidate in enumerate(candidates, start=1):
        rows = rows_by_source.get(candidate["source"], {}).get(candidate["login"], [])
        try:
            screened.append(screen_candidate(candidate, rows, args.small_order_priority))
        except Exception as exc:
            failures.append({"stage": "screen", **candidate, "error": str(exc)})
        if index % 250 == 0 or index == len(candidates):
            emit("screen", f"结构初筛 {index}/{len(candidates)}", 45 + round(index / max(len(candidates), 1) * 15))
    screened.sort(key=lambda row: (-app.numeric_value(row.get("routePriority")), row["server"], app.mysql_int(row["login"])))
    for rank, row in enumerate(screened, start=1):
        row["screenRank"] = rank
    eligible = [row for row in screened if row.get("deepEligible")]
    selected = eligible[: args.deep_limit]
    write_json(output_dir / "screened.json", screened)
    write_json(output_dir / "deep_candidates.json", selected)
    emit(
        "deep",
        f"初筛完成：{len(eligible)}个进入深检队列，本轮深检前{len(selected)}个",
        62,
        screened=len(screened),
        eligible=len(eligible),
        selected=len(selected),
    )

    app.toxic_cached_tick_mapping = lambda login, report_symbol: None
    deep_results: list[dict] = []
    for index, candidate in enumerate(selected, start=1):
        try:
            result = deep_candidate(candidate, source_map[candidate["source"]])
            deep_results.append(result)
            write_json(output_dir / "deep_results_checkpoint.json", deep_results)
            message = f"深检 {index}/{len(selected)}：{result['server']}/{result['login']} {result['initialScore']}→{result['deepScore']}"
        except Exception as exc:
            failures.append({"stage": "deep", **candidate, "error": str(exc)})
            message = f"深检 {index}/{len(selected)} 失败：{candidate['server']}/{candidate['login']}"
        emit("deep", message, 62 + round(index / max(len(selected), 1) * 34))
    deep_results.sort(key=lambda row: (-app.numeric_value(row.get("deepScore")), -app.numeric_value(row.get("routePriority"))))
    for rank, row in enumerate(deep_results, start=1):
        row["deepRank"] = rank
    write_json(output_dir / "deep_results.json", deep_results)
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
        "deepEligible": len(eligible),
        "deepSelected": len(selected),
        "deepCompleted": len(deep_results),
        "deepPending": max(len(eligible) - len(selected), 0),
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
