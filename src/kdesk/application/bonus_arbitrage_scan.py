from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from threading import Lock
from typing import Protocol

from kdesk.application.bonus_arbitrage import BonusArbitrageService
from kdesk.domain.bonus_arbitrage import BonusAnalysisCancelled, number, parse_datetime

ENVIRONMENT_LABELS = {
    "ac_gb": "AC GB",
    "ac_cn": "AC CN",
    "dbg_cn": "DBG CN",
    "dbg_vn": "DBG VN",
}
ALLOWED_ENVIRONMENTS = tuple(ENVIRONMENT_LABELS)
HANDLED_DATABASE_STATUSES = {"T", "TA", "A", "A/TA"}
CANDIDATE_WORKERS = 4
DEEP_WORKERS = 3


class BonusScanRepository(Protocol):
    def scan_units(self, environments: list[str]) -> list[dict]: ...
    def discover_candidates(self, unit_id: str, start: datetime, end: datetime) -> list[dict]: ...
    def load_account_context(self, login: str, filters: dict) -> dict: ...


Progress = Callable[[int, str], None]
Cancelled = Callable[[], bool]


class BonusScanCancelled(RuntimeError):
    pass


def normalize_bonus_scan_options(payload: dict, *, now: datetime | None = None) -> dict:
    now = (now or datetime.now()).replace(microsecond=0)
    start = parse_datetime(payload.get("start")) or now - timedelta(days=30)
    end = parse_datetime(payload.get("end")) or now
    environments = payload.get("environments") or list(ALLOWED_ENVIRONMENTS)
    if not isinstance(environments, list):
        raise ValueError("扫描环境格式无效")
    environments = list(dict.fromkeys(str(value) for value in environments))
    if not environments or any(value not in ALLOWED_ENVIRONMENTS for value in environments):
        raise ValueError("扫描环境无效")
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    if end - start > timedelta(days=180):
        raise ValueError("赠金候选扫描最长180天")
    try:
        deep_limit = int(payload.get("deepLimit", 100))
        min_grant = float(payload.get("minGrant", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("扫描参数格式无效") from exc
    if not 1 <= deep_limit <= 300:
        raise ValueError("深检账号上限必须在1到300之间")
    if not 0 <= min_grant <= 10_000_000:
        raise ValueError("最低赠金额必须在0到10000000之间")
    exclude_handled = payload.get("excludeHandled", True)
    if not isinstance(exclude_handled, bool):
        raise ValueError("排除已处置账户参数必须是布尔值")
    return {
        "start": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end.strftime("%Y-%m-%d %H:%M:%S"),
        "environments": environments,
        "deepLimit": deep_limit,
        "minGrant": min_grant,
        "excludeHandled": exclude_handled,
    }


def _daily_shards(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        boundary = min(cursor + timedelta(days=1), end)
        yield cursor, boundary
        cursor = boundary


def _merge_candidate(target: dict, row: dict) -> None:
    target["grantCount"] += int(number(row.get("grantCount")))
    target["explicitGrantCount"] += int(number(row.get("explicitGrantCount")))
    target["grantAmount"] += number(row.get("grantAmount"))
    latest = str(row.get("latestGrant") or "")
    if latest > target["latestGrant"]:
        target["latestGrant"] = latest


def _candidate_rank_key(row: dict) -> tuple:
    deposit_total = number(row.get("depositTotal"))
    has_deposit = deposit_total > 0
    return (
        int(has_deposit),
        number(row.get("marginToDeposit")) if has_deposit else -1.0,
        number(row.get("currentMargin")),
        int(number(row.get("explicitGrantCount")) > 0),
        number(row.get("grantAmount")),
        number(row.get("grantCount")),
        str(row.get("latestGrant") or ""),
    )


class BonusArbitrageScanService:
    def __init__(self, repository: BonusScanRepository):
        self.repository = repository

    def run(
        self,
        payload: dict,
        *,
        progress: Progress,
        cancelled: Cancelled,
        handled_logins: set[str] | None = None,
    ) -> dict:
        options = normalize_bonus_scan_options(payload)
        started_at = time.monotonic()
        start = parse_datetime(options["start"])
        end = parse_datetime(options["end"])
        assert start and end
        units = self.repository.scan_units(options["environments"])
        shards = list(_daily_shards(start, end))
        total_shards = max(len(units) * len(shards), 1)
        merged: dict[tuple[str, str, str], dict] = {}
        failures: list[dict] = []
        completed_shards = 0
        progress_lock = Lock()

        def scan_unit(unit: dict) -> tuple[list[dict], list[dict]]:
            nonlocal completed_shards
            unit_rows = []
            unit_failures = []
            for shard_start, shard_end in shards:
                if cancelled():
                    raise BonusScanCancelled("任务已取消")
                with progress_lock:
                    progress(
                        3 + round(completed_shards / total_shards * 32),
                        f"{unit['label']}：扫描 {shard_start:%m-%d} 赠金事件",
                    )
                try:
                    rows = self.repository.discover_candidates(unit["id"], shard_start, shard_end)
                except Exception as day_error:
                    rows = []
                    segment = shard_start
                    while segment < shard_end:
                        segment_end = min(segment + timedelta(hours=6), shard_end)
                        try:
                            rows.extend(self.repository.discover_candidates(unit["id"], segment, segment_end))
                        except Exception as exc:
                            unit_failures.append({
                                "stage": "candidate",
                                "source": unit["label"],
                                "start": segment.strftime("%Y-%m-%d %H:%M:%S"),
                                "end": segment_end.strftime("%Y-%m-%d %H:%M:%S"),
                                "reason": str(exc),
                                "fallbackFrom": str(day_error),
                            })
                        segment = segment_end
                unit_rows.extend(rows)
                with progress_lock:
                    completed_shards += 1
            route_candidates = getattr(self.repository, "route_candidates", None)
            if callable(route_candidates) and unit_rows:
                try:
                    unit_rows = route_candidates(unit["id"], unit_rows)
                except Exception as exc:
                    unit_failures.append({
                        "stage": "candidate_route",
                        "source": unit["label"],
                        "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                        "reason": str(exc),
                    })
                    unit_rows = []
            return unit_rows, unit_failures

        candidate_workers = min(CANDIDATE_WORKERS, max(len(units), 1))
        with ThreadPoolExecutor(max_workers=candidate_workers, thread_name_prefix="bonus-candidate") as executor:
            futures = [executor.submit(scan_unit, unit) for unit in units]
            for future in as_completed(futures):
                rows, unit_failures = future.result()
                failures.extend(unit_failures)
                for row in rows:
                    key = (str(row.get("crmSchema") or ""), str(row.get("serverCode") or ""), str(row.get("account") or ""))
                    if key not in merged:
                        merged[key] = {
                            **row,
                            "grantCount": 0,
                            "explicitGrantCount": 0,
                            "grantAmount": 0.0,
                            "latestGrant": "",
                        }
                    _merge_candidate(merged[key], row)

        candidates = list(merged.values())
        aggregate_candidates = len(candidates)
        handled_logins = handled_logins or set()
        excluded_handled = 0
        excluded_below_grant = 0
        retained = []
        for candidate in candidates:
            database_status = str(candidate.get("databaseStatus") or "").strip().upper()
            if options["excludeHandled"] and (
                str(candidate.get("account") or "") in handled_logins
                or database_status in HANDLED_DATABASE_STATUSES
            ):
                excluded_handled += 1
                continue
            if number(candidate.get("grantAmount")) < options["minGrant"]:
                excluded_below_grant += 1
                continue
            retained.append(candidate)
        enrich_ranking_metrics = getattr(self.repository, "enrich_ranking_metrics", None)
        if callable(enrich_ranking_metrics) and retained:
            progress(36, f"正在批量计算 {len(retained)} 个候选账户的保证金 / 入金比例")
            try:
                ranking = enrich_ranking_metrics(retained)
                retained = list(ranking.get("candidates") or retained)
                failures.extend(ranking.get("failures") or [])
            except Exception as exc:
                failures.append({
                    "stage": "candidate_rank",
                    "source": "全平台候选排序",
                    "reason": str(exc),
                    "fallback": "赠金证据排序",
                })
        retained.sort(key=_candidate_rank_key, reverse=True)
        deep_queue = retained[: options["deepLimit"]]
        progress(38, f"候选初筛完成：按保证金 / 入金比例排序，准备深检{len(deep_queue)}个账户")

        analyzer = BonusArbitrageService(self.repository)
        results = []
        prepare_deep_candidates = getattr(self.repository, "prepare_deep_candidates", None)
        if callable(prepare_deep_candidates) and deep_queue:
            progress(39, f"正在批量准备 {len(deep_queue)} 个账户的画像与关系")
            prepare_deep_candidates(deep_queue)

        def analyze_candidate(candidate: dict) -> dict:
            if cancelled():
                raise BonusScanCancelled("任务已取消")
            result = analyzer.analyze(
                str(candidate["account"]),
                {
                    "platform": str(candidate.get("platform") or ""),
                    "server": str(candidate.get("server") or ""),
                    "symbol": "",
                    "start": "",
                    "end": "",
                    "_candidateMapping": {
                        "crmSchema": candidate.get("crmSchema"),
                        "serverCode": candidate.get("serverCode"),
                        "user_id": candidate.get("userId"),
                        "mt_login": candidate.get("account"),
                        "mt_server_code": candidate.get("serverCode"),
                        "status": candidate.get("databaseStatus"),
                        "mt_type_name": candidate.get("mtTypeName"),
                        "create_time": candidate.get("registration"),
                    },
                },
                stage="deep",
                cancelled=cancelled,
            )
            cycles = list((result.get("evidence") or {}).get("cycles") or [])
            return {
                "account": str(candidate["account"]),
                "platform": candidate.get("platform"),
                "server": candidate.get("server"),
                "environment": candidate.get("environment"),
                "currency": (result.get("source") or {}).get("currency") or candidate.get("currency"),
                "candidateGrantAmount": round(number(candidate.get("grantAmount")), 2),
                "candidateGrantCount": int(number(candidate.get("grantCount"))),
                "explicitGrantCount": int(number(candidate.get("explicitGrantCount"))),
                "latestGrant": candidate.get("latestGrant"),
                "currentMargin": round(number(candidate.get("currentMargin")), 2),
                "depositTotal": round(number(candidate.get("depositTotal")), 2),
                "marginToDeposit": (
                    round(number(candidate.get("marginToDeposit")), 6)
                    if number(candidate.get("depositTotal")) > 0 else None
                ),
                "score": number(result.get("score")),
                "level": result.get("level"),
                "confidence": result.get("confidence"),
                "summary": result.get("summary"),
                "cycleCount": len(cycles),
                "bestCycle": cycles[0] if cycles else None,
                "triggeredRules": list(result.get("triggeredRules") or []),
                "limitations": list(result.get("limitations") or []),
            }

        deep_workers = min(DEEP_WORKERS, max(len(deep_queue), 1))
        if deep_queue:
            progress(40, f"开始 {deep_workers} 路并行深检，共 {len(deep_queue)} 个账户")
            with ThreadPoolExecutor(max_workers=deep_workers, thread_name_prefix="bonus-deep") as executor:
                future_candidates = {
                    executor.submit(analyze_candidate, candidate): candidate
                    for candidate in deep_queue
                }
                completed_accounts = 0
                for future in as_completed(future_candidates):
                    candidate = future_candidates[future]
                    try:
                        results.append(future.result())
                    except BonusAnalysisCancelled as exc:
                        raise BonusScanCancelled("任务已取消") from exc
                    except BonusScanCancelled:
                        raise
                    except Exception as exc:
                        failures.append({
                            "stage": "deep",
                            "source": candidate.get("source"),
                            "environment": candidate.get("environment"),
                            "platform": candidate.get("platform"),
                            "server": candidate.get("server"),
                            "account": str(candidate.get("account") or ""),
                            "reason": str(exc),
                        })
                    completed_accounts += 1
                    progress(
                        40 + round(completed_accounts / len(deep_queue) * 57),
                        f"已深检 {candidate['server']} 账号 {candidate['account']}（{completed_accounts}/{len(deep_queue)}）",
                    )

        results.sort(key=lambda row: (
            -number(row.get("score")),
            -number((row.get("bestCycle") or {}).get("extractionMatch")),
            -number(row.get("candidateGrantAmount")),
        ))
        levels = Counter(row.get("level") for row in results)
        progress(99, "正在整理赠金套利风险榜与失败明细")
        return {
            "options": options,
            "summary": {
                "candidateAccounts": aggregate_candidates,
                "retainedCandidates": len(retained),
                "deepAccounts": len(deep_queue),
                "analyzedAccounts": len(results),
                "warnings": levels.get("预警", 0),
                "highRisk": levels.get("高危形态", 0),
                "severe": levels.get("严重形态", 0),
                "belowWarning": sum(1 for row in results if number(row.get("score")) < 60),
                "excludedHandled": excluded_handled,
                "excludedBelowGrant": excluded_below_grant,
                "notDeepChecked": max(len(retained) - len(deep_queue), 0),
                "failures": len(failures),
                "elapsedSeconds": round(time.monotonic() - started_at, 1),
            },
            "results": [row for row in results if number(row.get("score")) >= 60],
            "allResults": results,
            "failureTotal": len(failures),
            "failures": failures,
            "partialFailure": bool(failures),
        }
