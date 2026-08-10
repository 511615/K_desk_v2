# ruff: noqa: E402, I001
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "services" / "copy_pool_runtime"
EXTERNAL_DEPS = Path("D:/risk/pydeps")
if EXTERNAL_DEPS.is_dir() and str(EXTERNAL_DEPS) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_DEPS))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from copy_pool_multisource import ReadOnlySource
from copy_trading_multi_demo import MultiSourceLiveService


def test_runtime_recovery_request_resets_every_source_once_and_preserves_cursors(tmp_path: Path) -> None:
    reset_calls: list[str] = []
    request = tmp_path / "runtime_recovery_request.json"
    request.write_text(json.dumps({"revision": "recover-001", "action": "reconnect_and_sync"}), encoding="utf-8")
    service = object.__new__(MultiSourceLiveService)
    service.runtime_recovery_request_path = request
    service.runtime_recovery_status_path = tmp_path / "runtime_recovery_status.json"
    service.runtime_recovery_requested_at = ""
    service.db = SimpleNamespace(sources={
        "a": SimpleNamespace(
            reset_connection=lambda: reset_calls.append("a"),
            health=SimpleNamespace(state="ok"),
        ),
        "b": SimpleNamespace(
            reset_connection=lambda: reset_calls.append("b"),
            health=SimpleNamespace(state="error"),
        ),
    })
    cursors = {"a": object(), "b": object()}
    service.portfolio = SimpleNamespace(cursors=cursors)
    service.phase = "live"
    service.operational_ready_once = True
    service.reconcile_streak = 9
    service.pending_source_snapshot_count = 0
    service.log = lambda *_args: None

    assert service.consume_runtime_recovery_request() is True
    assert reset_calls == ["a", "b"]
    assert service.portfolio.cursors is cursors
    assert service.phase == "reconnecting"
    assert service.operational_ready_once is False
    assert service.reconcile_streak == 0
    status = json.loads(service.runtime_recovery_status_path.read_text(encoding="utf-8"))
    assert status["revision"] == "recover-001"
    assert status["state"] == "running"
    assert status["cursor_sources"] == 2
    assert status["position_count"] == 0

    service._write_runtime_recovery_status(
        "synchronized",
        revision="recover-001",
        requested_at=status["requested_at"],
    )
    completed = json.loads(service.runtime_recovery_status_path.read_text(encoding="utf-8"))
    assert completed["successful_sources"] == 1

    assert service.consume_runtime_recovery_request() is False
    assert reset_calls == ["a", "b"]


def test_build_query_retries_only_retryable_mysql_disconnect() -> None:
    assert MultiSourceLiveService.is_runtime_recovery_phase("reconnecting") is True
    assert MultiSourceLiveService.is_runtime_recovery_phase("live") is False


class _Cursor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql, _params) -> None:
        if self.error:
            raise self.error

    def fetchall(self):
        return ({"Login": 1},)


class _Connection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def ping(self, *, reconnect: bool) -> None:
        assert reconnect is False

    def cursor(self):
        return _Cursor(self.error)

    def close(self) -> None:
        pass


def _query_source(errors: list[Exception | None]) -> tuple[ReadOnlySource, list[int]]:
    source = object.__new__(ReadOnlySource)
    source.lock = threading.RLock()
    source.connection = None
    source.build_reconnect_attempts = 0
    source.health = SimpleNamespace(success=lambda *_args: None, failure=lambda *_args: None)
    attempts: list[int] = []

    def connect() -> None:
        attempts.append(len(attempts) + 1)
        source.connection = _Connection(errors[len(attempts) - 1])

    source.connect = connect
    return source, attempts


def test_read_only_build_query_retries_connection_loss_but_not_sql_error() -> None:
    source, attempts = _query_source([RuntimeError(2013, "Lost connection to MySQL server"), None])
    assert source.query("SELECT Login FROM accounts", reconnect_attempts=2) == [{"Login": 1}]
    assert attempts == [1, 2]

    source, attempts = _query_source([RuntimeError(1064, "SQL syntax error")])
    with pytest.raises(RuntimeError, match="1064"):
        source.query("SELECT Login FROM accounts", reconnect_attempts=2)
    assert attempts == [1]
