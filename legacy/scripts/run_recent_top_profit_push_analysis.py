from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "problem_account_registry"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app  # noqa: E402
import run_ac_mt5_push_validation as mt5_runner  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze recent top-profit accounts for market-pushing risk.")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--source-top", type=int, default=300)
    parser.add_argument("--strict-min-score", type=float, default=40.0)
    parser.add_argument("--strict-min-count", type=int, default=20)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs")
    parser.add_argument("--prefilter-json", type=Path)
    return parser.parse_args()


def print_progress(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def json_dump(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")


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


def latest_money_meta(cur, source: dict, logins: list[int]) -> dict[int, dict]:
    if not logins:
        return {}
    placeholders = ",".join(["%s"] * len(logins))
    metadata: dict[int, dict] = {}
    try:
        if source.get("kind") == "mt5_deals":
            sql = f"""
                select daily.Login, daily.Currency, daily.`Group` as AccountGroup
                from `{source['schema']}`.`mt5_daily_view` daily
                inner join (
                    select Login, max(Datetime) as LatestDatetime
                    from `{source['schema']}`.`mt5_daily_view`
                    where Login in ({placeholders})
                    group by Login
                ) latest on latest.Login = daily.Login and latest.LatestDatetime = daily.Datetime
            """
        else:
            sql = f"""
                select LOGIN as Login, CURRENCY as Currency, `GROUP` as AccountGroup
                from `{source['schema']}`.`mt4_users_view`
                where LOGIN in ({placeholders})
            """
        cur.execute(sql, logins)
        for row in cur.fetchall():
            login = app.mysql_int(row.get("Login"))
            metadata[login] = app.account_money_meta(
                row.get("Currency"), row.get("AccountGroup"), source.get("name")
            )
    except Exception as exc:
        print_progress(f"{source['name']} 账户币种读取失败，按原币值排序：{exc}")
    return metadata


def source_top_profit(source: dict, start: datetime, end: datetime, source_top: int) -> list[dict]:
    if source.get("kind") == "mt5_deals":
        sql = f"""
            select Login,
                   count(distinct case when Entry in (1, 2, 3) and PositionID <> 0 then PositionID end) as ClosedPositions,
                   sum(coalesce(Profit, 0) + coalesce(Commission, 0) + coalesce(Storage, 0) + coalesce(Fee, 0)) as PeriodNetRaw
            from `{source['schema']}`.`{source['table']}`
            where Action in (0, 1) and Time >= %s and Time < %s
            group by Login
            having ClosedPositions > 0
            order by PeriodNetRaw desc
            limit %s
        """
    else:
        sql = f"""
            select LOGIN as Login, count(*) as ClosedPositions,
                   sum(coalesce(PROFIT, 0) + coalesce(COMMISSION, 0) + coalesce(SWAPS, 0) + coalesce(TAXES, 0)) as PeriodNetRaw
            from `{source['schema']}`.`{source['table']}`
            where CMD in (0, 1) and CLOSE_TIME >= %s and CLOSE_TIME < %s
            group by LOGIN
            order by PeriodNetRaw desc
            limit %s
        """
    started = time.perf_counter()
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (start, end, source_top))
            aggregate_rows = cur.fetchall()
            logins = [app.mysql_int(row.get("Login")) for row in aggregate_rows if app.mysql_int(row.get("Login")) > 0]
            money_meta = latest_money_meta(cur, source, logins)
    out = []
    for row in aggregate_rows:
        login = app.mysql_int(row.get("Login"))
        if login <= 0:
            continue
        meta = money_meta.get(login) or app.account_money_meta(source_name=source.get("name"))
        money_scale = app.numeric_value(meta.get("moneyScale")) or 1.0
        out.append({
            "platform": source.get("platform"),
            "server": source.get("server"),
            "source": source.get("name"),
            "login": str(login),
            "currency": meta.get("displayCurrency") or meta.get("currency") or "",
            "isCentAccount": bool(meta.get("isCentAccount")),
            "moneyScale": money_scale,
            "periodNetRaw": app.rounded(row.get("PeriodNetRaw")),
            "periodNet": app.rounded(app.numeric_value(row.get("PeriodNetRaw")) * money_scale),
            "prefilterClosedOrders": app.mysql_int(row.get("ClosedPositions")),
        })
    print_progress(f"{source['name']} 收益聚合完成：{len(out)} 个候选，耗时 {time.perf_counter() - started:.1f}s")
    return out


def load_recent_rows(source: dict, login: str, start: datetime, end: datetime) -> list[dict]:
    if source.get("kind") == "mt5_deals":
        return mt5_runner.load_recent_closed_trades(source, login, start, end)["rows"]
    rows = app.query_mysql_mt4_source(
        source,
        login,
        start=app.trade_time_text(start),
        end=app.trade_time_text(end),
        limit=50000,
    )
    return [
        row for row in rows
        if (closed := app.parse_trade_time(row.get("close_time"))) and start <= closed < end
    ]


def initial_screen(candidate: dict, source: dict, start: datetime, end: datetime) -> dict:
    rows = load_recent_rows(source, candidate["login"], start, end)
    if not rows:
        return {**candidate, "screenStatus": "no_rows", "initialScore": 0.0, "exactOrders": 0}
    push_context = app.toxic_build_push_context(rows)
    push_rows = push_context["rows"]
    finance = {"available": False, "reason": "批量初筛不读取资金快照"}
    result = app.calculate_toxic_results(
        candidate["login"],
        push_rows,
        ["market_pushing"],
        "initial",
        finance,
        push_context=push_context,
    )[0]
    behavior = push_context["behavior"]
    exact_net = sum(app.toxic_trade_net(row) for row in rows)
    return {
        **candidate,
        "screenStatus": "ok",
        "exactOrders": len(rows),
        "analysisOrders": len(push_rows),
        "exactClosedNet": app.rounded(exact_net),
        "totalVolume": app.rounded(sum(app.numeric_value(row.get("volume")) for row in rows), 4),
        "firstTrade": min(app.normalize_text(row.get("open_time")) for row in rows),
        "lastTrade": max(app.normalize_text(row.get("close_time")) for row in rows),
        "initialScore": app.numeric_value(result.get("score")),
        "initialLevel": result.get("level"),
        "initialConfidence": app.mysql_int(result.get("confidence")),
        "initialSummary": result.get("summary"),
        "initialTriggers": result.get("triggeredRules", []),
        "initialLimitations": result.get("limitations", []),
        "initialAnalysis": result.get("analysis", []),
        "concentratedCoreVolumeRatio": app.numeric_value(behavior.get("concentratedCoreVolumeRatio")),
        "coreShortHoldVolumeRatio": app.numeric_value(behavior.get("coreShortHoldVolumeRatio")),
        "quietGapRatio": app.numeric_value(behavior.get("quietGapRatio")),
        "eaVolumeRatio": app.numeric_value(behavior.get("eaVolumeRatio")),
        "copyVolumeRatio": app.numeric_value(behavior.get("copyVolumeRatio")),
    }


def strict_screen(screened: dict, source: dict, start: datetime, end: datetime) -> dict:
    started = time.perf_counter()
    rows = load_recent_rows(source, screened["login"], start, end)
    push_context = app.toxic_build_push_context(rows)
    push_rows = push_context["rows"]
    metrics = app.trade_metrics(push_rows)
    finance = app.toxic_finance_summary(screened["login"], push_rows, metrics)
    original_loader = app.toxic_sync_candidates_for_source

    def source_aware_loader(
        candidate_source: dict,
        excluded_login: str,
        target_seconds: set[str],
        target_symbols: set[str] | None = None,
        target_directions: set[str] | None = None,
    ) -> list[dict]:
        effective_exclusion = excluded_login if candidate_source.get("server") == source.get("server") else "0"
        return original_loader(
            candidate_source,
            effective_exclusion,
            target_seconds,
            target_symbols,
            target_directions,
        )

    app.toxic_sync_candidates_for_source = source_aware_loader
    try:
        sync = app.toxic_cross_account_sync(screened["login"], push_rows)
    finally:
        app.toxic_sync_candidates_for_source = original_loader
    tick = app.toxic_winning_ticks(screened["login"], push_rows)
    result = app.calculate_toxic_results(
        screened["login"],
        push_rows,
        ["market_pushing"],
        "deep",
        finance,
        tick,
        sync,
        push_context=push_context,
    )[0]
    chain = result.get("evidenceChain") or {}
    return {
        **screened,
        "strictStatus": "ok",
        "strictScore": app.numeric_value(result.get("score")),
        "strictLevel": result.get("level"),
        "strictConfidence": app.mysql_int(result.get("confidence")),
        "strictHeadline": chain.get("headline"),
        "strictReasoning": chain.get("reasoning"),
        "strictTriggers": result.get("triggeredRules", []),
        "strictLimitations": result.get("limitations", []),
        "strictEvidenceOrders": result.get("evidenceOrders", []),
        "strictAnalysis": result.get("analysis", []),
        "suspectedAccomplices": result.get("suspectedAccomplices", []),
        "tickAvailable": bool(tick.get("available")),
        "tickAnalyzedOrders": app.mysql_int(tick.get("analyzedOrders")),
        "tickCoverageRatio": app.numeric_value(tick.get("accountCoverageRatio", tick.get("coverageRatio"))),
        "eventAcceleration10VolumeRatio": app.numeric_value(tick.get("eventAcceleration10VolumeRatio")),
        "eventPersistence60VolumeRatio": app.numeric_value(tick.get("eventPersistence60VolumeRatio")),
        "preexistingTrendVolumeRatio": app.numeric_value(tick.get("preexistingTrendVolumeRatio")),
        "syncAvailable": bool(sync.get("available")),
        "coordinatedMatchedRatio": app.numeric_value(sync.get("coordinatedMatchedRatio")),
        "coordinatedCloseRatio": app.numeric_value(sync.get("coordinatedCloseRatio")),
        "recurringPeerAccounts": app.mysql_int(sync.get("recurringPeerAccounts")),
        "strictElapsedSeconds": round(time.perf_counter() - started, 2),
        "tick": tick,
        "sync": sync,
        "finance": finance,
        "evidenceChain": chain,
    }


def main() -> int:
    args = parse_args()
    if min(args.days, args.top, args.source_top, args.strict_min_count, args.workers) <= 0:
        raise ValueError("days, top, source-top, strict-min-count and workers must be positive")
    prefilter_path = args.prefilter_json.resolve() if args.prefilter_json else None
    if prefilter_path:
        source_config = json.loads((prefilter_path.parent / "run_config.json").read_text(encoding="utf-8"))
        start = datetime.fromisoformat(source_config["windowStartUtc"])
        end = datetime.fromisoformat(source_config["windowEndUtc"])
        run_id = f"top_profit_push_corrected_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_utc"
    else:
        end = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        start = end - timedelta(days=args.days)
        run_id = f"top_profit_push_{end:%Y%m%d_%H%M%S}_utc"
    output_dir = args.output_root.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    sources = list(app.MYSQL_SOURCES)
    source_map = {source["name"]: source for source in sources}
    config = {
        "runId": run_id,
        "windowStartUtc": start.isoformat(sep=" "),
        "windowEndUtc": end.isoformat(sep=" "),
        "days": args.days,
        "topAccounts": args.top,
        "sourcePrefilterLimit": args.source_top,
        "strictMinInitialScore": args.strict_min_score,
        "strictMinimumCount": args.strict_min_count,
        "sources": [source["name"] for source in sources],
        "profitDefinition": "MT5 period deals or MT4 closed trades: Profit + Commission + Storage/Swaps + Fee/Taxes, cent accounts scaled to USD",
        "accountIdentity": "platform + server + login",
        "screening": "market-pushing structure only, no Tick and no cross-account evidence",
        "strict": "filtered core orders + finance + cross-account synchronization + Tick when configured",
        "prefilterSource": str(prefilter_path) if prefilter_path else "live database aggregation",
    }
    json_dump(output_dir / "run_config.json", config)
    print_progress(f"任务启动：{run_id}；窗口 {start} 至 {end} UTC；服务器 {len(sources)} 个")
    all_started = time.perf_counter()

    prefiltered: list[dict] = []
    failures_path = output_dir / "failures.jsonl"
    if prefilter_path:
        prefiltered = json.loads(prefilter_path.read_text(encoding="utf-8"))
        print_progress(f"已载入校正后的收益候选：{len(prefiltered)} 个")
    else:
        with ThreadPoolExecutor(max_workers=min(args.workers, len(sources))) as executor:
            futures = {
                executor.submit(source_top_profit, source, start, end, args.source_top): source
                for source in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    prefiltered.extend(future.result())
                except Exception as exc:
                    append_jsonl(failures_path, {"stage": "profit_aggregate", "source": source["name"], "error": str(exc)})
                    print_progress(f"{source['name']} 收益聚合失败：{exc}")
    prefiltered.sort(key=lambda row: (-app.numeric_value(row.get("periodNet")), row["server"], app.mysql_int(row["login"])))
    json_dump(output_dir / "profit_prefilter_all.json", prefiltered)
    top_accounts = prefiltered[: args.top]
    for rank, row in enumerate(top_accounts, start=1):
        row["profitRank"] = rank
    json_dump(output_dir / "top100_profit.json", top_accounts)
    print_progress(f"收益排名完成：跨服候选 {len(prefiltered)} 个，进入初筛 {len(top_accounts)} 个")

    screening_checkpoint = output_dir / "screening_checkpoint.jsonl"
    screened: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(initial_screen, candidate, source_map[candidate["source"]], start, end): candidate
            for candidate in top_accounts
        }
        for index, future in enumerate(as_completed(futures), start=1):
            candidate = futures[future]
            try:
                result = future.result()
                screened.append(result)
                append_jsonl(screening_checkpoint, result)
            except Exception as exc:
                append_jsonl(failures_path, {"stage": "initial_screen", **candidate, "error": str(exc)})
            if index % 10 == 0 or index == len(futures):
                print_progress(f"初筛进度 {index}/{len(futures)}")
    screened.sort(key=lambda row: app.mysql_int(row.get("profitRank")))
    json_dump(output_dir / "top100_screened.json", screened)
    write_csv(
        output_dir / "top100_screened.csv",
        screened,
        [
            "profitRank", "platform", "server", "login", "currency", "periodNet", "periodNetRaw",
            "prefilterClosedOrders", "exactOrders", "analysisOrders", "exactClosedNet", "totalVolume",
            "firstTrade", "lastTrade", "initialScore", "initialLevel", "initialConfidence",
            "concentratedCoreVolumeRatio", "coreShortHoldVolumeRatio", "quietGapRatio", "eaVolumeRatio",
            "copyVolumeRatio", "initialSummary", "initialTriggers", "initialLimitations",
        ],
    )

    ranked_for_strict = sorted(
        [row for row in screened if row.get("screenStatus") == "ok"],
        key=lambda row: (-app.numeric_value(row.get("initialScore")), app.mysql_int(row.get("profitRank"))),
    )
    strict_candidates = [row for row in ranked_for_strict if app.numeric_value(row.get("initialScore")) >= args.strict_min_score]
    if len(strict_candidates) < min(args.strict_min_count, len(ranked_for_strict)):
        strict_candidates = ranked_for_strict[: min(args.strict_min_count, len(ranked_for_strict))]
    strict_keys = {(row["source"], row["login"]) for row in strict_candidates}
    for row in screened:
        row["enteredStrict"] = (row["source"], row["login"]) in strict_keys
    json_dump(output_dir / "strict_candidates.json", strict_candidates)
    print_progress(
        f"初筛完成：分数≥{args.strict_min_score:g} 的账户 {sum(app.numeric_value(row.get('initialScore')) >= args.strict_min_score for row in ranked_for_strict)} 个；"
        f"进入严格检测 {len(strict_candidates)} 个"
    )

    strict_checkpoint = output_dir / "strict_checkpoint.jsonl"
    strict_results: list[dict] = []
    app.toxic_cached_tick_mapping = lambda login, report_symbol: None
    for index, candidate in enumerate(strict_candidates, start=1):
        try:
            result = strict_screen(candidate, source_map[candidate["source"]], start, end)
            strict_results.append(result)
            append_jsonl(strict_checkpoint, result)
            print_progress(
                f"严格检测 {index}/{len(strict_candidates)}：{result['server']}/{result['login']} "
                f"{result['initialScore']} -> {result['strictScore']}，Tick={'有' if result['tickAvailable'] else '无'}，"
                f"耗时 {result['strictElapsedSeconds']}s"
            )
        except Exception as exc:
            append_jsonl(failures_path, {"stage": "strict_screen", **candidate, "error": str(exc)})
            print_progress(f"严格检测 {index}/{len(strict_candidates)} 失败：{candidate['server']}/{candidate['login']}：{exc}")
    strict_results.sort(
        key=lambda row: (-app.numeric_value(row.get("strictScore")), app.mysql_int(row.get("profitRank")))
    )
    for rank, row in enumerate(strict_results, start=1):
        row["strictRank"] = rank
    json_dump(output_dir / "strict_results_full.json", strict_results)
    write_csv(
        output_dir / "strict_results.csv",
        strict_results,
        [
            "strictRank", "profitRank", "platform", "server", "login", "currency", "periodNet",
            "exactOrders", "analysisOrders", "totalVolume", "initialScore", "initialLevel", "strictScore",
            "strictLevel", "strictConfidence", "strictHeadline", "strictReasoning", "tickAvailable",
            "tickAnalyzedOrders", "tickCoverageRatio", "eventAcceleration10VolumeRatio",
            "eventPersistence60VolumeRatio", "preexistingTrendVolumeRatio", "syncAvailable",
            "coordinatedMatchedRatio", "coordinatedCloseRatio", "recurringPeerAccounts",
            "strictElapsedSeconds", "strictTriggers", "suspectedAccomplices", "strictEvidenceOrders",
            "strictLimitations",
        ],
    )

    summary = {
        **config,
        "completedAt": datetime.now().isoformat(timespec="seconds"),
        "profitCandidates": len(prefiltered),
        "topAccountsScreened": len(screened),
        "initialScore40Plus": sum(app.numeric_value(row.get("initialScore")) >= 40 for row in screened),
        "initialScore60Plus": sum(app.numeric_value(row.get("initialScore")) >= 60 for row in screened),
        "strictRequested": len(strict_candidates),
        "strictCompleted": len(strict_results),
        "strictScore40Plus": sum(app.numeric_value(row.get("strictScore")) >= 40 for row in strict_results),
        "strictScore60Plus": sum(app.numeric_value(row.get("strictScore")) >= 60 for row in strict_results),
        "strictScore75Plus": sum(app.numeric_value(row.get("strictScore")) >= 75 for row in strict_results),
        "strictScore90Plus": sum(app.numeric_value(row.get("strictScore")) >= 90 for row in strict_results),
        "tickAvailable": sum(bool(row.get("tickAvailable")) for row in strict_results),
        "elapsedSeconds": round(time.perf_counter() - all_started, 1),
        "outputDir": str(output_dir),
    }
    json_dump(output_dir / "summary.json", summary)
    print_progress(f"任务完成：{json.dumps(summary, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
