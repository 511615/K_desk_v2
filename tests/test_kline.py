from __future__ import annotations

import importlib.util
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from kdesk.application.kline_generation import missing_same_source_failure
from kdesk.domain.kline import (
    EndpointCheck,
    alignment_offsets,
    canonical_symbol,
    gap_segments,
    partial_result,
    split_indices_at_gaps,
    symbol_candidates,
    validation_metrics,
    validation_passes,
)
from kdesk.infrastructure.quote_sources import QuoteRoute, QuoteSource, QuoteSourceRegistry
from kdesk.worker.runner import Worker


def test_symbol_candidates_handle_suffixes_roll_and_ut100_alias() -> None:
    available = ["XAUUSD", "XAUUSD.ECN", "NAS100Roll", "NAS100Roll.PRO", "AUS200Roll"]

    assert canonical_symbol("XAUUSD.PRO") == "XAUUSD"
    assert canonical_symbol("XAUUSD.G") == "XAUUSD"
    assert canonical_symbol("XAUUSD.P") == "XAUUSD"
    assert symbol_candidates("XAUUSD.G", available)[:2] == ["XAUUSD", "XAUUSD.ECN"]
    assert canonical_symbol("NAS100Roll.ECN") == "NAS100"
    assert symbol_candidates("UT100.E", available)[:2] == ["NAS100Roll", "NAS100Roll.PRO"]


def test_quote_source_route_orders_preferred_before_explicit_fallback() -> None:
    preferred = QuoteSource("same", "same.exe", servers=("AC-Live",))
    fallback = QuoteSource("fallback", "fallback.exe")
    registry = QuoteSourceRegistry(
        [preferred, fallback],
        [QuoteRoute("MT5", "AC-Live", ("same",), ("fallback",))],
    )

    assert [(source.id, is_fallback) for source, is_fallback in registry.candidates("MT5", "AC-Live")] == [
        ("same", False),
        ("fallback", True),
    ]
    assert registry.candidates("MT5", "unknown") == []


def test_unscoped_legacy_default_is_universal_strict_fallback() -> None:
    default = QuoteSource("default", "terminal.exe")
    registry = QuoteSourceRegistry([default], [])

    assert registry.candidates("MT5", "DBG GB MT5") == [(default, True)]
    assert registry.candidates("MT5", "") == [(default, False)]
    assert registry.provider_summary() == [{"id": "default", "servers": [], "platforms": []}]


def test_missing_same_source_failure_is_actionable_and_structured() -> None:
    failure = missing_same_source_failure(
        "XAUUSD.G",
        platform="MT5",
        server="DBG GB MT5",
        configured_providers=[{"id": "default", "servers": [], "platforms": []}],
    )

    assert failure["stage"] == "source"
    assert failure["code"] == "NO_SAME_SOURCE_PROVIDER"
    assert failure["quoteSources"] == []
    assert failure["metrics"]["requestedServer"] == "DBG GB MT5"
    assert failure["metrics"]["configuredProviders"][0]["id"] == "default"
    assert "KDESK_KLINE_QUOTE_SOURCES" in failure["reason"]


def test_fallback_source_uses_harder_acceptance_gate() -> None:
    checks = [EndpointCheck(True, 0, 1) for _ in range(3)] + [EndpointCheck(False, 1.5, 1) for _ in range(2)]
    metrics = validation_metrics(checks)

    assert metrics["insideRatio"] == 0.6
    assert validation_passes(metrics, fallback=False)
    assert not validation_passes(metrics, fallback=True)

    all_tolerated = validation_metrics([EndpointCheck(True, 0, 1), EndpointCheck(False, 0.5, 1)])
    assert validation_passes(all_tolerated, fallback=True)


def test_gmt_expansion_only_runs_after_initial_low_confidence() -> None:
    assert alignment_offsets(True) == (0, -3)
    assert alignment_offsets(False)[:2] == (0, -3)
    assert set(alignment_offsets(False)) == set(range(-4, 5))


def test_low_confidence_quotes_are_rejected() -> None:
    btc_like = validation_metrics([EndpointCheck(False, 9.65, 1) for _ in range(10)])
    xag_like = validation_metrics([EndpointCheck(True, 0, 1), EndpointCheck(False, 3, 1)])
    audcad_like = validation_metrics([EndpointCheck(False, 2.1, 1) for _ in range(8)])

    assert not validation_passes(btc_like, fallback=False)
    assert not validation_passes(xag_like, fallback=False)
    assert not validation_passes(audcad_like, fallback=False)


def test_partial_result_keeps_successful_symbols() -> None:
    result = partial_result(
        [{"symbol": "XAUUSD", "validationStatus": "accepted"}],
        [{"symbol": "AUDCAD", "stage": "calibration", "code": "LOW_CONFIDENCE"}],
        [{"id": "same", "readOnly": True}],
    )

    assert result["partial"] is True
    assert result["symbols"][0]["symbol"] == "XAUUSD"
    assert result["failures"][0]["code"] == "LOW_CONFIDENCE"


def test_gap_detection_and_segmentation_preserve_weekend_boundaries() -> None:
    start = datetime(2026, 7, 17, 20, 0)
    times = [start, start + timedelta(minutes=1), start + timedelta(minutes=2947), start + timedelta(minutes=2948)]

    gaps = gap_segments(times)

    assert len(gaps) == 1
    assert gaps[0]["minutes"] == 2946
    assert gaps[0]["closed"] is True
    assert split_indices_at_gaps(times) == [(0, 2), (2, 4)]


def test_chart_preserves_white_workspace_and_embeds_gap_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    builder = (root / "legacy" / "tools" / "trade_kline_tool" / "build_enhanced_trade_kline_from_cache.py").read_text(encoding="utf-8")

    assert "background:#f5f6f8" in builder
    assert "ctx.fillStyle = '#fff'" in builder
    assert 'id="hideGaps" class="active"' in builder
    assert 'id="showGaps"' in builder
    assert "configured_price_correction" in builder
    assert "const isBuy = t.Type === 'buy'" in builder
    assert "ctx.moveTo(xo, yo - 7)" in builder
    assert "ctx.moveTo(xo, yo + 7)" in builder
    assert "ctx.strokeRect(xc-5,yc-5,10,10)" in builder
    assert "function visibleIndexRange()" in builder
    assert "function nearestBarIndex(position)" in builder
    assert "function visibleGapMarkers(" in builder
    assert "const buckets = new Map()" not in builder
    assert "idx=bars.reduce((best" not in builder
    assert "gaps.filter(g =>" not in builder
    assert "setInputsFromView(s, e)" in builder
    assert "overflow-wrap:anywhere" in builder


def test_worker_reads_additive_kline_result() -> None:
    result = Worker._parse_kline_result(
        'progress\nKLINE_RESULT {"partial": true, "symbols": [{"symbol": "XAUUSD"}], "failures": []}\n'
    )

    assert result["partial"] is True
    assert result["symbols"][0]["symbol"] == "XAUUSD"


def test_production_launcher_uses_dedicated_quote_terminal_with_override() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_prod.ps1").read_text(encoding="utf-8")

    assert "KDESK_KLINE_QUOTE_TERMINAL" in launcher
    assert r"D:\risk\mt5_backtest_terminal\terminal64.exe" in launcher
    assert "$env:TRADE_KLINE_TERMINAL" in launcher


def test_timeline_feature_embeds_factual_balance_credit_replay_and_event_table() -> None:
    root = Path(__file__).resolve().parents[1]
    tool_root = root / "legacy" / "tools" / "trade_kline_tool"
    spec = importlib.util.spec_from_file_location("account_timeline_features", tool_root / "account_timeline_features.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    html = '''<html><head><style></style></head><body>
<button id="panelPosition">仓位</button>
<div class="metric"><div class="k">占用保证金</div><div class="v" id="posMargin">-</div></div>
<div class="tableWrap" data-role="trades"><table id="tradeTable"></table></div>
<script>const DATA = {"account":"1"};
const canvas = document.getElementById('chart');</script></body></html>'''
    timeline = {
        "version": 1,
        "available": True,
        "openingState": {"timestamp": "2026-01-01 09:00:00", "balance": 1000, "credit": 10, "known": True},
        "summary": {"currency": "USD", "eventCount": 1, "allEventCount": 1},
        "events": [{"timestamp": "2026-01-01 10:00:00", "kind": "deposit"}],
        "curve": [{"timestamp": "2026-01-01 10:00:00", "balance": 1100, "credit": 10}],
        "liquidationPoints": [],
    }

    result = module.inject_account_timeline(html, timeline)

    assert '"accountTimeline"' in result
    assert 'id="panelFunds"' in result
    assert '资金与订单事件' in result
    assert 'posFundingFact' in result
    assert '历史保证金率没有平台盘中快照，未展示估算比例' in result
    assert 'build_position_fused_trade_kline_demo' not in (tool_root / "fused_trade_kline_features.py").read_text(encoding="utf-8")
    node = shutil.which("node")
    if node:
        scripts = __import__("re").findall(r"<script>([\s\S]*?)</script>", result)
        check = subprocess.run(
            [node, "-e", "new Function(process.argv[1]);", "\n".join(scripts)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert check.returncode == 0, check.stderr


def test_database_kline_timeline_is_opt_in_and_reuses_a_full_history_cache() -> None:
    root = Path(__file__).resolve().parents[1]
    legacy = (root / "legacy" / "apps" / "problem_account_registry" / "app.py").read_text(encoding="utf-8")
    api = (root / "src" / "kdesk" / "api" / "account_app.py").read_text(encoding="utf-8")
    worker = (root / "src" / "kdesk" / "worker" / "runner.py").read_text(encoding="utf-8")

    assert "KlineTimelineCache(KLINE_TIMELINE_CACHE_DIR).get_or_build" in legacy
    assert '"includeTimeline": payload_bool(payload.get("includeTimeline"))' in legacy
    assert '"refreshTimelineCache": payload_bool(payload.get("refreshTimelineCache"))' in legacy
    assert "if timeline_path is not None:" in legacy
    assert 'id="includeTimeline"' in legacy
    assert "时间留空即按所选账号和品种的全量历史生成" in legacy
    assert '"includeTimeline": _payload_bool(payload, "includeTimeline", False)' in api
    assert '"refreshTimelineCache": _payload_bool(payload, "refreshTimelineCache", False)' in api
    assert '"includeTimeline", "refreshTimelineCache"' in worker
