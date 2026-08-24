from __future__ import annotations

import pandas as pd

from legacy.tools.trade_kline_tool.lightweight_trade_kline import build_lightweight_html


def _fixture() -> tuple[pd.DataFrame, dict, dict]:
    trades = pd.DataFrame(
        [
            {
                "Ticket": 1,
                "Item": "EURUSD",
                "Type": "buy",
                "Volume": 0.1,
                "Open Time": pd.Timestamp("2026-08-20 10:00:00"),
                "Close Time": pd.Timestamp("2026-08-20 10:03:00"),
                "Open Price": 1.1,
                "Close Price": 1.101,
                "Open Plot Price": 1.1,
                "Close Plot Price": 1.101,
                "Profit": 10.0,
                "Commission": -1.0,
                "Swap": 0.0,
                "Taxes": 0.0,
                "Comment": "demo",
                "Holding Seconds": 180,
            }
        ]
    )
    bars = pd.DataFrame(
        [
            {"time": f"2026-08-20 10:0{i}:00", "open": 1.1, "high": 1.102, "low": 1.099, "close": 1.101, "tick_volume": 20}
            for i in range(6)
        ]
    )
    return trades, {"EURUSD": bars}, {"EURUSD": {"mt5_symbol": "EURUSD", "provider": "cache", "time_mode": "utc"}}


def test_lightweight_renderer_contains_native_series_and_compatibility_controls():
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_demo", trades, bars, mapping)
    assert "lightweight-charts" in html
    assert "CandlestickSeries" in html
    assert "createSeriesMarkers" not in html
    assert "panelPosition" in html
    assert "filterType" in html
    assert "windowStart" in html
    assert "accountTimelineData" in html
    assert "hideGaps" in html
    assert "showGaps" in html
    assert "买入开仓 ▲" in html
    assert "卖出开仓 ▼" in html
    assert "开 ${t.Ticket" not in html
    assert "平 ${t.Ticket" not in html
    assert "'S/L'" in html
    assert "'T/P'" in html
    assert 'id="hideGaps"' in html
    assert 'id="showGaps"' in html
    assert 'id="displayLimit"' in html
    assert "#061322" in html
    assert "#071b31" in html
    assert "shownAvgHold" in html
    assert "groupProfitBars" in html
    assert "subscribeVisibleLogicalRangeChange" in html
    assert "priceToCoordinate" in html
    assert "tradeMarkers" in html
    assert "border-left:4px solid transparent" in html
    assert "border-bottom-color:#101b2c" in html
    assert "filter:drop-shadow(0 0 1px #e5f2ff)" in html
    assert "profitZero" in html
    assert "minValue:-profitMaxAbs" in html
    assert "rgba(192,145,255,${alpha})" in html
    assert "Math.abs(ms(bars[right].time)-x)" in html
    assert "MetaTrader5" not in html


def test_lightweight_renderer_embeds_quote_and_trade_payload():
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_demo", trades, bars, mapping, timeline={"events": [], "curve": []})
    assert '"EURUSD"' in html
    assert '"Ticket":1' in html
    assert '"events":[]' in html
