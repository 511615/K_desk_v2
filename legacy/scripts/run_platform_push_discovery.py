from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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
MT4_COLUMNS = """
    TICKET, LOGIN, CMD, SYMBOL, VOLUME, OPEN_TIME, OPEN_PRICE, CLOSE_TIME,
    CLOSE_PRICE, COMMISSION, TAXES, SWAPS, PROFIT, SL, TP, REASON, MAGIC, COMMENT
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover previously unmarked market-pushing accounts.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-orders", type=int, default=200)
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


def source_candidates(source: dict, start: datetime, end: datetime, max_orders: int) -> list[dict]:
    if source.get("kind") == "mt5_deals":
        sql = f"""
            select Login,
                   count(distinct case when Entry in (1, 2, 3) and PositionID <> 0 then PositionID end) as ClosedOrders,
                   sum(coalesce(Profit, 0) + coalesce(Commission, 0) + coalesce(Storage, 0) + coalesce(Fee, 0)) as PeriodNetRaw
            from `{source['schema']}`.`{source['table']}`
            where Action in (0, 1) and Time >= %s and Time < %s
            group by Login
            having ClosedOrders between 1 and %s and PeriodNetRaw > 0
        """
    else:
        sql = f"""
            select LOGIN as Login, count(*) as ClosedOrders,
                   sum(coalesce(PROFIT, 0) + coalesce(COMMISSION, 0) + coalesce(SWAPS, 0) + coalesce(TAXES, 0)) as PeriodNetRaw
            from `{source['schema']}`.`{source['table']}`
            where CMD in (0, 1) and CLOSE_TIME >= %s and CLOSE_TIME < %s
            group by LOGIN
            having ClosedOrders between 1 and %s and PeriodNetRaw > 0
        """
    started = time.perf_counter()
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (start, end, max_orders))
            rows = cur.fetchall()
    return [{
        "source": source["name"],
        "platform": source["platform"],
        "server": source["server"],
        "login": str(app.mysql_int(row.get("Login"))),
        "closedOrders": app.mysql_int(row.get("ClosedOrders")),
        "periodNetRaw": app.rounded(row.get("PeriodNetRaw")),
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


def load_exact_rows(source: dict, login: str, start: datetime, end: datetime) -> list[dict]:
    if source.get("kind") == "mt5_deals":
        return mt5_runner.load_recent_closed_trades(source, login, start, end)["rows"]
    rows = app.query_mysql_mt4_source(
        source,
        login,
        start=app.trade_time_text(start),
        end=app.trade_time_text(end),
        limit=50000,
    )
    return [row for row in rows if (closed := app.parse_trade_time(row.get("close_time"))) and start <= closed < end]


def deep_candidate(candidate: dict, source: dict, start: datetime, end: datetime) -> dict:
    started = time.perf_counter()
    rows = load_exact_rows(source, candidate["login"], start, end)
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
    return {
        **candidate,
        "deepScore": app.numeric_value(result.get("score")),
        "deepLevel": result.get("level"),
        "deepConfidence": app.mysql_int(result.get("confidence")),
        "headline": chain.get("headline") or result.get("summary"),
        "reasoning": chain.get("reasoning") or "",
        "triggeredRules": result.get("triggeredRules", []),
        "limitations": result.get("limitations", []),
        "tickAvailable": bool(tick.get("available")),
        "tickAnalyzedOrders": app.mysql_int(tick.get("analyzedOrders")),
        "coordinatedMatchedRatio": app.numeric_value(sync.get("coordinatedMatchedRatio")),
        "coordinatedCloseRatio": app.numeric_value(sync.get("coordinatedCloseRatio")),
        "recurringPeerAccounts": app.mysql_int(sync.get("recurringPeerAccounts")),
        "suspectedAccomplices": (result.get("suspectedAccomplices") or [])[:10],
        "deepElapsedSeconds": round(time.perf_counter() - started, 2),
    }


def main() -> int:
    args = parse_args()
    if not (1 <= args.days <= 30):
        raise ValueError("days must be between 1 and 30")
    if not (20 <= args.max_orders <= 1000):
        raise ValueError("max-orders must be between 20 and 1000")
    if not (1 <= args.deep_limit <= 300):
        raise ValueError("deep-limit must be between 1 and 300")
    if not (1 <= args.workers <= 8):
        raise ValueError("workers must be between 1 and 8")

    end = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    start = end - timedelta(days=args.days)
    run_id = f"push_discovery_{end:%Y%m%d_%H%M%S}_utc"
    output_dir = args.output_root.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    sources = list(app.MYSQL_SOURCES)
    source_map = {source["name"]: source for source in sources}
    known_excluded = excluded_logins(app.load_records())
    all_started = time.perf_counter()
    failures: list[dict] = []
    emit("aggregate", f"正在汇总{len(sources)}个服务器近{args.days}天盈利账户", 5)

    candidates: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(args.workers, len(sources))) as executor:
        futures = {executor.submit(source_candidates, source, start, end, args.max_orders): source for source in sources}
        for index, future in enumerate(as_completed(futures), start=1):
            source = futures[future]
            try:
                candidates.extend(future.result())
            except Exception as exc:
                failures.append({"stage": "aggregate", "source": source["name"], "error": str(exc)})
            emit("aggregate", f"收益候选聚合 {index}/{len(sources)} 个服务器", 5 + round(index / len(sources) * 12))
    before_exclusion = len(candidates)
    candidates = [row for row in candidates if row["login"] not in known_excluded]
    candidates.sort(key=lambda row: (row["source"], app.mysql_int(row["login"])))
    write_json(output_dir / "candidates.json", candidates)
    emit(
        "screen",
        f"候选{before_exclusion}个，排除已标记T/TA/A账号{before_exclusion - len(candidates)}个，开始批量初筛",
        20,
        candidates=len(candidates),
        excluded=before_exclusion - len(candidates),
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
            result = deep_candidate(candidate, source_map[candidate["source"]], start, end)
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
        "excludedActions": sorted(DEFAULT_EXCLUDED_ACTIONS),
        "sources": [source["name"] for source in sources],
        "aggregateCandidates": before_exclusion,
        "excludedKnownAccounts": before_exclusion - len(candidates),
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
