from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "problem_account_registry"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app  # noqa: E402


AC_MT5_SOURCE_NAMES = {"AC GB MT5", "AC CN MT5"}
DEAL_COLUMNS = """
    Deal, Login, `Order`, PositionID, Action, Entry, Reason, Time, TimeMsc,
    Symbol, Price, Volume, VolumeExt, VolumeClosed, VolumeClosedExt,
    Profit, Commission, Storage, Fee, Comment, ExpertID, PriceSL, PriceTP,
    ContractSize, TickValue, TickSize, MarketBid, MarketAsk, PriceGateway
"""
OUTPUT_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AC MT5 push-detection validation.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-orders", type=int, default=100)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs")
    return parser.parse_args()


def json_dump(path: Path, value) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def append_jsonl(path: Path, value: dict) -> None:
    with OUTPUT_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")


def print_progress(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def source_candidates(source: dict, start: datetime, end: datetime, max_orders: int) -> list[dict]:
    sql = f"""
        select Login,
               count(*) as RawDealCount,
               count(distinct case when Entry in (1, 2, 3) and PositionID <> 0 then PositionID end) as ClosedPositions,
               sum(coalesce(Profit, 0) + coalesce(Commission, 0) + coalesce(Storage, 0) + coalesce(Fee, 0)) as PeriodNet
        from `{source['schema']}`.`{source['table']}`
        force index (idx_mt5_deals_Time)
        where Action in (0, 1) and Time >= %s and Time < %s
        group by Login
        having ClosedPositions between 1 and %s and PeriodNet > 0
    """
    started = time.perf_counter()
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (start, end, max_orders))
            rows = cur.fetchall()
    print_progress(f"{source['name']} 候选聚合完成：{len(rows)} 个，耗时 {time.perf_counter() - started:.1f}s")
    return [
        {
            "source": source["name"],
            "server": source["server"],
            "login": str(app.mysql_int(row.get("Login"))),
            "rawDealCount": app.mysql_int(row.get("RawDealCount")),
            "prefilterPositions": app.mysql_int(row.get("ClosedPositions")),
            "periodNetRaw": app.numeric_value(row.get("PeriodNet")),
        }
        for row in rows
        if app.mysql_int(row.get("Login")) > 0
    ]


def deal_volume(deal: dict, close: bool = False) -> float:
    value = deal.get("VolumeClosed") if close else deal.get("Volume")
    if not value:
        value = deal.get("Volume") or deal.get("VolumeExt")
    return max(app.normalize_mt5_volume(value), 0.0)


def weighted_price(deals: list[dict], close: bool = False) -> float:
    weighted = [(app.numeric_value(deal.get("Price")), deal_volume(deal, close=close)) for deal in deals]
    total = sum(volume for _, volume in weighted)
    return sum(price * volume for price, volume in weighted) / total if total else 0.0


def corrected_mt5_positions(deals: list[dict], source: dict, login: str, account_meta: dict) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for deal in deals:
        position_id = app.normalize_text(deal.get("PositionID"))
        if position_id and position_id != "0":
            grouped.setdefault(position_id, []).append(deal)
    money_scale = app.numeric_value(account_meta.get("moneyScale")) or 1.0
    rows: list[dict] = []
    for position_id, items in grouped.items():
        items.sort(key=lambda row: (app.mysql_datetime_text(row.get("TimeMsc") or row.get("Time")), app.mysql_int(row.get("Deal"))))
        opens = [row for row in items if app.mysql_int(row.get("Entry"), -1) == 0 and app.mysql_int(row.get("Action"), -1) in (0, 1)]
        closes = [row for row in items if app.mysql_int(row.get("Entry"), -1) in (1, 2, 3) and app.mysql_int(row.get("Action"), -1) in (0, 1)]
        if not opens or not closes:
            continue
        first_open = opens[0]
        last_close = closes[-1]
        open_time = app.mysql_datetime_text(first_open.get("Time"))
        close_time = app.mysql_datetime_text(last_close.get("Time"))
        open_time_msc = app.mysql_datetime_text(first_open.get("TimeMsc") or first_open.get("Time"))
        close_time_msc = app.mysql_datetime_text(last_close.get("TimeMsc") or last_close.get("Time"))
        open_dt = app.parse_trade_time(open_time_msc)
        close_dt = app.parse_trade_time(close_time_msc)
        total_open_volume = sum(deal_volume(row) for row in opens)
        total_close_volume = sum(deal_volume(row, close=True) for row in closes)
        action = app.mysql_int(first_open.get("Action"))
        comments = [app.normalize_text(row.get("Comment")) for row in items if app.normalize_text(row.get("Comment"))]
        reason_value = first_open.get("Reason") if first_open.get("Reason") is not None else last_close.get("Reason")
        rows.append({
            "id": app.normalize_text(last_close.get("Deal") or position_id),
            "source_id": app.normalize_text(source.get("name")),
            "data_source": "mysql",
            "platform": "MT5",
            "server": source.get("server", source.get("name", "")),
            "account": login,
            "account_currency": account_meta.get("currency", ""),
            "display_currency": account_meta.get("displayCurrency", ""),
            "money_scale": money_scale,
            "is_cent_account": bool(account_meta.get("isCentAccount")),
            "currency_source": "mt5_daily_view" if account_meta.get("currency") else "",
            "ticket": position_id,
            "open_time": open_time,
            "close_time": close_time,
            "open_time_msc": open_time_msc,
            "close_time_msc": close_time_msc,
            "type": "buy" if action == 0 else "sell",
            "volume": min(total_open_volume, total_close_volume) or total_close_volume or total_open_volume,
            "symbol": app.normalize_text(last_close.get("Symbol") or first_open.get("Symbol")),
            "open_price": weighted_price(opens),
            "close_price": weighted_price(closes, close=True),
            "commission": sum(app.numeric_value(row.get("Commission")) for row in items) * money_scale,
            "fee": sum(app.numeric_value(row.get("Fee")) for row in items) * money_scale,
            "taxes": 0,
            "swap": sum(app.numeric_value(row.get("Storage")) for row in items) * money_scale,
            "profit": sum(app.numeric_value(row.get("Profit")) for row in items) * money_scale,
            "sl": first_open.get("PriceSL") or "",
            "tp": first_open.get("PriceTP") or "",
            "reason": app.trade_reason_label("MT5", reason_value),
            "reason_code": app.mysql_int(reason_value, -1),
            "comment": " / ".join(dict.fromkeys(comments)),
            "expert_id": app.normalize_text(first_open.get("ExpertID") or last_close.get("ExpertID")),
            "tick_value": app.numeric_value(first_open.get("TickValue") or last_close.get("TickValue")),
            "tick_size": app.numeric_value(first_open.get("TickSize") or last_close.get("TickSize")),
            "contract_size": app.numeric_value(first_open.get("ContractSize") or last_close.get("ContractSize")),
            "market_bid": app.numeric_value(first_open.get("MarketBid")),
            "market_ask": app.numeric_value(first_open.get("MarketAsk")),
            "price_gateway": app.numeric_value(first_open.get("PriceGateway")),
            "holding_seconds": (close_dt - open_dt).total_seconds() if open_dt and close_dt else "",
            "raw_deal_count": len(items),
            "open_deal_count": len(opens),
            "close_deal_count": len(closes),
        })
    return rows


def load_recent_closed_trades(source: dict, login: str, start: datetime, end: datetime) -> dict:
    position_sql = f"""
        select distinct PositionID
        from `{source['schema']}`.`{source['table']}`
        where Login = %s and Action in (0, 1) and Entry in (1, 2, 3) and Time >= %s and Time < %s
          and PositionID is not null and PositionID <> 0
    """
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            cur.execute(position_sql, (int(login), start, end))
            position_ids = [app.mysql_int(row.get("PositionID")) for row in cur.fetchall()]
            position_ids = [value for value in position_ids if value > 0]
            if not position_ids:
                return {"rows": [], "positionCount": 0, "accountMeta": app.account_money_meta(source_name=source.get("name"))}
            placeholders = ",".join(["%s"] * len(position_ids))
            deals_sql = f"""
                select {DEAL_COLUMNS}
                from `{source['schema']}`.`{source['table']}`
                where Login = %s and Action in (0, 1) and Entry in (0, 1, 2, 3)
                  and PositionID in ({placeholders})
                order by PositionID, Time, Deal
            """
            cur.execute(deals_sql, [int(login), *position_ids])
            deals = cur.fetchall()
            account_meta = app.query_mysql_mt5_account_meta(cur, source, login)
    rows = corrected_mt5_positions(deals, source, login, account_meta)
    rows = [
        row for row in rows
        if (closed := app.parse_trade_time(row.get("close_time_msc") or row.get("close_time")))
        and start <= closed < end
    ]
    return {
        "rows": rows,
        "positionCount": len(position_ids),
        "accountMeta": account_meta,
        "loadedDealCount": len(deals),
        "multiDealPositions": sum(1 for row in rows if app.mysql_int(row.get("raw_deal_count")) > 2),
    }


def behavior_strength(behavior: dict) -> float:
    return app.rounded(
        app.numeric_value(behavior.get("concentratedCoreVolumeRatio")) * 0.35
        + app.numeric_value(behavior.get("coreShortHoldVolumeRatio")) * 0.25
        + app.numeric_value(behavior.get("quietGapRatio")) * 0.2
        + app.numeric_value(behavior.get("coreVolumeRatio")) * 0.1
        + app.numeric_value(behavior.get("cohesiveBatchOrderRatio")) * 0.1,
        4,
    )


def screen_candidate(candidate: dict, source_map: dict[str, dict], start: datetime, end: datetime, max_orders: int) -> dict:
    source = source_map[candidate["source"]]
    login = candidate["login"]
    loaded = load_recent_closed_trades(source, login, start, end)
    rows = loaded["rows"]
    order_count = loaded["positionCount"]
    money_scale = app.numeric_value(loaded["accountMeta"].get("moneyScale")) or 1.0
    period_net = app.numeric_value(candidate.get("periodNetRaw")) * money_scale
    closed_position_net = sum(app.toxic_trade_net(row) for row in rows)
    if not (1 <= order_count <= max_orders) or period_net <= 0 or not rows:
        return {
            **candidate,
            "qualified": False,
            "exactOrders": order_count,
            "periodNet": app.rounded(period_net),
            "closedPositionNet": app.rounded(closed_position_net),
            "reason": "精确重建后不满足订单数或净收益条件",
        }
    metrics = app.trade_metrics(rows)
    behavior = app.toxic_push_behavior(rows)
    finance = {"available": False, "reason": "批量初筛不读取当前资金快照"}
    result = app.calculate_toxic_results(login, rows, ["market_pushing"], "initial", finance)[0]
    return {
        **candidate,
        "qualified": True,
        "exactOrders": order_count,
        "periodNet": app.rounded(period_net),
        "closedPositionNet": app.rounded(closed_position_net),
        "loadedDealCount": loaded.get("loadedDealCount"),
        "multiDealPositions": loaded.get("multiDealPositions"),
        "grossProfit": app.rounded(sum(app.numeric_value(row.get("profit")) for row in rows)),
        "totalVolume": app.rounded(sum(app.numeric_value(row.get("volume")) for row in rows), 4),
        "firstTrade": min(app.normalize_text(row.get("open_time")) for row in rows),
        "lastTrade": max(app.normalize_text(row.get("close_time")) for row in rows),
        "initialScore": app.numeric_value(result.get("score")),
        "initialLevel": result.get("level"),
        "initialSummary": result.get("summary"),
        "initialTriggers": result.get("triggeredRules", []),
        "initialLimitations": result.get("limitations", []),
        "behaviorStrength": behavior_strength(behavior),
        "coreOrders": app.mysql_int(behavior.get("coreOrders")),
        "concentratedSessions": app.mysql_int(behavior.get("concentratedSessions")),
        "concentratedCoreVolumeRatio": app.numeric_value(behavior.get("concentratedCoreVolumeRatio")),
        "coreShortHoldVolumeRatio": app.numeric_value(behavior.get("coreShortHoldVolumeRatio")),
        "quietGapRatio": app.numeric_value(behavior.get("quietGapRatio")),
        "staggeredAddOnOrderRatio": app.numeric_value(behavior.get("staggeredAddOnOrderRatio")),
        "cohesiveBatchOrderRatio": app.numeric_value(behavior.get("cohesiveBatchOrderRatio")),
        "lossRate": app.numeric_value(behavior.get("lossRate")),
        "winRate": app.numeric_value(metrics.get("winRate")),
    }


def screen_sort_key(row: dict) -> tuple:
    return (
        -app.numeric_value(row.get("initialScore")),
        -app.numeric_value(row.get("behaviorStrength")),
        -app.mysql_int(row.get("coreOrders")),
        -app.numeric_value(row.get("concentratedCoreVolumeRatio")),
        -app.numeric_value(row.get("periodNet")),
        app.normalize_text(row.get("server")),
        app.mysql_int(row.get("login")),
    )


def deep_candidate(screened: dict, source_map: dict[str, dict], start: datetime, end: datetime) -> dict:
    source = source_map[screened["source"]]
    login = screened["login"]
    rows = load_recent_closed_trades(source, login, start, end)["rows"]
    metrics = app.trade_metrics(rows)
    finance = app.toxic_finance_summary(login, rows, metrics)
    original_sync_loader = app.toxic_sync_candidates_for_source
    def source_aware_sync_loader(candidate_source: dict, excluded_login: str, target_seconds: set[str]) -> list[dict]:
        effective_exclusion = excluded_login if candidate_source.get("server") == source.get("server") else "0"
        return original_sync_loader(candidate_source, effective_exclusion, target_seconds)
    app.toxic_sync_candidates_for_source = source_aware_sync_loader
    try:
        sync = app.toxic_cross_account_sync(login, rows)
    finally:
        app.toxic_sync_candidates_for_source = original_sync_loader
    tick = app.toxic_winning_ticks(login, rows)
    result = app.calculate_toxic_results(login, rows, ["market_pushing"], "deep", finance, tick, sync)[0]
    return {
        **screened,
        "deepScore": app.numeric_value(result.get("score")),
        "deepLevel": result.get("level"),
        "deepConfidence": app.mysql_int(result.get("confidence")),
        "deepSummary": result.get("summary"),
        "deepTriggers": result.get("triggeredRules", []),
        "deepEvidenceOrders": result.get("evidenceOrders", []),
        "deepLimitations": result.get("limitations", []),
        "deepAnalysis": result.get("analysis", []),
        "deepMetrics": result.get("metrics", []),
        "tick": tick,
        "sync": sync,
        "finance": finance,
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            for key, value in list(flat.items()):
                if isinstance(value, (list, dict)):
                    flat[key] = json.dumps(value, ensure_ascii=False, default=str)
            writer.writerow(flat)


def top100_csv_row(row: dict) -> dict:
    tick = row.get("tick") or {}
    sync = row.get("sync") or {}
    sources = tick.get("sources") or []
    mappings = tick.get("mappings") or []
    return {
        **row,
        "tickAvailable": bool(tick.get("available")),
        "tickAnalyzedOrders": tick.get("analyzedOrders"),
        "tickCoverageRatio": tick.get("accountCoverageRatio", tick.get("coverageRatio")),
        "priceWinTickMedian": tick.get("priceWinTickMedian"),
        "win1OrderRatio": tick.get("win1OrderRatio"),
        "win3OrderRatio": tick.get("win3OrderRatio"),
        "tickRatePerMinuteMedian": tick.get("tickRatePerMinuteMedian"),
        "terminalServers": "/".join(sorted({app.normalize_text(item.get("terminalServer")) for item in sources if app.normalize_text(item.get("terminalServer"))})),
        "timeModes": "/".join(sorted({app.normalize_text(item.get("timeMode")) for item in mappings if app.normalize_text(item.get("timeMode"))})),
        "syncAvailable": bool(sync.get("available")),
        "coordinatedMatchedRatio": sync.get("coordinatedMatchedRatio", sync.get("matchedRatio")),
        "coordinatedCloseRatio": sync.get("coordinatedCloseRatio", sync.get("closeMatchedRatio")),
        "recurringPeerAccounts": sync.get("recurringPeerAccounts", sync.get("peerAccounts")),
        "maxPeerRatio": sync.get("maxPeerRatio"),
        "topPeers": sync.get("topPeers", []),
    }


def main() -> int:
    args = parse_args()
    if args.days <= 0 or args.max_orders <= 0 or args.top <= 0 or args.workers <= 0:
        raise ValueError("days, max-orders, top and workers must be positive")
    end = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    start = end - timedelta(days=args.days)
    run_id = f"ac_mt5_push_{end:%Y%m%d_%H%M%S}_utc"
    output_dir = args.output_root.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    sources = [source for source in app.MYSQL_SOURCES if source.get("name") in AC_MT5_SOURCE_NAMES]
    source_map = {source["name"]: source for source in sources}
    app.MYSQL_SOURCES = sources
    config = {
        "runId": run_id,
        "startedAt": datetime.now().isoformat(timespec="seconds"),
        "windowStartUtc": start.isoformat(sep=" "),
        "windowEndUtc": end.isoformat(sep=" "),
        "days": args.days,
        "maxOrders": args.max_orders,
        "topDeep": args.top,
        "workers": args.workers,
        "sources": sorted(source_map),
        "screenFinance": "disabled to avoid current-snapshot leakage",
        "deepSyncScope": "AC GB MT5 and AC CN MT5 only; same login on the other server remains eligible as a peer",
        "tickTimeMapping": "live calibration only; cached mappings disabled for cross-server batch safety",
        "batchCorrectedReconstruction": True,
        "orderDefinition": "distinct PositionID with Entry in (1,2,3) closed inside the UTC window",
        "profitDefinition": "raw MT5 deal Profit+Commission+Storage+Fee inside the UTC window, currency-scaled",
    }
    json_dump(output_dir / "run_config.json", config)
    print_progress(f"任务启动：{run_id}，窗口 {start} 至 {end} UTC")

    aggregate_started = time.perf_counter()
    candidates: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {executor.submit(source_candidates, source, start, end, args.max_orders): source for source in sources}
        for future in as_completed(futures):
            candidates.extend(future.result())
    candidates.sort(key=lambda row: (row["source"], int(row["login"])))
    json_dump(output_dir / "candidate_prefilter.json", candidates)
    print_progress(f"候选预筛完成：{len(candidates)} 个，累计 {time.perf_counter() - aggregate_started:.1f}s")

    screened_path = output_dir / "screening_checkpoint.jsonl"
    failures_path = output_dir / "failures.jsonl"
    screened: list[dict] = []
    screen_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(screen_candidate, candidate, source_map, start, end, args.max_orders): candidate
            for candidate in candidates
        }
        for index, future in enumerate(as_completed(futures), start=1):
            candidate = futures[future]
            try:
                result = future.result()
                append_jsonl(screened_path, result)
                if result.get("qualified"):
                    screened.append(result)
            except Exception as exc:
                append_jsonl(failures_path, {"stage": "screen", **candidate, "error": str(exc)})
            if index % 50 == 0 or index == len(futures):
                elapsed = time.perf_counter() - screen_started
                print_progress(f"初筛进度 {index}/{len(futures)}，合格盈利账户 {len(screened)}，阶段耗时 {elapsed:.1f}s")

    screened.sort(key=screen_sort_key)
    for rank, row in enumerate(screened, start=1):
        row["initialRank"] = rank
    json_dump(output_dir / "screening_ranked.json", screened)
    screening_fields = [
        "initialRank", "source", "server", "login", "exactOrders", "periodNet", "closedPositionNet",
        "rawDealCount", "loadedDealCount", "multiDealPositions", "grossProfit", "totalVolume",
        "firstTrade", "lastTrade", "initialScore", "initialLevel", "initialSummary", "behaviorStrength",
        "coreOrders", "concentratedSessions", "concentratedCoreVolumeRatio", "coreShortHoldVolumeRatio",
        "quietGapRatio", "staggeredAddOnOrderRatio", "cohesiveBatchOrderRatio", "lossRate", "winRate",
        "initialTriggers", "initialLimitations",
    ]
    write_csv(output_dir / "screening_ranked.csv", screened, screening_fields)
    top_screened = screened[: args.top]
    json_dump(output_dir / "top100_screening.json", top_screened)
    print_progress(f"初筛完成：精确合格 {len(screened)} 个，进入深检 {len(top_screened)} 个")

    app.toxic_cached_tick_mapping = lambda login, report_symbol: None
    deep_path = output_dir / "deep_checkpoint.jsonl"
    deep_results: list[dict] = []
    deep_started = time.perf_counter()
    for index, screened_row in enumerate(top_screened, start=1):
        try:
            result = deep_candidate(screened_row, source_map, start, end)
            deep_results.append(result)
            append_jsonl(deep_path, result)
            print_progress(
                f"深检 {index}/{len(top_screened)}：{result['server']}/{result['login']} "
                f"初筛 {result['initialScore']} -> 深检 {result['deepScore']}，"
                f"Tick={'有' if (result.get('tick') or {}).get('available') else '无'}"
            )
        except Exception as exc:
            append_jsonl(failures_path, {"stage": "deep", **screened_row, "error": str(exc)})
            print_progress(f"深检 {index}/{len(top_screened)} 失败：{screened_row['server']}/{screened_row['login']}：{exc}")

    deep_results.sort(key=lambda row: (
        -app.numeric_value(row.get("deepScore")),
        -app.numeric_value(row.get("initialScore")),
        -app.numeric_value(row.get("behaviorStrength")),
        app.normalize_text(row.get("server")),
        app.mysql_int(row.get("login")),
    ))
    for rank, row in enumerate(deep_results, start=1):
        row["deepRank"] = rank
    json_dump(output_dir / "top100_deep_full.json", deep_results)
    csv_rows = [top100_csv_row(row) for row in deep_results]
    deep_fields = [
        "deepRank", "initialRank", "source", "server", "login", "exactOrders", "periodNet",
        "closedPositionNet", "rawDealCount", "loadedDealCount", "multiDealPositions", "totalVolume",
        "initialScore", "deepScore", "deepLevel", "deepConfidence", "deepSummary", "deepTriggers",
        "behaviorStrength", "coreOrders", "concentratedSessions", "concentratedCoreVolumeRatio",
        "coreShortHoldVolumeRatio", "quietGapRatio", "staggeredAddOnOrderRatio", "cohesiveBatchOrderRatio",
        "tickAvailable", "tickAnalyzedOrders", "tickCoverageRatio", "priceWinTickMedian", "win1OrderRatio",
        "win3OrderRatio", "tickRatePerMinuteMedian", "terminalServers", "timeModes", "syncAvailable",
        "coordinatedMatchedRatio", "coordinatedCloseRatio", "recurringPeerAccounts", "maxPeerRatio", "topPeers",
        "deepEvidenceOrders", "deepLimitations",
    ]
    write_csv(output_dir / "top100_deep_ranked.csv", csv_rows, deep_fields)

    summary = {
        **config,
        "completedAt": datetime.now().isoformat(timespec="seconds"),
        "prefilterCandidates": len(candidates),
        "qualifiedProfitableAccounts": len(screened),
        "deepRequested": len(top_screened),
        "deepCompleted": len(deep_results),
        "tickAvailable": sum(1 for row in deep_results if (row.get("tick") or {}).get("available")),
        "syncAvailable": sum(1 for row in deep_results if (row.get("sync") or {}).get("available")),
        "deepScore60Plus": sum(1 for row in deep_results if app.numeric_value(row.get("deepScore")) >= 60),
        "deepScore75Plus": sum(1 for row in deep_results if app.numeric_value(row.get("deepScore")) >= 75),
        "deepScore90Plus": sum(1 for row in deep_results if app.numeric_value(row.get("deepScore")) >= 90),
        "elapsedSeconds": round(time.perf_counter() - aggregate_started, 1),
        "deepElapsedSeconds": round(time.perf_counter() - deep_started, 1),
        "outputDir": str(output_dir),
    }
    json_dump(output_dir / "summary.json", summary)
    print_progress(f"任务完成：{json.dumps(summary, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
