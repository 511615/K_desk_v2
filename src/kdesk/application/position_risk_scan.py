from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from math import isfinite
from threading import Lock
from typing import Protocol

from kdesk.application.position_risk import PositionRiskService
from kdesk.domain.position_risk import number, parse_datetime

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


class PositionRiskScanRepository(Protocol):
    def scan_units(self, environments: list[str]) -> list[dict]: ...
    def discover_candidates(self, unit_id: str, start: datetime, end: datetime) -> list[dict]: ...
    def route_candidates(self, unit_id: str, rows: list[dict]) -> list[dict]: ...
    def load_account_context(self, account: str, filters: dict) -> dict: ...
    def load_peer_accounts(self, account: str, context: dict, event: dict) -> dict: ...


Progress = Callable[[int, str], None]
Cancelled = Callable[[], bool]


class PositionRiskScanCancelled(RuntimeError):
    pass


def normalize_position_scan_options(payload: dict, *, now: datetime | None = None) -> dict:
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
    if end - start > timedelta(days=90):
        raise ValueError("重仓时点候选扫描最长90天")
    try:
        deep_limit = int(payload.get("deepLimit", 100))
    except (TypeError, ValueError) as exc:
        raise ValueError("深检账号上限格式无效") from exc
    if not 1 <= deep_limit <= 300:
        raise ValueError("深检账号上限必须在1到300之间")
    exclude_handled = payload.get("excludeHandled", True)
    if not isinstance(exclude_handled, bool):
        raise ValueError("排除已处置账户参数必须是布尔值")

    def optional_nonnegative(key: str, label: str) -> float | None:
        raw = payload.get(key)
        if raw is None or raw == "":
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}格式无效") from exc
        if not isfinite(value) or value < 0:
            raise ValueError(f"{label}必须是大于或等于0的数字")
        return value

    return {
        "start": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end.strftime("%Y-%m-%d %H:%M:%S"),
        "environments": environments,
        "deepLimit": deep_limit,
        "excludeHandled": exclude_handled,
        "minPositionPercent": optional_nonnegative("minPositionPercent", "最低仓位"),
        "minLots": optional_nonnegative("minLots", "最低手数"),
        "minProfit": optional_nonnegative("minProfit", "最小盈利金额"),
    }


def _daily_shards(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        boundary = min(cursor + timedelta(days=1), end)
        yield cursor, boundary
        cursor = boundary


def _candidate_key(row: dict) -> tuple[str, str, str]:
    return str(row.get("crmSchema") or ""), str(row.get("serverCode") or ""), str(row.get("account") or "")


def _passes_result_filters(row: dict, options: dict) -> bool:
    checks = (
        ("minPositionPercent", "marginRatio", 100.0),
        ("minLots", "peakLots", 1.0),
        ("minProfit", "netProfit", 1.0),
    )
    for option_key, result_key, scale in checks:
        threshold = options.get(option_key)
        if threshold is None:
            continue
        if row.get(result_key) is None or number(row.get(result_key)) * scale + 1e-9 < number(threshold):
            return False
    return True


class PositionRiskScanService:
    def __init__(self, repository: PositionRiskScanRepository):
        self.repository = repository

    def run(
        self,
        payload: dict,
        *,
        progress: Progress,
        cancelled: Cancelled,
        handled_logins: set[str] | None = None,
    ) -> dict:
        options = normalize_position_scan_options(payload)
        started_at = time.monotonic()
        start = parse_datetime(options["start"])
        end = parse_datetime(options["end"])
        assert start and end
        units = self.repository.scan_units(options["environments"])
        shards = list(_daily_shards(start, end))
        total_shards = max(len(units) * len(shards), 1)
        completed_shards = 0
        lock = Lock()
        failures: list[dict] = []

        def scan_unit(unit: dict) -> tuple[list[dict], list[dict]]:
            nonlocal completed_shards
            raw_rows = []
            unit_failures = []
            for shard_start, shard_end in shards:
                if cancelled():
                    raise PositionRiskScanCancelled("任务已取消")
                with lock:
                    progress(3 + round(completed_shards / total_shards * 32), f"{unit['label']}：扫描 {shard_start:%m-%d} 特殊时点")
                try:
                    raw_rows.extend(self.repository.discover_candidates(unit["id"], shard_start, shard_end))
                except Exception as exc:
                    unit_failures.append({
                        "stage": "candidate", "source": unit["label"],
                        "start": shard_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": shard_end.strftime("%Y-%m-%d %H:%M:%S"), "reason": str(exc),
                    })
                with lock:
                    completed_shards += 1
            if not raw_rows:
                return [], unit_failures
            try:
                routed = self.repository.route_candidates(unit["id"], raw_rows)
            except Exception as exc:
                unit_failures.append({"stage": "candidate_route", "source": unit["label"], "reason": str(exc)})
                return [], unit_failures
            peer_index: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
            for row in routed:
                first = parse_datetime(row.get("firstEvent"))
                if first:
                    peer_index[(str(row.get("physicalSource")), str(row.get("symbol")), int(first.timestamp()))].append(row)
            for row in routed:
                first = parse_datetime(row.get("firstEvent"))
                same_direction = set()
                opposite_direction = set()
                if first:
                    second = int(first.timestamp())
                    for nearby_second in range(second - 5, second + 6):
                        for peer in peer_index.get((str(row.get("physicalSource")), str(row.get("symbol")), nearby_second), []):
                            if str(peer.get("account")) == str(row.get("account")):
                                continue
                            target = same_direction if peer.get("direction") == row.get("direction") else opposite_direction
                            target.add(str(peer.get("account")))
                row["sameDirectionAccounts"] = sorted(same_direction)[:20]
                row["oppositeDirectionAccounts"] = sorted(opposite_direction)[:20]
                row["peerAccounts"] = row["sameDirectionAccounts"]
            return routed, unit_failures

        routed_rows: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(CANDIDATE_WORKERS, max(len(units), 1)), thread_name_prefix="position-candidate") as executor:
            futures = [executor.submit(scan_unit, unit) for unit in units]
            for future in as_completed(futures):
                rows, unit_failures = future.result()
                routed_rows.extend(rows)
                failures.extend(unit_failures)

        merged: dict[tuple[str, str, str], dict] = {}
        for row in routed_rows:
            key = _candidate_key(row)
            if key not in merged:
                merged[key] = {
                    **row,
                    "eventOrders": 0,
                    "eventLots": 0.0,
                    "eventNotional": 0.0,
                    "peakEventLots": 0.0,
                    "peakEventNotional": 0.0,
                    "peakEventKind": "",
                    "eventKinds": set(),
                    "sameDirectionAccounts": set(),
                    "oppositeDirectionAccounts": set(),
                    "peerAccounts": set(),
                    "firstEvent": "",
                    "latestEvent": "",
                }
            target = merged[key]
            target["eventOrders"] += int(number(row.get("orderCount")))
            target["eventLots"] += number(row.get("eventLots"))
            target["eventNotional"] += number(row.get("eventNotional"))
            if number(row.get("eventNotional")) > number(target.get("peakEventNotional")):
                target["peakEventNotional"] = number(row.get("eventNotional"))
                target["peakEventLots"] = number(row.get("eventLots"))
                target["peakEventKind"] = str(row.get("eventKind") or "")
            target["eventKinds"].add(str(row.get("eventKind") or ""))
            target["sameDirectionAccounts"].update(row.get("sameDirectionAccounts") or row.get("peerAccounts") or [])
            target["oppositeDirectionAccounts"].update(row.get("oppositeDirectionAccounts") or [])
            target["peerAccounts"].update(row.get("sameDirectionAccounts") or row.get("peerAccounts") or [])
            first = str(row.get("firstEvent") or "")
            latest = str(row.get("latestEvent") or "")
            if first and (not target["firstEvent"] or first < target["firstEvent"]):
                target["firstEvent"] = first
            if latest > target["latestEvent"]:
                target["latestEvent"] = latest

        handled_logins = handled_logins or set()
        excluded_handled = 0
        candidates = []
        for row in merged.values():
            if options["excludeHandled"] and (
                str(row.get("account")) in handled_logins
                or str(row.get("databaseStatus") or "").strip().upper() in HANDLED_DATABASE_STATUSES
            ):
                excluded_handled += 1
                continue
            row["eventKinds"] = sorted(value for value in row["eventKinds"] if value)
            row["sameDirectionAccounts"] = sorted(row["sameDirectionAccounts"])[:20]
            row["oppositeDirectionAccounts"] = sorted(row["oppositeDirectionAccounts"])[:20]
            row["peerAccounts"] = row["sameDirectionAccounts"]
            equity = max(abs(number(row.get("equity") or row.get("balance"))), 50.0)
            leverage = max(number(row.get("leverage")), 1.0)
            gross_ratio = number(row.get("peakEventNotional")) / equity
            margin_ratio = gross_ratio / leverage
            stress_ratio = gross_ratio * (0.01 if row.get("peakEventKind") == "weekend" else 0.005)
            row["initialExposureRatio"] = gross_ratio
            row["initialMarginRatio"] = margin_ratio
            row["initialStressRatio"] = stress_ratio
            row["initialRiskProxy"] = max(margin_ratio / 0.30, stress_ratio / 0.10)
            candidates.append(row)
        candidates.sort(
            key=lambda row: (
                (
                    (options["minPositionPercent"] is None or number(row.get("initialMarginRatio")) * 100 >= options["minPositionPercent"])
                    and (options["minLots"] is None or number(row.get("peakEventLots")) >= options["minLots"])
                ),
                number(row.get("initialRiskProxy")),
                row.get("peakEventKind") == "weekend",
                len(row.get("sameDirectionAccounts") or row.get("peerAccounts") or []),
                number(row.get("eventOrders")),
            ),
            reverse=True,
        )
        deep_queue = candidates[: options["deepLimit"]]
        progress(38, f"候选初筛完成：{len(candidates)}个，准备深检{len(deep_queue)}个账户")

        analyzer = PositionRiskService(self.repository)
        results = []
        deep_failures = []

        def analyze_candidate(candidate: dict) -> dict:
            if cancelled():
                raise PositionRiskScanCancelled("任务已取消")
            filters = {
                "platform": candidate.get("platform"),
                "server": candidate.get("server"),
                "start": options["start"],
                "end": options["end"],
                "_candidateMapping": candidate.get("_candidateMapping"),
            }
            analysis = analyzer.analyze(str(candidate["account"]), filters, stage="deep")
            best = analysis.get("bestResult") or {}
            event = (best.get("evidence") or {}).get("bestEvent") or {}
            return {
                "account": str(candidate["account"]),
                "platform": candidate.get("platform"),
                "server": candidate.get("server"),
                "environment": candidate.get("environment"),
                "currency": (analysis.get("source") or {}).get("currency") or candidate.get("currency"),
                "score": number(best.get("score")),
                "level": best.get("level") or "未见明显",
                "classification": event.get("classification") or "none",
                "summary": best.get("summary") or "没有形成可疑重仓时点事件",
                "eventStart": event.get("start") or candidate.get("firstEvent"),
                "eventEnd": event.get("end") or candidate.get("latestEvent"),
                "eventOrders": event.get("orderCount") or candidate.get("eventOrders"),
                "peakLots": event.get("peakLots") or candidate.get("peakEventLots"),
                "peakOrderCount": event.get("peakOrderCount") or event.get("orderCount") or candidate.get("eventOrders"),
                "peakGrossExposure": event.get("peakGrossExposure") or candidate.get("peakEventNotional"),
                "equityBefore": event.get("equityBefore"),
                "leverage": event.get("leverage") or candidate.get("leverage"),
                "grossLeverage": event.get("grossLeverage"),
                "estimatedMargin": event.get("estimatedMargin"),
                "marginRatio": event.get("marginRatio"),
                "estimatedMarginLevel": event.get("estimatedMarginLevel"),
                "stressRatio": event.get("stressRatio"),
                "baselineRatio": event.get("baselineRatio"),
                "directionRatio": event.get("directionRatio"),
                "entryBatchRatio": event.get("entryBatchRatio"),
                "holdingHours": event.get("holdingHours"),
                "netProfit": event.get("netProfit"),
                "actualLoss": event.get("actualLoss"),
                "lossToEquity": event.get("lossToEquity"),
                "penetrationStatus": event.get("penetrationStatus") or "数据不足",
                "penetrationReason": event.get("penetrationReason") or "未形成可核对的完整事件。",
                "penetrationDataGaps": event.get("penetrationDataGaps") or [],
                "eventClosed": event.get("eventClosed"),
                "equityReliable": event.get("equityReliable"),
                "negativeBalanceEvidence": event.get("negativeBalanceEvidence") or [],
                "sameDirectionAccounts": event.get("sameDirectionAccounts") or [],
                "oppositeDirectionAccounts": event.get("oppositeDirectionAccounts") or [],
                "peerAccounts": event.get("sameDirectionAccounts") or event.get("peerAccounts") or [],
                "sameDirectionMatches": event.get("sameDirectionMatches") or [],
                "oppositeDirectionMatches": event.get("oppositeDirectionMatches") or [],
                "sameDirectionMatchTotal": event.get("sameDirectionMatchTotal") or 0,
                "oppositeDirectionMatchTotal": event.get("oppositeDirectionMatchTotal") or 0,
                "peerMatchDetailLimit": event.get("peerMatchDetailLimit") or 0,
                "peerMatchesTruncated": bool(event.get("peerMatchesTruncated")),
                "peerSearchCoverage": event.get("peerSearchCoverage") or {},
                "heavyOrders": event.get("heavyOrders") or [],
                "scoreBasis": event.get("scoreBasis") or {},
                "triggeredRules": best.get("triggeredRules") or [],
                "limitations": best.get("limitations") or [],
                "analysis": best.get("analysis") or [],
                "initialExposureRatio": round(number(candidate.get("initialExposureRatio")), 2),
                "initialMarginRatio": round(number(candidate.get("initialMarginRatio")), 4),
                "initialStressRatio": round(number(candidate.get("initialStressRatio")), 4),
                "types": analysis.get("results") or [],
            }

        completed = 0
        with ThreadPoolExecutor(max_workers=min(DEEP_WORKERS, max(len(deep_queue), 1)), thread_name_prefix="position-deep") as executor:
            future_map = {executor.submit(analyze_candidate, candidate): candidate for candidate in deep_queue}
            for future in as_completed(future_map):
                candidate = future_map[future]
                try:
                    results.append(future.result())
                except PositionRiskScanCancelled:
                    raise
                except Exception as exc:
                    deep_failures.append({
                        "stage": "deep", "account": str(candidate.get("account")),
                        "platform": candidate.get("platform"), "server": candidate.get("server"),
                        "source": candidate.get("source"), "reason": str(exc),
                    })
                completed += 1
                progress(40 + round(completed / max(len(deep_queue), 1) * 55), f"账户深检 {completed}/{len(deep_queue)}")
        failures.extend(deep_failures)
        results.sort(key=lambda row: (number(row.get("score")), number(row.get("stressRatio"))), reverse=True)
        filtered_results = [row for row in results if _passes_result_filters(row, options)]
        warnings = [row for row in filtered_results if number(row.get("score")) >= 60]
        return {
            "summary": {
                "candidateAccounts": len(merged),
                "retainedCandidates": len(candidates),
                "excludedHandled": excluded_handled,
                "analyzedAccounts": len(results),
                "matchedFilters": len(filtered_results),
                "excludedByFilters": len(results) - len(filtered_results),
                "warnings": len(warnings),
                "highRisk": sum(1 for row in filtered_results if number(row.get("score")) >= 75),
                "severe": sum(1 for row in filtered_results if number(row.get("score")) >= 90),
                "notDeepChecked": max(len(candidates) - len(deep_queue), 0),
                "failures": len(failures),
                "elapsedSeconds": round(time.monotonic() - started_at, 1),
            },
            "filters": {
                "minPositionPercent": options["minPositionPercent"],
                "minLots": options["minLots"],
                "minProfit": options["minProfit"],
            },
            "results": warnings,
            "allResults": filtered_results,
            "failures": failures,
            "failureTotal": len(failures),
        }
