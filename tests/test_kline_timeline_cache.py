from __future__ import annotations

from pathlib import Path

from kdesk.application.kline_timeline_cache import KlineTimelineCache


def _replay(balance: float) -> dict:
    return {
        "summary": {"currency": "USD", "eventCount": 1},
        "events": [{"timestamp": "2026-01-01 00:00:00", "balance": balance, "credit": 0.0}],
        "curve": [{"timestamp": "2026-01-01 00:00:00", "balance": balance, "credit": 0.0}],
        "liquidationPoints": [],
    }


def test_timeline_cache_builds_once_then_reuses_the_full_history(tmp_path: Path) -> None:
    cache = KlineTimelineCache(tmp_path)
    calls = 0

    def build() -> dict:
        nonlocal calls
        calls += 1
        return _replay(100.0)

    first, first_status = cache.get_or_build("302360", "MT5", "DBG MT5", build)
    second, second_status = cache.get_or_build("302360", "MT5", "DBG MT5", build)

    assert calls == 1
    assert first_status == "built"
    assert second_status == "cache"
    assert first == second
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_timeline_cache_only_reads_source_again_when_user_requests_refresh(tmp_path: Path) -> None:
    cache = KlineTimelineCache(tmp_path)
    values = iter([100.0, 250.0])

    def build() -> dict:
        return _replay(next(values))

    cache.get_or_build("302360", "MT5", "DBG MT5", build)
    refreshed, status = cache.get_or_build("302360", "MT5", "DBG MT5", build, refresh=True)

    assert status == "refreshed"
    assert refreshed["curve"][-1]["balance"] == 250.0


def test_timeline_cache_discards_invalid_local_json_and_rebuilds(tmp_path: Path) -> None:
    cache = KlineTimelineCache(tmp_path)
    path = cache.path_for("302360", "MT5", "DBG MT5")
    path.write_text("not json", encoding="utf-8")

    replay, status = cache.get_or_build("302360", "MT5", "DBG MT5", lambda: _replay(88.0))

    assert status == "built"
    assert replay["curve"][-1]["balance"] == 88.0
