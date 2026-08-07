# ruff: noqa: E402, I001
from __future__ import annotations

import sys
import threading
from concurrent.futures import Future
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "services" / "copy_pool_runtime"
EXTERNAL_DEPS = Path("D:/risk/pydeps")
if EXTERNAL_DEPS.exists() and str(EXTERNAL_DEPS) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_DEPS))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from copy_trading_multi_demo import HourlyDiscoveryResult, MultiSourceLiveService


NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)


def make_service(tmp_path: Path) -> MultiSourceLiveService:
    service = object.__new__(MultiSourceLiveService)
    service.universe_frame = pd.DataFrame([{
        "account_key": "source:1",
        "factor_ready": True,
    }])
    service.pool_build_as_of = NOW
    service._hourly_discovery_generation = 3
    service._hourly_background_enabled = True
    service._hourly_discovery_executor = None
    service._hourly_discovery_future = None
    service.last_discovery_attempt = 0.0
    service.coverage = {}
    service.coverage_path = tmp_path / "coverage.json"
    service.pool_frame = pd.DataFrame([{"account_key": "accepted:1"}])
    service.log = lambda *_args: None
    return service


def test_background_hourly_collect_uses_its_own_database_without_blocking_poll(tmp_path: Path) -> None:
    collect_started = threading.Event()
    release_collect = threading.Event()
    created: list[object] = []

    class WorkerDatabase:
        def __init__(self) -> None:
            self.closed = False
            created.append(self)

        def connect(self) -> None:
            return None

        def refresh_hourly_universe(self, universe, *, build_as_of, as_of):
            assert build_as_of == NOW
            assert as_of == NOW
            assert universe is not service.universe_frame
            collect_started.set()
            assert release_collect.wait(timeout=2.0)
            return pd.DataFrame(), {"factor_ready_sleeves_scanned": 0}

        def close(self) -> None:
            self.closed = True

    class MainDatabase:
        def __init__(self) -> None:
            self.polls = 0

        def poll_mt5_events(self, _cursors):
            self.polls += 1
            return [], []

    service = make_service(tmp_path)
    service.db = MainDatabase()
    service._commit_hourly_discovery = lambda _result: None

    with patch("copy_trading_multi_demo.MultiSourceDatabase", WorkerDatabase), patch(
        "copy_trading_multi_demo.utc_now", return_value=NOW
    ):
        service.run_hourly_discovery()
        assert collect_started.wait(timeout=0.5)
        assert service.db.poll_mt5_events({}) == ([], [])
        assert service.db.polls == 1
        assert len(created) == 1
        assert created[0] is not service.db
        release_collect.set()
        assert service._hourly_discovery_future.result(timeout=1.0).generation == 3
        service._consume_completed_hourly_discovery()
        service.shutdown_hourly_discovery_worker()

    assert created[0].closed


def test_completed_hourly_result_commits_only_when_generation_still_matches(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    committed: list[HourlyDiscoveryResult] = []
    service._commit_hourly_discovery = committed.append

    stale = Future()
    stale.set_result(HourlyDiscoveryResult(2, NOW, pd.DataFrame(), {}))
    service._hourly_discovery_future = stale
    service._consume_completed_hourly_discovery()

    current = Future()
    result = HourlyDiscoveryResult(3, NOW, pd.DataFrame(), {"status": "ok"})
    current.set_result(result)
    service._hourly_discovery_future = current
    service._consume_completed_hourly_discovery()

    assert committed == [result]


def test_completed_hourly_result_is_committed_without_starting_another_collect(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    committed: list[HourlyDiscoveryResult] = []
    service._commit_hourly_discovery = committed.append
    completed = Future()
    result = HourlyDiscoveryResult(3, NOW, pd.DataFrame(), {"status": "ok"})
    completed.set_result(result)
    service._hourly_discovery_future = completed
    service._start_hourly_discovery = lambda: (_ for _ in ()).throw(
        AssertionError("a completed result must not start another collection")
    )

    service.run_hourly_discovery()

    assert committed == [result]


def test_empty_hourly_result_without_account_column_retains_accepted_pool(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    accepted_pool = service.pool_frame
    result = HourlyDiscoveryResult(3, NOW, pd.DataFrame(), {})

    service._commit_hourly_discovery(result)

    assert service.pool_frame is accepted_pool
    assert service.coverage["hourly_discovery"]["status"] == "insufficient_qualified_accounts"
    assert service.coverage["hourly_discovery"]["pool_retained"] is True


def test_failed_hourly_collect_retains_pool_and_can_be_retried(tmp_path: Path) -> None:
    attempts = 0

    class FailingWorkerDatabase:
        def __init__(self) -> None:
            nonlocal attempts
            attempts += 1
            self.closed = False

        def connect(self) -> None:
            return None

        @staticmethod
        def refresh_hourly_universe(*_args, **_kwargs):
            raise TimeoutError("hourly source timed out")

        def close(self) -> None:
            self.closed = True

    service = make_service(tmp_path)
    accepted_pool = service.pool_frame
    with patch("copy_trading_multi_demo.MultiSourceDatabase", FailingWorkerDatabase), patch(
        "copy_trading_multi_demo.utc_now", return_value=NOW
    ):
        service.run_hourly_discovery()
        with pytest.raises(TimeoutError):
            service._hourly_discovery_future.result(timeout=1.0)
        service._consume_completed_hourly_discovery()
        service.run_hourly_discovery()
        with pytest.raises(TimeoutError):
            service._hourly_discovery_future.result(timeout=1.0)
        service.shutdown_hourly_discovery_worker()

    assert attempts == 2
    assert service.pool_frame is accepted_pool
    assert service.coverage["hourly_discovery"]["status"] == "failed"
    assert service.coverage["hourly_discovery"]["pool_retained"] is True


def test_public_status_is_throttled_but_forced_errors_are_written() -> None:
    service = object.__new__(MultiSourceLiveService)
    writes: list[float] = []
    service.write_status = lambda: writes.append(1.0)
    service.last_status_write = 100.0

    with patch("copy_trading_multi_demo.time.monotonic", return_value=100.5):
        assert service.write_status_if_due() is False
        assert service.write_status_if_due(force=True) is True
    with patch("copy_trading_multi_demo.time.monotonic", return_value=101.6):
        assert service.write_status_if_due() is True

    assert len(writes) == 2
