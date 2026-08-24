from __future__ import annotations

import multiprocessing
import time
from queue import Empty
from typing import Any

from kdesk.application.relationship_network import AccountRelationshipNetworkService
from kdesk.application.relationship_risk import AccountRelationshipRiskService
from kdesk.application.trade_relationship_detection import TradeRelationshipDetectionService
from kdesk.infrastructure.kuzu_risk_graph import KuzuRiskGraphRepository
from kdesk.infrastructure.legacy_bridge import LegacyBridge
from kdesk.infrastructure.position_risk import LegacyPositionRiskRepository
from kdesk.settings import Settings


def _relationship_worker(
    result_queue: Any,
    settings: Settings,
    login: str,
    filters: dict[str, str],
    threshold: float,
    include_toxic: bool,
    discovery_timeout_seconds: float,
    source_timeout_seconds: float,
) -> None:
    """Build one graph in a disposable process so native/query allocations leave with it."""
    network: AccountRelationshipNetworkService | None = None
    try:
        legacy = LegacyBridge(settings)
        network = AccountRelationshipNetworkService(
            legacy.call,
            source_timeout_seconds=source_timeout_seconds,
        )
        kuzu = KuzuRiskGraphRepository(
            settings.kuzu_risk_path or settings.runtime_dir / "relationship_risk_graph.kuzu"
        )
        risk = AccountRelationshipRiskService(
            network,
            kuzu.score_projection,
            lambda account, active_filters: legacy.call(
                "account_shared_last_ip_payload", account, active_filters
            ),
            lambda account, active_filters: TradeRelationshipDetectionService(
                LegacyPositionRiskRepository(legacy)
            ).analyze(account, active_filters),
            shared_cid_lookup=lambda account, active_filters: legacy.call(
                "account_shared_cid_payload", account, active_filters
            ),
            discovery_timeout_seconds=discovery_timeout_seconds,
        )
        final = risk.build(
            login,
            filters,
            threshold,
            include_toxic=include_toxic,
            on_progress=lambda snapshot: result_queue.put(("progress", snapshot)),
        )
        result_queue.put(("complete", final))
    except Exception:
        result_queue.put(("error", "关系隔离进程执行失败"))
    finally:
        if network is not None:
            network.close()


class IsolatedRelationshipRiskBuilder:
    """Run each production relationship investigation in one short-lived child process."""

    def __init__(
        self,
        settings: Settings,
        *,
        discovery_timeout_seconds: float,
        source_timeout_seconds: float,
        process_timeout_seconds: float = 45.0,
        worker_target: Any = _relationship_worker,
    ) -> None:
        if discovery_timeout_seconds <= 0 or source_timeout_seconds <= 0 or process_timeout_seconds <= 0:
            raise ValueError("relationship process limits must be positive")
        self._settings = settings
        self._discovery_timeout_seconds = discovery_timeout_seconds
        self._source_timeout_seconds = source_timeout_seconds
        self._process_timeout_seconds = process_timeout_seconds
        self._worker_target = worker_target

    def build(
        self,
        login: str,
        filters: dict[str, str],
        threshold: float,
        *,
        include_toxic: bool = False,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue(maxsize=4)
        process = context.Process(
            target=self._worker_target,
            args=(
                result_queue,
                self._settings,
                str(login),
                dict(filters),
                float(threshold),
                bool(include_toxic),
                self._discovery_timeout_seconds,
                self._source_timeout_seconds,
            ),
            daemon=False,
        )
        latest_progress: dict[str, Any] | None = None
        deadline = time.monotonic() + self._process_timeout_seconds
        try:
            process.start()
            while time.monotonic() < deadline:
                try:
                    kind, value = result_queue.get(timeout=min(0.5, max(deadline - time.monotonic(), 0.01)))
                except Empty:
                    if not process.is_alive():
                        break
                    continue
                if kind == "progress" and isinstance(value, dict):
                    latest_progress = value
                    if on_progress is not None:
                        on_progress(value)
                    continue
                if kind == "complete" and isinstance(value, dict):
                    return value
                raise RuntimeError(str(value) or "关系隔离进程执行失败")

            if latest_progress is not None:
                limitations = list(latest_progress.get("limitations") or [])
                limitations.append(
                    f"关系隔离进程达到 {self._process_timeout_seconds:g} 秒硬上限；已保留当前部分结果并回收进程内存。"
                )
                return {
                    **latest_progress,
                    "limitations": limitations,
                    "inProgress": False,
                    "discoveryTruncated": True,
                    "queryBudgetExhausted": True,
                }
            raise RuntimeError(
                f"关系隔离进程在 {self._process_timeout_seconds:g} 秒内没有返回可用证据"
            )
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            result_queue.close()
            result_queue.join_thread()
