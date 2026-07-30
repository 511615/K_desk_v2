from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Protocol

from kdesk.domain.rebate_churning import (
    candidate_accounts,
    cohort_thresholds,
    integer,
    normalize_scan_options,
    number,
    score_ib,
)

ENVIRONMENT_LABELS = {"gb": "AC GB", "cn": "AC CN", "dbg_cn": "DBG CN", "dbg_vn": "DBG VN"}


class RebateScanRepository(Protocol):
    def discover_active_ibs(self, environment: str, start: str, end: str) -> set[int]: ...
    def load_rebate_rows(self, environment: str, ib_ids: set[int], start: str, end: str) -> list[dict]: ...
    def proxy_accounts(self, environment: str, rows: list[dict]) -> list[dict]: ...
    def load_deep_accounts(self, environment: str, ib_id: int, keys: set[tuple[str, int]], rows: list[dict], start: str, end: str) -> list[dict]: ...
    def ib_names(self, environment: str, ib_ids: set[int]) -> dict[int, dict]: ...
    def ib_display_name(self, row: dict) -> str: ...


Progress = Callable[[int, str], None]
Cancelled = Callable[[], bool]


class ScanCancelled(RuntimeError):
    pass


def _batches(values, size: int = 50):
    values = list(values)
    for index in range(0, len(values), size):
        yield values[index:index + size]


class RebateChurningScanService:
    def __init__(self, repository: RebateScanRepository):
        self.repository = repository

    def run(self, payload: dict, *, progress: Progress, cancelled: Cancelled) -> dict:
        options = normalize_scan_options(payload)
        started = time.monotonic()
        results = []
        failures = []
        environment_summaries = []
        all_ib_count = all_account_count = deep_count = 0
        total_environments = len(options["environments"])
        for env_index, environment in enumerate(options["environments"]):
            if cancelled():
                raise ScanCancelled("任务已取消")
            label = ENVIRONMENT_LABELS[environment]
            progress(3 + round(env_index / total_environments * 90), f"{label}：按日分片发现活跃收佣IB")
            try:
                ib_ids = self.repository.discover_active_ibs(environment, options["start"], options["end"])
                all_ib_count += len(ib_ids)
                if not ib_ids:
                    environment_summaries.append({"environment": environment, "label": label, "ibs": 0, "accounts": 0, "deepAccounts": 0, "results": 0})
                    continue
                proxies = []
                ib_batches = list(_batches(sorted(ib_ids)))
                for batch_index, ib_batch in enumerate(ib_batches):
                    if cancelled():
                        raise ScanCancelled("任务已取消")
                    progress(
                        4 + round((env_index + (batch_index + 1) / max(len(ib_batches), 1) * 0.2) / total_environments * 88),
                        f"{label}：聚合返佣账户（{batch_index + 1}/{len(ib_batches)}批）",
                    )
                    batch_rows = self.repository.load_rebate_rows(
                        environment, set(ib_batch), options["start"], options["end"]
                    )
                    proxies.extend(self.repository.proxy_accounts(environment, batch_rows))
                selected, baselines = candidate_accounts(proxies)
                all_account_count += len(proxies)
                deep_count += len(selected)
                by_ib_keys = defaultdict(set)
                by_ib_proxies = defaultdict(list)
                for proxy in proxies:
                    ib_id = integer(proxy.get("ibId"))
                    key = (str(proxy.get("serverCode") or ""), integer(proxy.get("account")))
                    by_ib_proxies[ib_id].append(proxy)
                    if key in selected:
                        by_ib_keys[ib_id].add(key)
                names = self.repository.ib_names(environment, ib_ids)
                environment_results = 0
                for ib_index, ib_id in enumerate(sorted(ib_ids)):
                    if cancelled():
                        raise ScanCancelled("任务已取消")
                    keys = by_ib_keys.get(ib_id, set())
                    if not keys:
                        continue
                    progress(
                        5 + round((env_index + (ib_index + 1) / max(len(ib_ids), 1)) / total_environments * 88),
                        f"{label}：深检IB {ib_id}（{ib_index + 1}/{len(ib_ids)}）",
                    )
                    try:
                        ib_rows = self.repository.load_rebate_rows(
                            environment, {ib_id}, options["start"], options["end"]
                        )
                        proxy_thresholds = cohort_thresholds(by_ib_proxies[ib_id])
                        accounts = self.repository.load_deep_accounts(
                            environment, ib_id, keys, ib_rows, options["start"], options["end"]
                        )
                        deep_keys = {(str(row.get("serverCode") or ""), integer(row.get("account"))) for row in accounts}
                        accounts.extend({
                            **proxy,
                            "cohortThresholds": baselines.get(
                                (str(proxy.get("serverCode") or ""), "USC" if proxy.get("isCent") else "USD"),
                                proxy_thresholds,
                            ),
                            "currentIbRebateRows": integer(proxy.get("orders")),
                            "matchedRebateOrders": 0,
                            "tradeProfit": 0.0,
                            "hierarchyRebate": number(proxy.get("currentIbRebate")),
                            "evidenceTags": [],
                        } for proxy in by_ib_proxies[ib_id] if (str(proxy.get("serverCode") or ""), integer(proxy.get("account"))) not in deep_keys)
                        for account in accounts:
                            cohort_key = (str(account.get("serverCode") or ""), "USC" if "USC" in str(account.get("typeName") or "").upper() or "CENT" in str(account.get("typeName") or "").upper() else "USD")
                            account["cohortThresholds"] = baselines.get(cohort_key, proxy_thresholds)
                        scored = score_ib(accounts, ib_id=ib_id, environment=environment, thresholds=proxy_thresholds)
                        name = names.get(ib_id, {})
                        scored["ibName"] = self.repository.ib_display_name(name) or f"IB {ib_id}"
                        scored["ibLevel"] = name.get("ib_level")
                        scored["period"] = {"start": options["start"], "end": options["end"]}
                        results.append(scored)
                        environment_results += 1
                    except Exception as exc:
                        failures.append({"stage": "deep", "environment": environment, "ibId": ib_id, "reason": str(exc), "attempts": 1})
                environment_summaries.append({"environment": environment, "label": label, "ibs": len(ib_ids), "accounts": len(proxies), "deepAccounts": len(selected), "results": environment_results})
            except ScanCancelled:
                raise
            except Exception as exc:
                failures.append({"stage": "environment", "environment": environment, "reason": str(exc), "attempts": 1})
                environment_summaries.append({"environment": environment, "label": label, "failed": True, "reason": str(exc)})
        results.sort(key=lambda row: (-number(row.get("score")), -number((row.get("summary") or {}).get("currentIbRebate")), -integer((row.get("summary") or {}).get("suspiciousCustomers"))))
        levels = Counter(row.get("level") for row in results)
        ranked = [row for row in results if number(row.get("score")) >= 60]
        progress(99, "正在整理IB风险榜与部分失败明细")
        return {
            "options": options,
            "summary": {
                "activeIbs": all_ib_count, "rebateAccounts": all_account_count, "deepAccounts": deep_count,
                "warnings": sum(1 for row in results if 60 <= number(row.get("score")) < 75),
                "highRisk": sum(1 for row in results if 75 <= number(row.get("score")) < 90),
                "severe": levels.get("严重", 0), "lowRisk": sum(1 for row in results if number(row.get("score")) < 60),
                "failures": len(failures), "elapsedSeconds": round(time.monotonic() - started, 1),
            },
            "environmentSummary": environment_summaries,
            "results": ranked,
            "allResults": results,
            "failureTotal": len(failures), "failures": failures,
            "partialFailure": bool(failures),
        }
