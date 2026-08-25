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
    assert "host.appendChild(markerHost)" in html
    assert "host.parentElement.insertBefore(markerHost,host.nextSibling)" not in html
    assert "border-left:4px solid transparent" in html
    assert "border-bottom-color:#101b2c" in html
    assert "filter:drop-shadow(0 0 1px #e5f2ff)" in html
    assert "profitZero" in html
    assert "base:0" in html
    assert "minValue:-profitMaxAbs" in html
    assert "stroke-dasharray','5 4'" in html
    assert "rgba(192,145,255,${alpha})" in html
    assert "const halo=document.createElementNS" not in html
    assert ".holdingOverlay{z-index:20" in html
    assert ".tradeMarkers{z-index:21}" in html
    assert "return Math.max(0,Math.min(bars.length-1,hi))" in html
    assert "MetaTrader5" not in html


def test_lightweight_renderer_embeds_quote_and_trade_payload():
    trades, bars, mapping = _fixture()
    replay = {"fields": ["openTime"], "rows": [["2026-08-20 10:00:00"]], "seriesBySymbol": {"EURUSD": [["2026-08-20 10:00:00", 1, 0.1]]}}
    html = build_lightweight_html("10001", "10001_demo", trades, bars, mapping, timeline={"events": [], "curve": []}, account_replay=replay)
    assert '"EURUSD"' in html
    assert '"Ticket":1' in html
    assert '"events":[]' in html
    assert '"accountReplay":{"fields":["openTime"]' in html


def test_lightweight_renderer_uses_account_replay_for_the_all_product_position_panel():
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_all_products", trades, bars, mapping)

    assert "const accountReplay=DATA.accountReplay||{}" in html
    assert "function accountOpenRowsAt(at)" in html
    assert "function accountFundsAt(at)" in html
    assert "accountReplay.seriesBySymbol?.[symbol]||[]" in html
    assert "全账户仓位" in html


def test_lightweight_renderer_values_all_product_positions_from_execution_contracts_and_quotes():
    trades, bars, mapping = _fixture()
    replay = {
        "fields": ["openTime", "closeTime", "ticket", "symbol", "type", "volume", "openPrice", "isOpen", "contractSize", "profitRate", "marginRate"],
        "rows": [["2026-08-20 10:00:00", "2026-08-20 10:03:00", "GOLD-1", "XAUUSD", "sell", 0.04, 4589.26, False, 100, 1, 1]],
        "seriesBySymbol": {"EURUSD": [["2026-08-20 10:00:00", 1, 0.04]]},
        "valuation": {
            "accountCurrency": "USD",
            "leverage": 500,
            "quoteBarsBySymbol": {"XAUUSD": [["2026-08-20 10:00:00", 4627.06]]},
            "symbolSpecs": {"XAUUSD": {"contractSize": 100, "profitCurrency": "USD", "marginCurrency": "USD", "calcMode": 4}},
        },
    }
    html = build_lightweight_html("10001", "10001_valued_positions", trades, bars, mapping, account_replay=replay)

    assert "function accountPositionValuation(at,open)" in html
    assert "function quoteAt(symbol,at)" in html
    assert "contractSize" in html
    assert "mode===4" in html
    assert "浮动盈亏" in html
    assert "DATA.positionMeta?.leverage)||500" not in html
    assert "initialBalance)||10000" not in html


def test_lightweight_renderer_calculates_a_portfolio_risk_boundary_without_guessing_stop_out():
    """A multi-product replay must expose its computed price stress boundary.

    The group stop-out percentage is not exported by this read-only source, so
    the renderer must label the zero-equity boundary instead of inventing a
    broker threshold.  The client calculation remains timestamp-specific and
    uses the same per-row valuation inputs as floating P/L and margin.
    """
    trades, bars, mapping = _fixture()
    replay = {
        "fields": ["openTime", "closeTime", "ticket", "symbol", "type", "volume", "openPrice", "isOpen", "contractSize", "profitRate", "marginRate"],
        "rows": [["2026-08-20 10:00:00", "", "XAU-1", "XAUUSD", "buy", 1, 4500, True, 100, 1, 1]],
        "valuation": {
            "accountCurrency": "USD",
            "leverage": 500,
            "riskBoundaryMode": "equity_zero",
            "riskBoundaryNote": "账户组强平阈值未导出；按权益归零压力价计算。",
            "quoteBarsBySymbol": {"XAUUSD": [["2026-08-20 10:00:00", 4600]]},
            "symbolSpecs": {"XAUUSD": {"contractSize": 100, "profitCurrency": "USD", "calcMode": 4}},
        },
    }

    html = build_lightweight_html("10001", "10001_risk_boundary", trades, bars, mapping, account_replay=replay)

    assert 'id="posRiskBoundary"' in html
    assert "function accountRiskBoundaries(valuation,equity)" in html
    assert "mode==='equity_zero'" in html
    assert "权益归零压力价" in html
    assert "账户组强平阈值未导出" in html


def test_lightweight_renderer_labels_the_all_product_position_pane_in_place():
    """The lower position lines must be self-explanatory without scrolling."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_position_labels", trades, bars, mapping)

    assert 'id="positionPaneLegend"' in html
    assert "蓝：全账户持仓笔数" in html
    assert "黄：全账户总手数" in html
    assert "组合风险边界（权益归零压力价）" in html
    assert "$('positionPaneLegend').hidden=panel!=='position'" in html
    assert "仓位使用率" not in html


def test_lightweight_renderer_keeps_current_positions_open_at_the_latest_quote():
    trades, bars, mapping = _fixture()
    trades.loc[0, "Is Open"] = True
    html = build_lightweight_html("10001", "10001_current", trades, bars, mapping)

    assert "function isOpen(t)" in html
    assert "function tradeEndIndex(t)" in html
    assert "isOpen(t)?bars.length-1" in html
    assert "持仓中" in html
    assert "rows.filter(t=>!isOpen(t))" in html


def test_lightweight_renderer_orders_same_minute_by_their_second_and_draws_overlay_lines():
    trades, bars, mapping = _fixture()
    trades.loc[0, "Open Time"] = pd.Timestamp("2026-08-20 10:00:05")
    trades.loc[0, "Close Time"] = pd.Timestamp("2026-08-20 10:00:52")
    html = build_lightweight_html("10001", "10001_seconds", trades, bars, mapping)

    assert "function intraMinuteFraction(t)" in html
    assert "function tradeX(t,endpoint)" in html
    assert "const holdingOverlay=document.createElementNS" in html
    assert "intraMinuteFraction(t['Open Time'])" in html
    assert "intraMinuteFraction(t['Close Time'])" in html
    assert "positionTradeMarkers(candle,rows)" in html


def test_lightweight_renderer_batches_only_visible_trade_overlays_while_panning():
    """Dense order history must not rebuild one DOM node per order for every pan event."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_performance", trades, bars, mapping)

    assert "const OVERLAY_DRAG_INTERVAL_MS=50" in html
    assert "function visibleOverlayRows(rows)" in html
    assert "const holdingPath=document.createElementNS" in html
    assert "const openMarkerPath=document.createElementNS" in html
    assert "holdingPath.setAttribute('d',segments.join(''))" in html
    assert "openMarkerPath.setAttribute('d',openSegments.join(''))" in html
    assert "function scheduleOverlayRefresh(settled=false)" in html
    assert "scheduleOverlayRefresh();scheduleSettledOverlayRefresh()" in html


def test_lightweight_renderer_allows_the_full_generated_kline_range():
    """Zooming out must follow the legacy full-axis rule rather than stop at a pixel floor."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_zoom", trades, bars, mapping)

    assert "minBarSpacing:.01" in html


def test_lightweight_renderer_keeps_bar_pane_and_time_axis_compact():
    """The lower indicator and time labels should not dominate the vertical layout."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_compact_height", trades, bars, mapping)

    assert ".chartStage{position:relative;height:620px}" in html
    assert ".chartShell>.chart{height:620px}" in html
    assert ".chartShell>.tradeMarkers{height:620px" in html
    assert "minimumHeight:24" in html
    assert "chart.panes()[1].setStretchFactor(.6)" in html


def test_lightweight_renderer_formats_compact_time_axis_from_quote_timestamps():
    """Compressed trading time must label quotes, never the synthetic 2000 anchor."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_compact_time_labels", trades, bars, mapping)

    assert "tickMarkFormatter:axisTickMarkFormatter" in html
    assert "function axisTickMarkFormatter" in html
    assert "compactTimes.length" in html
    assert "bars[index]?.time" in html
    assert "localization:{timeFormatter:chartTimeFormatter}" in html
    assert "function chartTimeFormatter(time)" in html
    assert "return raw||axisTickMarkFormatter(value)" in html

def test_lightweight_renderer_draws_dynamic_bars_with_a_fixed_minimum_width():
    """Dense chart intervals retain readable lower-pane bars while panning and zooming."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_readable_bars", trades, bars, mapping)

    assert "PANEL_BAR_MIN_WIDTH=8" in html
    assert "PANEL_BAR_MAX_WIDTH=18" in html
    assert "function panelBarWidth" in html
    assert "function paintPanelBars" in html
    assert "function panelPaneGeometry" in html
    assert "PANEL_PANE_SEPARATOR_HEIGHT=4" in html
    assert "top=panes.slice(0,paneIndex).reduce((sum,item)=>sum+n(item.getHeight?.()),0)+paneIndex*PANEL_PANE_SEPARATOR_HEIGHT" in html
    assert "function refreshInteractiveOverlays(){refreshTradeMarkers();schedulePanelBars()}" in html
    assert "host.addEventListener('pointermove',refreshInteractiveOverlays)" in html
    assert "host.addEventListener('pointerup',refreshInteractiveOverlays)" in html
    assert "base+geometry.top" in html
    assert "y+geometry.top" in html
    assert "panelBarClip" in html
    assert "function axisTickMarkFormatter(time,tickMarkType)" in html
    assert "if(index<=0)return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}`" in html
    assert "if(date.getHours()===0&&date.getMinutes()===0)return `${pad(date.getMonth()+1)}-${pad(date.getDate())}`" in html
    assert "return `${pad(date.getHours())}:${pad(date.getMinutes())}`" in html
    assert "priceScaleId:'profit',base:0,lastValueVisible:false,priceLineVisible:false" in html
    assert "priceScale:{visible:true,scaleMargins:{top:.15,bottom:.15}}" in html
    assert "chart.priceScale('profit').applyOptions({visible:true})" in html
    assert "priceScaleId:'volume',lastValueVisible:false,priceLineVisible:false" in html
    assert "panelSeries.profitZero?.priceToCoordinate(0)??active.priceToCoordinate(0)" in html
    assert "panelSeries={profit,profitZero,volume}" in html
    assert "const NATIVE_PANEL_BAR_COLOR='rgba(0,0,0,0)'" in html
    assert "closeMarkerPath.setAttribute('fill','#ff6575')" in html
    assert html.count("color:NATIVE_PANEL_BAR_COLOR") == 2


def test_lightweight_renderer_keeps_profit_axis_and_crosshair_value_in_the_price_scale_gutter():
    """Profit values share the right price-axis position and crosshair exposes the exact value."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_profit_crosshair_axis", trades, bars, mapping)

    assert "const PROFIT_AXIS_X_OFFSET=5" in html
    assert "String(rect.width-PROFIT_AXIS_X_OFFSET)" in html
    assert "function updateProfitCrosshair(param)" in html
    assert "function profitAxisValueFromCoordinate(paneY)" in html
    assert "profitAxisGeometry={maximum:axisMax,zero:base,positive:active.priceToCoordinate(axisMax),negative:active.priceToCoordinate(-axisMax)}" in html
    assert "profitAxisValueFromCoordinate(paneY)" in html
    assert "chart.subscribeCrosshairMove(updateProfitCrosshair)" in html
    assert "chart.subscribeClick(updateProfitCrosshair)" in html
    assert "function updateProfitCrosshairFromPointer(event)" in html
    assert "event.clientY-host.getBoundingClientRect().top-geometry.top" in html
    assert "host.addEventListener('pointerdown',updateProfitCrosshairFromPointer)" in html
    assert "profitCrosshairValue" in html


def test_lightweight_renderer_uses_profit_stack_mode_for_overlay_axis_and_crosshair():
    """The Profit overlay must retain individual values unless its control says merged."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_profit_stack_mode", trades, bars, mapping)

    assert "function profitPanelBars(rows)" in html
    assert "barStack?groupProfitBars(rows):rows.map" in html
    assert "const rows=panel==='profit'?profitPanelBars(filtered().filter(t=>!isOpen(t)).slice(0,Math.max(1,n($('displayLimit').value)||300))):groupVolumeBars" in html
    assert "const profitValues=profitPanelBars(closedRows)" in html


def test_lightweight_renderer_loads_its_chart_library_from_the_local_account_service():
    """The direct account chart must not require the browser to reach a public CDN."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_local_lightweight_charts", trades, bars, mapping)

    assert '<script src="/vendor/lightweight-charts-5.0.8.js"></script>' in html
    assert "https://unpkg.com/lightweight-charts" not in html


def test_lightweight_renderer_reports_its_document_height_when_embedded():
    """An inline chart expands in the account page instead of adding an iframe scrollbar."""
    trades, bars, mapping = _fixture()
    html = build_lightweight_html("10001", "10001_embedded_height", trades, bars, mapping)

    assert "kdesk-inline-kline-height" in html
    assert "window.parent!==window" in html
    assert "ResizeObserver" in html
