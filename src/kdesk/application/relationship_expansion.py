from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Protocol


class RelationshipRiskBuilder(Protocol):
    def build(
        self,
        login: str,
        filters: dict[str, str],
        threshold: float,
        *,
        include_toxic: bool = False,
        on_progress: Any = None,
    ) -> dict[str, Any]: ...


class AccountRelationshipExpansionCoordinator:
    """Single-flight, bounded background expansion that keeps the account API responsive."""

    def __init__(
        self,
        risk_builder: RelationshipRiskBuilder,
        *,
        max_concurrent_jobs: int = 1,
        cache_seconds: float = 90.0,
        max_resident_jobs: int = 3,
    ) -> None:
        if max_concurrent_jobs <= 0 or cache_seconds <= 0 or max_resident_jobs <= 0:
            raise ValueError("relationship expansion limits must be positive")
        self._risk_builder = risk_builder
        self._cache_seconds = cache_seconds
        self._max_resident_jobs = max_resident_jobs
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent_jobs, thread_name_prefix="relationship-expansion")
        self._jobs: dict[tuple[Any, ...], dict[str, Any]] = {}

    def get_or_start(self, login: str, filters: dict[str, str], threshold: float, include_toxic: bool) -> dict[str, Any]:
        key = (str(login), tuple(sorted((str(name), str(value)) for name, value in filters.items())), float(threshold), bool(include_toxic))
        with self._lock:
            self._prune_locked()
            job = self._jobs.get(key)
            if job is None:
                self._evict_completed_locked(self._max_resident_jobs - 1)
                if len(self._jobs) >= self._max_resident_jobs:
                    return self._busy_snapshot(login, filters)
                now = time.monotonic()
                job = {
                    "snapshot": self._pending_snapshot(login, filters),
                    "startedAt": now,
                    "updatedAt": now,
                    "accessedAt": now,
                    "finishedAt": 0.0,
                    "future": None,
                    "revision": 0,
                }
                self._jobs[key] = job
                job["future"] = self._executor.submit(self._run, key, str(login), dict(filters), float(threshold), bool(include_toxic))
            job["accessedAt"] = time.monotonic()
            snapshot = dict(job["snapshot"])
            snapshot["revision"] = int(job["revision"])
            progress = snapshot.get("progress")
            if isinstance(progress, dict):
                snapshot["progress"] = {
                    **progress,
                    "elapsedSeconds": round(max(time.monotonic() - float(job["startedAt"]), 0.0), 1),
                    "secondsSinceUpdate": round(max(time.monotonic() - float(job["updatedAt"]), 0.0), 1),
                }
            return snapshot

    def stats(self) -> dict[str, int | float]:
        with self._lock:
            self._prune_locked()
            running = queued = completed = 0
            for job in self._jobs.values():
                future = job.get("future")
                if isinstance(future, Future) and future.done():
                    completed += 1
                elif job.get("startedAt") and not job.get("finishedAt"):
                    if isinstance(future, Future) and future.running():
                        running += 1
                    else:
                        queued += 1
            return {
                "residentJobs": len(self._jobs),
                "runningJobs": running,
                "queuedJobs": queued,
                "completedJobs": completed,
                "maxResidentJobs": self._max_resident_jobs,
                "cacheSeconds": self._cache_seconds,
            }

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, key: tuple[Any, ...], login: str, filters: dict[str, str], threshold: float, include_toxic: bool) -> None:
        def update(snapshot: dict[str, Any]) -> None:
            with self._lock:
                job = self._jobs.get(key)
                if job is not None:
                    job["snapshot"] = {**snapshot, "inProgress": True}
                    job["updatedAt"] = time.monotonic()
                    job["revision"] += 1

        try:
            final = self._risk_builder.build(login, filters, threshold, include_toxic=include_toxic, on_progress=update)
            snapshot = {**final, "inProgress": False, "progress": {"state": "complete", "expandedAccounts": int((final.get("summary") or {}).get("discoveryAccountCount") or 0), "pendingAccounts": 0}}
        except Exception:
            snapshot = {
                "ok": False, "account": login, "filters": dict(filters), "entities": [], "relationships": [],
                "relationTypes": [], "coverage": [], "summary": {"discoveryAccountCount": 0, "pendingAccountCount": 0},
                "limitations": ["关系后台扩散失败，请重新计算。"], "inProgress": False,
                "progress": {"state": "failed", "expandedAccounts": 0, "pendingAccounts": 0},
            }
        with self._lock:
            job = self._jobs.get(key)
            if job is not None:
                job["snapshot"] = snapshot
                now = time.monotonic()
                job["updatedAt"] = now
                job["finishedAt"] = now
                job["revision"] += 1

    def _prune_locked(self) -> None:
        cutoff = time.monotonic() - self._cache_seconds
        for key, job in list(self._jobs.items()):
            future = job.get("future")
            if job.get("finishedAt", 0.0) and job["finishedAt"] < cutoff and isinstance(future, Future) and future.done():
                self._jobs.pop(key, None)
        self._evict_completed_locked(self._max_resident_jobs)

    def _evict_completed_locked(self, target_size: int) -> None:
        if len(self._jobs) <= target_size:
            return
        completed = sorted(
            (
                (key, job)
                for key, job in self._jobs.items()
                if job.get("finishedAt") and isinstance(job.get("future"), Future) and job["future"].done()
            ),
            key=lambda item: (float(item[1].get("accessedAt") or 0.0), float(item[1].get("finishedAt") or 0.0)),
        )
        for key, _job in completed:
            if len(self._jobs) <= target_size:
                break
            self._jobs.pop(key, None)

    @staticmethod
    def _pending_snapshot(login: str, filters: dict[str, str]) -> dict[str, Any]:
        return {
            "ok": True,
            "account": login,
            "filters": dict(filters),
            "entities": [],
            "relationships": [],
            "relationTypes": [],
            "coverage": [],
            "limitations": ["关系扩散任务已排队，首批证据准备中。"],
            "summary": {"discoveryAccountCount": 0, "pendingAccountCount": 1},
            "discoveryTruncated": False,
            "queryBudgetExhausted": False,
            "inProgress": True,
            "progress": {"state": "queued", "expandedAccounts": 0, "pendingAccounts": 1},
        }

    @staticmethod
    def _busy_snapshot(login: str, filters: dict[str, str]) -> dict[str, Any]:
        return {
            "ok": True,
            "account": login,
            "filters": dict(filters),
            "entities": [],
            "relationships": [],
            "relationTypes": [],
            "coverage": [],
            "limitations": ["关系任务并发已达内存安全上限，请等待当前任务完成后自动重试。"],
            "summary": {"discoveryAccountCount": 0, "pendingAccountCount": 1},
            "discoveryTruncated": False,
            "queryBudgetExhausted": False,
            "inProgress": True,
            "retryAfterSeconds": 3,
            "progress": {"state": "busy", "expandedAccounts": 0, "pendingAccounts": 1},
        }
