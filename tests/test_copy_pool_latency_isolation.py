# ruff: noqa: E402, I001
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "services" / "copy_pool_runtime"
EXTERNAL_DEPS = Path("D:/risk/pydeps")
if EXTERNAL_DEPS.exists() and str(EXTERNAL_DEPS) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_DEPS))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from copy_pool_multisource import ROUTES, MultiSourceDatabase, SourceHealth
from copy_trading_multi_demo import MultiSourceLiveService


class QuerySource:
    def __init__(self, key: str, platform: str, query) -> None:
        self.key = key
        self.platform = platform
        self.schema = "source_schema"
        self.query = query
        self.health = SourceHealth(
            physical_key=key,
            connection="test",
            schema=self.schema,
            platform=platform,
            logical_routes=(key,),
        )


def make_database(*sources: QuerySource) -> MultiSourceDatabase:
    database = object.__new__(MultiSourceDatabase)
    database.sources = {source.key: source for source in sources}
    database.clients = {}
    database.clients_by_source_login = {}
    database.factor_service = None
    return database


def subscribe(database: MultiSourceDatabase, **account_sources: str) -> None:
    clients = {
        account_key: SimpleNamespace(
            account_key=account_key,
            login=index + 1,
            physical_key=source_key,
        )
        for index, (account_key, source_key) in enumerate(account_sources.items())
    }
    database.set_clients(clients)


def test_physical_and_account_health_do_not_inherit_an_unrelated_source_age() -> None:
    fast = QuerySource("fast-mt5", "MT5", lambda _sql, _parameters: [])
    slow = QuerySource("slow-mt4", "MT4", lambda _sql, _parameters: [])
    database = make_database(fast, slow)
    subscribe(database, fast_account="fast-mt5", slow_account="slow-mt4")
    fast.health.last_success_monotonic = 99.9
    slow.health.last_success_monotonic = 40.0

    with patch("copy_pool_multisource.time.monotonic", return_value=100.0):
        assert database.physical_source_staleness("fast-mt5") == pytest.approx(0.1)
        assert database.account_source_staleness("fast_account") == pytest.approx(0.1)
        assert database.selected_source_staleness() == pytest.approx(60.0)

        physical_health = database.physical_source_health("fast-mt5")
        account_health = database.account_source_health("fast_account")

    assert physical_health["physical_key"] == "fast-mt5"
    assert physical_health["age_seconds"] == pytest.approx(0.1)
    assert account_health == physical_health


def test_five_mt5_sources_are_started_concurrently() -> None:
    release = threading.Event()
    all_started = threading.Event()
    started: set[str] = set()
    started_lock = threading.Lock()

    def source_for(index: int) -> QuerySource:
        key = f"mt5-{index}"

        def query(_sql, _parameters):
            with started_lock:
                started.add(key)
                if len(started) == 5:
                    all_started.set()
            assert release.wait(timeout=2.0)
            return []

        return QuerySource(key, "MT5", query)

    database = make_database(*(source_for(index) for index in range(5)))
    subscribe(database, **{f"account-{index}": f"mt5-{index}" for index in range(5)})
    outcome: dict[str, object] = {}

    def poll() -> None:
        outcome["value"] = database.poll_mt5_events({})

    polling_thread = threading.Thread(target=poll)
    polling_thread.start()
    try:
        assert all_started.wait(timeout=0.5), "a five-source MT5 poll must not queue its fifth source"
    finally:
        release.set()
        polling_thread.join(timeout=2.0)

    assert not polling_thread.is_alive()
    assert outcome["value"] == ([], [])


def test_slow_mt4_poll_does_not_delay_mt5_event_application() -> None:
    mt4_started = threading.Event()
    release_mt4 = threading.Event()
    mt5_applied = threading.Event()

    class Database:
        def poll_mt5_events(self, _cursors):
            return [], []

        def poll_mt4_positions(self):
            mt4_started.set()
            assert release_mt4.wait(timeout=2.0)
            return {}, []

    service = object.__new__(MultiSourceLiveService)
    service.db = Database()
    service.portfolio = SimpleNamespace(cursors={})
    service.apply_event_batch = lambda _events: mt5_applied.set()
    service.apply_mt4_snapshot = lambda _source_key, _rows: None
    outcome: dict[str, object] = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        cycle_thread = threading.Thread(
            target=lambda: outcome.setdefault("value", service._poll_source_cycle(executor))
        )
        cycle_thread.start()
        try:
            assert mt4_started.wait(timeout=0.5)
            assert mt5_applied.wait(timeout=0.5), "MT5 events must be applied before slow MT4 returns"
        finally:
            release_mt4.set()
            cycle_thread.join(timeout=2.0)

    assert not cycle_thread.is_alive()
    assert outcome["value"] == ([], [])


def test_live_open_gate_uses_the_signal_accounts_source_age() -> None:
    fast = QuerySource("fast-mt5", "MT5", lambda _sql, _parameters: [])
    slow = QuerySource("slow-mt4", "MT4", lambda _sql, _parameters: [])
    database = make_database(fast, slow)
    subscribe(database, fast_account="fast-mt5", slow_account="slow-mt4")
    fast.health.last_success_monotonic = 99.9
    slow.health.last_success_monotonic = 90.0

    service = object.__new__(MultiSourceLiveService)
    service.db = database
    service.portfolio = SimpleNamespace(duplicate_events=0)
    service.coverage = {
        "logical_routes_scanned": len(ROUTES),
        "physical_sources_scanned": len(database.sources),
    }
    service.reconcile_streak = 3
    service.pending_source_snapshot_count = 0
    service.poll_latencies = [0.1] * 20
    service.operational_ready_once = True

    with patch("copy_pool_multisource.time.monotonic", return_value=100.0):
        assert service.operational_gates_ready("fast_account") is True
        assert service.operational_gates_ready("slow_account") is False


def test_startup_gate_reports_the_exact_blocking_check() -> None:
    fast = QuerySource("fast-mt5", "MT5", lambda _sql, _parameters: [])
    database = make_database(fast)
    subscribe(database, fast_account="fast-mt5")
    fast.health.last_success_monotonic = 99.9
    service = object.__new__(MultiSourceLiveService)
    service.db = database
    service.portfolio = SimpleNamespace(duplicate_events=0)
    service.coverage = {
        "logical_routes_scanned": len(ROUTES),
        "physical_sources_scanned": 1,
    }
    service.reconcile_streak = 0
    service.pending_source_snapshot_count = 1
    service.poll_latencies = [0.1] * 20
    service.operational_ready_once = False

    with patch("copy_pool_multisource.time.monotonic", return_value=100.0):
        assert service._operational_gate_rejection_reason("fast_account") == (
            "execution_gate_blocked:source_reconcile"
        )
        service.reconcile_streak = 3
        service.pending_source_snapshot_count = 0
        service.poll_latencies = []
        assert service._operational_gate_rejection_reason("fast_account") == (
            "execution_gate_blocked:latency_warmup"
        )
