from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd
from fused_trade_kline_features import enhance_trade_kline_html


def quote_gaps(bars: pd.DataFrame) -> list[dict]:
    times = pd.to_datetime(bars["time"]).sort_values().reset_index(drop=True)
    gaps = []
    for index in range(len(times) - 1):
        minutes = (times.iloc[index + 1] - times.iloc[index]).total_seconds() / 60
        if minutes <= 5:
            continue
        gaps.append(
            {
                "afterIndex": index,
                "before": times.iloc[index].strftime("%Y-%m-%d %H:%M:%S"),
                "after": times.iloc[index + 1].strftime("%Y-%m-%d %H:%M:%S"),
                "minutes": round(minutes, 3),
                "closed": minutes > 60,
            }
        )
    return gaps


PROJECT_ROOT = Path(os.environ.get("K_DESK_ROOT", Path(__file__).resolve().parents[2]))
LEGACY_RISK_ROOT = Path(r"D:\risk")
DEFAULT_OUT_DIR = LEGACY_RISK_ROOT / "output_data" if LEGACY_RISK_ROOT.exists() else PROJECT_ROOT / "outputs" / "kline"
OUT_DIR = Path(os.environ.get("TRADE_KLINE_OUT_DIR", DEFAULT_OUT_DIR))
MAX_HTML_BARS_PER_SYMBOL = 30000
PRESERVE_TRADE_WINDOW_MINUTES = 60


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def infer_stem(trades_csv: Path) -> str:
    name = trades_csv.name
    suffix = "_trades.csv"
    if not name.endswith(suffix):
        raise ValueError(f"trades csv must end with {suffix}: {trades_csv}")
    return name[: -len(suffix)]


def load_bars_for_symbol(out_dir: Path, stem: str, report_symbol: str, mapping: dict) -> pd.DataFrame:
    mt5_symbol = mapping["mt5_symbol"]
    time_mode = mapping["time_mode"]
    exact = out_dir / f"{stem}_{safe_name(report_symbol)}_quote_cache_{safe_name(mt5_symbol)}_M1_{time_mode}.csv"
    if exact.exists():
        return pd.read_csv(exact, parse_dates=["time"])

    candidates = sorted(out_dir.glob(f"{stem}_*quote_cache*{safe_name(mt5_symbol)}*M1*{time_mode}*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No M1 quote cache for {report_symbol} / {mt5_symbol} / {time_mode}")
    return pd.read_csv(candidates[0], parse_dates=["time"])


def aggregate_bars_by_position(bars: pd.DataFrame, target_rows: int) -> pd.DataFrame:
    if target_rows <= 0 or bars.empty:
        return bars.iloc[0:0].copy()
    if len(bars) <= target_rows:
        return bars.copy()
    ordered = bars.sort_values("time").reset_index(drop=True).copy()
    ordered["_segment"] = (pd.to_datetime(ordered["time"]).diff().dt.total_seconds().fillna(0) > 5 * 60).cumsum()
    parts = []
    for _, segment in ordered.groupby("_segment", sort=True):
        budget = max(1, round(target_rows * len(segment) / len(ordered)))
        step = max(1, int(len(segment) / budget) + 1)
        tmp = segment.reset_index(drop=True).copy()
        tmp["_bucket"] = tmp.index // step
        parts.append(
            tmp.groupby("_bucket", sort=True)
            .agg(
                time=("time", "first"),
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                tick_volume=("tick_volume", "sum"),
            )
            .reset_index(drop=True)
        )
    return pd.concat(parts, ignore_index=True).sort_values("time").reset_index(drop=True)


def bars_for_html(bars: pd.DataFrame, trades_for_symbol: pd.DataFrame) -> pd.DataFrame:
    """Keep local CSV caches full-size, but embed a display-sized OHLC series in HTML."""
    if len(bars) <= MAX_HTML_BARS_PER_SYMBOL:
        return bars.copy()
    b = bars.sort_values("time").reset_index(drop=True).copy()
    b["time"] = pd.to_datetime(b["time"])

    def preserve_mask(window_minutes: int) -> pd.Series:
        mask = pd.Series(False, index=b.index)
        pad = pd.Timedelta(minutes=window_minutes)
        for col in ["Open Time", "Close Time"]:
            if col not in trades_for_symbol.columns:
                continue
            for ts in pd.to_datetime(trades_for_symbol[col], errors="coerce").dropna():
                mask |= b["time"].between(ts - pad, ts + pad)
        return mask

    mask = preserve_mask(PRESERVE_TRADE_WINDOW_MINUTES)
    if int(mask.sum()) > int(MAX_HTML_BARS_PER_SYMBOL * 0.75):
        mask = preserve_mask(20)
    if int(mask.sum()) > int(MAX_HTML_BARS_PER_SYMBOL * 0.85):
        mask = preserve_mask(5)

    kept = b.loc[mask, ["time", "open", "high", "low", "close", "tick_volume"]]
    budget = max(1000, MAX_HTML_BARS_PER_SYMBOL - len(kept))
    rest = b.loc[~mask, ["time", "open", "high", "low", "close", "tick_volume"]]
    rest_agg = aggregate_bars_by_position(rest, budget)
    out = (
        pd.concat([kept, rest_agg], ignore_index=True)
        .drop_duplicates(subset=["time"], keep="first")
        .sort_values("time")
        .reset_index(drop=True)
    )
    if len(out) > MAX_HTML_BARS_PER_SYMBOL:
        out = aggregate_bars_by_position(out, MAX_HTML_BARS_PER_SYMBOL)
    print(f"html bars compressed: {len(bars)} -> {len(out)}")
    return out


def add_plot_prices(trades: pd.DataFrame, bars_by_symbol: dict) -> pd.DataFrame:
    out = trades.copy()
    out["Open Plot Price"] = out["Open Price"]
    out["Close Plot Price"] = out["Close Price"]
    return out


def account_meta_from_trades(trades: pd.DataFrame) -> dict:
    def first_value(col: str, default=None):
        if col not in trades.columns:
            return default
        vals = trades[col].dropna()
        if vals.empty:
            return default
        return vals.iloc[0]

    currency = str(first_value("Account Currency", "") or "").upper()
    display_currency = str(first_value("Display Currency", currency) or currency).upper()
    try:
        money_scale = float(first_value("Money Scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        money_scale = 1.0
    raw_cent = first_value("Is Cent Account", False)
    is_cent = str(raw_cent).strip().lower() in {"true", "1", "yes"} if isinstance(raw_cent, str) else bool(raw_cent)
    note = str(first_value("Money Unit Note", "") or "")
    return {
        "currency": currency,
        "displayCurrency": display_currency,
        "moneyScale": money_scale,
        "isCentAccount": is_cent,
        "note": note,
    }


def find_statement_for_stem(out_dir: Path, account: str) -> Path | None:
    patterns = [
        f"ReportHistory-{account}.html",
        f"ReportHistory-{account}.htm",
        f"ReportHistory_{account}.html",
        f"ReportHistory_{account}.htm",
        f"Statement_{account}.html",
        f"Statement_{account}.htm",
        f"Statement-{account}.html",
        f"Statement-{account}.htm",
    ]
    for name in patterns:
        path = out_dir / name
        if path.exists():
            return path
    uploaded = out_dir / "uploaded_statements"
    if uploaded.exists():
        candidates = sorted(uploaded.glob(f"*{account}*.htm*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return None


def apply_display_price_alignment(report_symbol: str, bars: pd.DataFrame, trades_for_symbol: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    shift = float(mapping.get("configured_price_correction") or 0.0)
    mapping["display_price_shift"] = shift
    mapping["display_price_shift_applied"] = bool(shift)
    mapping["display_price_shift_source"] = "quote-source configuration" if shift else "none"
    if not shift:
        return bars
    out = bars.copy()
    for col in ["open", "high", "low", "close"]:
        out[col] = out[col].astype(float) + shift
    print(f"{report_symbol}: applied configured price correction {shift:.8f}")
    return out


def build_html(account: str, stem: str, trades: pd.DataFrame, bars_by_symbol: dict, mapping_by_symbol: dict) -> str:
    chart_trades = add_plot_prices(trades, bars_by_symbol)
    for col in chart_trades.columns:
        if pd.api.types.is_datetime64_any_dtype(chart_trades[col]):
            chart_trades[col] = chart_trades[col].dt.strftime("%Y-%m-%d %H:%M:%S")

    bars_json = {}
    gaps_json = {}
    for sym, bars in bars_by_symbol.items():
        symbol_trades = trades[trades["Item"] == sym] if "Item" in trades.columns else trades.iloc[0:0]
        b = bars_for_html(bars, symbol_trades)
        gaps_json[sym] = quote_gaps(b)
        gap_after = {item["afterIndex"] for item in gaps_json[sym]}
        segment = 0
        segments = []
        for index in range(len(b)):
            segments.append(segment)
            if index in gap_after:
                segment += 1
        b["segment"] = segments
        b["time"] = pd.to_datetime(b["time"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        bars_json[sym] = b[["time", "open", "high", "low", "close", "tick_volume", "segment"]].to_dict(orient="records")

    payload = {
        "account": account,
        "stem": stem,
        "accountMeta": account_meta_from_trades(chart_trades),
        "barsBySymbol": bars_json,
        "gapsBySymbol": gaps_json,
        "trades": chart_trades.where(pd.notna(chart_trades), None).to_dict(orient="records"),
        "mappingBySymbol": mapping_by_symbol,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>{stem} 买卖点K线图</title>
<style>
body {{ margin:0; font-family: Arial, "Microsoft YaHei", sans-serif; background:#f5f6f8; color:#1f2937; }}
header {{ padding:14px 20px; background:#111827; color:#fff; }}
h1 {{ margin:0 0 8px; font-size:20px; overflow-wrap:anywhere; }}
.meta {{ display:flex; flex-wrap:wrap; gap:10px 22px; font-size:13px; color:#d1d5db; }}
.toolbar {{ display:flex; align-items:center; gap:8px; padding:12px 18px 6px; flex-wrap:wrap; }}
select, button, input {{ border:1px solid #cbd5e1; background:#fff; color:#111827; padding:7px 10px; border-radius:4px; }}
button {{ cursor:pointer; }}
button:hover {{ background:#f1f5f9; }}
label {{ display:inline-flex; align-items:center; gap:5px; }}
.filters {{ display:flex; align-items:center; gap:8px; padding:6px 18px 10px; flex-wrap:wrap; border-bottom:1px solid #e5e7eb; }}
.filters input {{ width:82px; padding:6px 7px; }}
.filters select {{ padding:6px 7px; }}
.filters .filterTitle {{ color:#334155; font-weight:700; }}
.status {{ margin-left:auto; color:#4b5563; font-size:13px; }}
.wrap {{ padding:0 18px 22px; }}
.chartShell {{ position:relative; }}
#chart {{ display:block; width:100%; height:760px; background:#fff; border:1px solid #cbd5e1; cursor:grab; }}
#chart.dragging {{ cursor:grabbing; }}
.panelToggle {{ position:absolute; top:10px; right:12px; display:flex; gap:4px; background:rgba(255,255,255,0.9); border:1px solid #cbd5e1; padding:3px; }}
.panelToggle button {{ padding:4px 9px; border:0; background:transparent; font-size:12px; }}
.panelToggle button.active {{ background:#111827; color:#fff; }}
.chartHelp {{ margin-top:8px; background:#fff; border:1px solid rgba(203,213,225,0.95); padding:6px 8px; }}
.legend {{ display:flex; flex-wrap:wrap; gap:12px; font-size:13px; line-height:1.4; }}
.sw {{ width:12px; height:12px; display:inline-block; margin-right:5px; vertical-align:-1px; }}
.note {{ margin-top:3px; color:#4b5563; font-size:13px; line-height:1.35; }}
.summary {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:8px; margin-top:12px; }}
.metric {{ background:#fff; border:1px solid #e5e7eb; padding:10px 12px; }}
.metric .k {{ color:#64748b; font-size:12px; }}
.metric .v {{ margin-top:5px; font-size:18px; font-weight:700; color:#111827; }}
.windowControls {{ display:grid; grid-template-columns:1fr 1fr auto; gap:6px; margin-top:6px; align-items:center; }}
.windowControls input {{ width:100%; min-width:0; padding:6px 7px; font-size:12px; }}
.windowControls button {{ padding:6px 9px; white-space:nowrap; }}
.windowHint {{ margin-top:5px; color:#64748b; font-size:11px; }}
.tableWrap {{ overflow:auto; max-height:420px; border:1px solid #e5e7eb; background:#fff; margin-top:12px; }}
table {{ width:100%; border-collapse:collapse; background:#fff; font-size:12px; }}
th, td {{ border:1px solid #e5e7eb; padding:5px 7px; text-align:right; white-space:nowrap; }}
th {{ background:#eef2f7; position:sticky; top:0; z-index:1; }}
td.left, th.left {{ text-align:left; }}
@media (max-width: 900px) {{ .summary {{ grid-template-columns:repeat(1,minmax(150px,1fr)); }} .status {{ margin-left:0; width:100%; }} }}
.gapToggle {{ display:inline-flex; margin-left:4px; overflow:hidden; border:1px solid #cbd5e1; border-radius:4px; background:#fff; }}
.gapToggle button {{ border:0; border-radius:0; background:transparent; color:#64748b; }}
.gapToggle button.active {{ background:#111827; color:#fff; }}
@media (max-width:600px) {{ .wrap {{ padding:0 8px 18px; }} .toolbar,.filters {{ padding-left:8px; padding-right:8px; }} #chart {{ height:620px; }} }}
</style>
</head>
<body>
<header>
<h1>{stem} / 买卖点K线图</h1>
<div class="meta" id="meta"></div>
</header>
<div class="toolbar">
<select id="symbolSelect"></select>
<button id="zoomIn">放大</button>
<button id="zoomOut">缩小</button>
<button id="reset">重置</button>
<button class="fitTradesButton" id="fitTrades">只看交易区间</button>
<div class="gapToggle" aria-label="停盘时间轴">
<button id="hideGaps" class="active" type="button">隐藏停盘</button><button id="showGaps" type="button">显示停盘</button>
</div>
<label>显示订单 <input id="displayLimit" type="number" min="1" step="50" value="300" style="width:86px;"> 笔</label>
<span class="status" id="status"></span>
</div>
<div class="filters">
<span class="filterTitle">过滤</span>
<label>方向 <select id="filterType"><option value="">全部</option><option value="buy">buy</option><option value="sell">sell</option></select></label>
<label>手数 <input id="filterVolumeMin" type="number" step="0.01" placeholder="min"> - <input id="filterVolumeMax" type="number" step="0.01" placeholder="max"></label>
<label>Profit <input id="filterProfitMin" type="number" step="1" placeholder="min"> - <input id="filterProfitMax" type="number" step="1" placeholder="max"></label>
<label>持仓分钟 <input id="filterHoldMin" type="number" step="1" placeholder="min"> - <input id="filterHoldMax" type="number" step="1" placeholder="max"></label>
<button id="clearFilters">清空</button>
</div>
<div class="wrap">
<div class="chartShell">
<canvas id="chart"></canvas>
<div class="panelToggle">
<button id="panelProfit" class="active">Profit</button>
<button id="panelVolume">手数</button>
</div>
<div class="chartHelp">
<div class="legend">
<span><i class="sw" style="background:#16a34a"></i>买入开仓</span>
<span><i class="sw" style="background:#dc2626"></i>卖出开仓</span>
<span><i class="sw" style="background:#2563eb"></i>平仓</span>
<span><i class="sw" style="background:#7c3aed"></i>持仓连线</span>
<span><i class="sw" style="background:#ef4444"></i>盈利柱</span>
<span><i class="sw" style="background:#22c55e"></i>亏损柱</span>
<span><i class="sw" style="background:#3b82f6"></i>手数柱</span>
<span>右上角切换 Profit/手数；过滤条件会同步影响图上订单、表格和底部指标；滚轮缩放，按住拖动，双击重置；鼠标移动显示十字光标</span>
</div>
<div class="note">报价/K线缓存保存在 {OUT_DIR}；HTML 按 account + 时间范围命名。“显示订单”会同步控制图上点位、下方表格和盈亏柱状图。</div>
</div>
</div>
<div class="summary">
<div class="metric"><div class="k">当前显示订单</div><div class="v" id="shownCount">0</div></div>
<div class="metric"><div class="k">当前显示 Profit</div><div class="v" id="shownProfit">0.00</div></div>
<div class="metric"><div class="k">全量 Closed P/L</div><div class="v" id="totalClosedPL">0.00</div></div>
<div class="metric">
<div class="k">时间窗口</div>
<div class="windowControls">
<input id="windowStart" type="text" placeholder="YYYY-MM-DD HH:MM">
<input id="windowEnd" type="text" placeholder="YYYY-MM-DD HH:MM">
<button id="applyWindow">应用</button>
</div>
<div class="windowHint" id="windowLabel">输入时间后定位到该区间</div>
</div>
</div>
<div class="tableWrap"><table id="tradeTable"></table></div>
</div>
<script>
const DATA = {payload_json};
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
const metaEl = document.getElementById('meta');
const symbolSelect = document.getElementById('symbolSelect');
const displayLimitInput = document.getElementById('displayLimit');
const windowStartInput = document.getElementById('windowStart');
const windowEndInput = document.getElementById('windowEnd');
const filterTypeInput = document.getElementById('filterType');
const filterVolumeMinInput = document.getElementById('filterVolumeMin');
const filterVolumeMaxInput = document.getElementById('filterVolumeMax');
const filterProfitMinInput = document.getElementById('filterProfitMin');
const filterProfitMaxInput = document.getElementById('filterProfitMax');
const filterHoldMinInput = document.getElementById('filterHoldMin');
const filterHoldMaxInput = document.getElementById('filterHoldMax');
const hideGapsButton = document.getElementById('hideGaps');
const showGapsButton = document.getElementById('showGaps');
let symbol = Object.keys(DATA.barsBySymbol)[0];
let bars = [], trades = [], viewStart = 0, viewEnd = 1, drag = null, crosshair = null;
let barMinutes = [], firstBarMinute = 0;
let gaps = [], showRealGaps = false, noQuoteWindow = '';
let panelMode = 'profit';
let filteredTradesCache = null, filteredTradesCacheKey = '', lastTableKey = '';
let pendingDraw = null;

function minuteValue(time) {{ return new Date(String(time).replace(' ', 'T')).getTime() / 60000; }}
function locateTime(time) {{
  const key = String(time).slice(0,16);
  let lo = 0, hi = bars.length - 1;
  while (lo <= hi) {{
    const mid = (lo + hi) >> 1, bt = bars[mid].time.slice(0,16);
    if (bt === key) return {{index:mid, insertion:mid, missing:false, minute:minuteValue(time)}};
    if (bt < key) lo = mid + 1; else hi = mid - 1;
  }}
  return {{index:-1, insertion:lo, missing:true, minute:minuteValue(time)}};
}}
function axisMax() {{ return bars.length ? barPosition(bars.length - 1) : 1; }}
function barPosition(index) {{
  if (!showRealGaps) return index;
  return barMinutes[index] - firstBarMinute;
}}
function lowerBoundPosition(target) {{
  let lo = 0, hi = bars.length;
  while (lo < hi) {{ const mid = (lo + hi) >> 1; if (barPosition(mid) < target) lo = mid + 1; else hi = mid; }}
  return lo;
}}
function upperBoundPosition(target) {{
  let lo = 0, hi = bars.length;
  while (lo < hi) {{ const mid = (lo + hi) >> 1; if (barPosition(mid) <= target) lo = mid + 1; else hi = mid; }}
  return lo;
}}
function lowerBoundMinute(target) {{
  let lo = 0, hi = barMinutes.length;
  while (lo < hi) {{ const mid = (lo + hi) >> 1; if (barMinutes[mid] < target) lo = mid + 1; else hi = mid; }}
  return lo;
}}
function upperBoundMinute(target) {{
  let lo = 0, hi = barMinutes.length;
  while (lo < hi) {{ const mid = (lo + hi) >> 1; if (barMinutes[mid] <= target) lo = mid + 1; else hi = mid; }}
  return lo;
}}
function visibleIndexRange() {{
  if (!bars.length) return [0, -1];
  const start = Math.max(0, Math.min(bars.length - 1, lowerBoundPosition(viewStart)));
  const end = Math.max(start, Math.min(bars.length - 1, upperBoundPosition(viewEnd) - 1));
  return [start, end];
}}
function nearestBarIndex(position) {{
  if (!bars.length) return -1;
  const right = lowerBoundPosition(position);
  if (right <= 0) return 0;
  if (right >= bars.length) return bars.length - 1;
  return Math.abs(barPosition(right) - position) < Math.abs(barPosition(right - 1) - position) ? right : right - 1;
}}
function lowerBoundGapPosition(target) {{
  let lo = 0, hi = gaps.length;
  while (lo < hi) {{ const mid = (lo + hi) >> 1; if (Number(gaps[mid].afterIndex) + 0.5 < target) lo = mid + 1; else hi = mid; }}
  return lo;
}}
function upperBoundGapPosition(target) {{
  let lo = 0, hi = gaps.length;
  while (lo < hi) {{ const mid = (lo + hi) >> 1; if (Number(gaps[mid].afterIndex) + 0.5 <= target) lo = mid + 1; else hi = mid; }}
  return lo;
}}
function visibleGapMarkers(xScale, plotLeft, plotWidth) {{
  if (showRealGaps || !gaps.length) return [];
  const start = lowerBoundGapPosition(viewStart), end = upperBoundGapPosition(viewEnd);
  const visibleCount = Math.max(0, end - start);
  if (!visibleCount) return [];
  const bucketWidth = visibleCount > plotWidth / 6 ? 6 : 1;
  const markers = [];
  let group = null, groupKey = -1;
  for (let index = start; index < end; index++) {{
    const gap = gaps[index], position = Number(gap.afterIndex) + 0.5;
    const key = Math.floor((xScale(position) - plotLeft) / bucketWidth);
    if (key !== groupKey) {{
      if (group) markers.push(group);
      groupKey = key;
      group = {{...gap, positionSum: position, groupedCount: 1, closedCount: gap.closed ? 1 : 0}};
      continue;
    }}
    group.positionSum += position;
    group.groupedCount += 1;
    group.closedCount += gap.closed ? 1 : 0;
    if ((gap.closed && !group.closed) || (Boolean(gap.closed) === Boolean(group.closed) && Number(gap.minutes) > Number(group.minutes))) {{
      group.closed = gap.closed;
      group.minutes = gap.minutes;
    }}
  }}
  if (group) markers.push(group);
  return markers.map(marker => ({{...marker, position: marker.positionSum / marker.groupedCount}}));
}}
function tradePosition(location) {{
  if (showRealGaps) return location.minute - firstBarMinute;
  if (!location.missing) return location.index;
  return Math.max(-0.5, Math.min(bars.length - 0.5, location.insertion - 0.5));
}}
function setSymbol(sym) {{
  symbol = sym;
  bars = DATA.barsBySymbol[symbol] || [];
  barMinutes = bars.map(bar => minuteValue(bar.time));
  firstBarMinute = barMinutes[0] || 0;
  gaps = (DATA.gapsBySymbol || {{}})[symbol] || [];
  trades = DATA.trades.filter(t => t.Item === symbol).map(t => {{
    const openLocation = locateTime(t["Open Time"]), closeLocation = locateTime(t["Close Time"]);
    return {{...t, openLocation, closeLocation, openIdx:openLocation.index, closeIdx:closeLocation.index}};
  }});
  invalidateTradeCache();
  viewStart = 0; viewEnd = Math.max(1, axisMax());
  const m = DATA.mappingBySymbol[symbol] || {{}};
  const am = DATA.accountMeta || {{}};
  const currencyText = am.isCentAccount
    ? `币种：${{am.currency}} 美分账户，金额已按 ${{am.displayCurrency || 'USD'}} 口径显示`
    : (am.currency ? `币种：${{am.currency}}` : '');
  const correction = Number(m.configured_price_correction || 0);
  metaEl.innerHTML = `<span>账户：${{DATA.account}}</span>${{currencyText ? `<span>${{currencyText}}</span>` : ''}}<span>品种：${{symbol}} -> ${{m.mt5_symbol || ''}}</span><span>报价源：${{m.provider || 'legacy'}} / ${{m.provider_server || '-'}}</span><span>时间判断：${{m.time_mode || ''}}</span><span>查询偏移：${{m.hour_delta ?? ''}}小时</span><span>置信度：${{m.confidence == null ? '-' : (Number(m.confidence) * 100).toFixed(1) + '%'}}</span>${{correction ? `<span>配置价格修正：${{correction}}</span>` : ''}}<span>停盘段：${{gaps.filter(g=>g.closed).length}}</span><span>订单数：${{trades.length}}</span>`;
  fitTrades();
}}
function displayLimit() {{ return Math.max(1, Number(displayLimitInput.value) || 300); }}
function parseTimeInput(value) {{
  const text = String(value || '').trim();
  if (!text) return null;
  return (text.length === 16 ? text + ':00' : text).replace('T', ' ');
}}
function setInputsFromView(startIndex=null, endIndex=null) {{
  if (!bars.length) return;
  const range = startIndex == null || endIndex == null ? visibleIndexRange() : [startIndex, endIndex];
  const s = range[0], e = range[1];
  if (e < s) return;
  windowStartInput.value = bars[s].time.slice(0, 16);
  windowEndInput.value = bars[e].time.slice(0, 16);
}}
function applyWindow() {{
  const start = parseTimeInput(windowStartInput.value), end = parseTimeInput(windowEndInput.value);
  if (!start || !end || !bars.length) return;
  const lowTime = Math.min(minuteValue(start), minuteValue(end)), highTime = Math.max(minuteValue(start), minuteValue(end));
  const firstQuoted = lowerBoundMinute(lowTime), afterQuoted = upperBoundMinute(highTime);
  if (firstQuoted >= afterQuoted) {{
    noQuoteWindow = `${{start.slice(0,16)}} 至 ${{end.slice(0,16)}} · 该区间无报价`;
    document.getElementById('windowLabel').textContent = noQuoteWindow;
    statusEl.textContent = noQuoteWindow;
    return;
  }}
  noQuoteWindow = '';
  if (showRealGaps) {{
    viewStart = Math.max(0, lowTime - firstBarMinute);
    viewEnd = Math.min(axisMax(), highTime - firstBarMinute);
  }} else {{
    viewStart = firstQuoted; viewEnd = afterQuoted - 1;
  }}
  clampView();
  draw(false);
}}
function scheduleDraw(syncInputs=true, updateDom=true) {{
  pendingDraw = {{syncInputs, updateDom}};
  if (scheduleDraw.raf) return;
  scheduleDraw.raf = requestAnimationFrame(() => {{
    const next = pendingDraw || {{syncInputs:true, updateDom:true}};
    pendingDraw = null;
    scheduleDraw.raf = null;
    draw(next.syncInputs, next.updateDom);
  }});
}}
function applyWindowOnEnter(ev) {{
  if (ev.key === 'Enter') applyWindow();
}}
function holdSeconds(t) {{
  if (t["Holding Seconds"] != null && t["Holding Seconds"] !== '') return Math.max(0, Number(t["Holding Seconds"]) || 0);
  const open = new Date(String(t["Open Time"]).replace(' ', 'T'));
  const close = new Date(String(t["Close Time"]).replace(' ', 'T'));
  const sec = Math.round((close - open) / 1000);
  return Number.isFinite(sec) ? Math.max(0, sec) : 0;
}}
function formatDuration(sec) {{
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${{h}}小时${{m}}分`;
  if (m) return `${{m}}分${{s}}秒`;
  return `${{s}}秒`;
}}
function clampView() {{
  const minSpan = 8;
  if (viewEnd - viewStart < minSpan) {{
    const mid = (viewStart + viewEnd) / 2;
    viewStart = mid - minSpan / 2; viewEnd = mid + minSpan / 2;
  }}
  const span = viewEnd - viewStart;
  if (viewStart < 0) {{ viewStart = 0; viewEnd = span; }}
  if (viewEnd > axisMax()) {{ viewEnd = axisMax(); viewStart = viewEnd - span; }}
  viewStart = Math.max(0, viewStart); viewEnd = Math.min(axisMax(), viewEnd);
}}
function zoom(factor, anchorRatio=0.5) {{
  const span = viewEnd - viewStart, anchor = viewStart + span * anchorRatio;
  const newSpan = Math.max(8, Math.min(axisMax(), span * factor));
  viewStart = anchor - newSpan * anchorRatio;
  viewEnd = anchor + newSpan * (1 - anchorRatio);
  clampView(); scheduleDraw();
}}
function reset() {{ viewStart = 0; viewEnd = Math.max(1, axisMax()); noQuoteWindow=''; scheduleDraw(); }}
function fitTrades() {{
  const all = filteredTrades();
  const focusLimit = Math.min(displayLimit(), 60);
  const focus = all.length > focusLimit ? all.slice(-focusLimit) : all;
  const idxs = focus.flatMap(t => [tradePosition(t.openLocation), tradePosition(t.closeLocation)]).filter(Number.isFinite);
  if (!idxs.length) return draw();
  viewStart = Math.max(0, Math.min(...idxs) - 20);
  viewEnd = Math.min(axisMax(), Math.max(...idxs) + 20);
  scheduleDraw();
}}
function visibleBars() {{
  const [start, end] = visibleIndexRange(), visible = [];
  for (let index = start; index <= end; index++) visible.push([bars[index], index, barPosition(index)]);
  return visible;
}}
function visibleTrades() {{
  return filteredTrades().filter(t => {{
    const open = tradePosition(t.openLocation), close = tradePosition(t.closeLocation);
    return (open >= viewStart && open <= viewEnd) || (close >= viewStart && close <= viewEnd);
  }});
}}
function numberFilter(input) {{
  const text = String(input.value || '').trim();
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}}
function filteredTrades() {{
  const key = [
    symbol,
    filterTypeInput.value,
    filterVolumeMinInput.value,
    filterVolumeMaxInput.value,
    filterProfitMinInput.value,
    filterProfitMaxInput.value,
    filterHoldMinInput.value,
    filterHoldMaxInput.value,
  ].join('|');
  if (filteredTradesCache && key === filteredTradesCacheKey) return filteredTradesCache;
  const type = filterTypeInput.value;
  const volMin = numberFilter(filterVolumeMinInput), volMax = numberFilter(filterVolumeMaxInput);
  const profitMin = numberFilter(filterProfitMinInput), profitMax = numberFilter(filterProfitMaxInput);
  const holdMin = numberFilter(filterHoldMinInput), holdMax = numberFilter(filterHoldMaxInput);
  filteredTradesCacheKey = key;
  filteredTradesCache = trades.filter(t => {{
    const volume = Number(t.Volume) || 0;
    const profit = Number(t.Profit) || 0;
    const holdMinValue = holdSeconds(t) / 60;
    if (type && t.Type !== type) return false;
    if (volMin != null && volume < volMin) return false;
    if (volMax != null && volume > volMax) return false;
    if (profitMin != null && profit < profitMin) return false;
    if (profitMax != null && profit > profitMax) return false;
    if (holdMin != null && holdMinValue < holdMin) return false;
    if (holdMax != null && holdMinValue > holdMax) return false;
    return true;
  }});
  return filteredTradesCache;
}}
function invalidateTradeCache() {{
  filteredTradesCache = null;
  filteredTradesCacheKey = '';
  lastTableKey = '';
}}
function resizeCanvas(c, cctx) {{
  const dpr = window.devicePixelRatio || 1, rect = c.getBoundingClientRect();
  c.width = Math.floor(rect.width * dpr); c.height = Math.floor(rect.height * dpr);
  cctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}}
function resize() {{ resizeCanvas(canvas, ctx); draw(); }}
function digits() {{ return symbol.includes('XAU') ? 2 : 5; }}
function draw(syncInputs=true, updateDom=true) {{
  const rect = canvas.getBoundingClientRect(), W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);
  const pad = {{l:72, r:24, t:20, b:74}}, plotW = W - pad.l - pad.r;
  const profitH = 118, profitGap = 30;
  const plotH = Math.max(280, H - pad.t - pad.b - profitH - profitGap);
  const profitTop = pad.t + plotH + profitGap;
  const allFiltered = filteredTrades();
  const vb = visibleBars(), vt = visibleTrades(), shown = vt.slice(0, displayLimit());
  if (!vb.length) return;
  const x = position => pad.l + (position - viewStart) / (viewEnd - viewStart) * plotW;
  const candleX = position => x(position);
  const maxDrawBars = Math.max(1, Math.floor(plotW * 1.5));
  let candleBars = [];
  if (vb.length > maxDrawBars) {{
    let group = null, groupKey = '';
    vb.forEach(([b, _index, position]) => {{
      const key = `${{b.segment || 0}}:${{Math.floor(candleX(position))}}`;
      if (key !== groupKey) {{
        if (group) candleBars.push([group, group.positionSum / group.count]);
        groupKey = key;
        group = {{positionSum: position, count: 1, open: Number(b.open), close: Number(b.close), high: Number(b.high), low: Number(b.low)}};
        return;
      }}
      group.positionSum += position; group.count += 1;
      group.high = Math.max(group.high, Number(b.high));
      group.low = Math.min(group.low, Number(b.low));
      group.close = Number(b.close);
    }});
    if (group) candleBars.push([group, group.positionSum / group.count]);
  }} else {{
    candleBars = vb.map(([bar, _index, position]) => [bar, position]);
  }}
  let lo = Infinity, hi = -Infinity;
  candleBars.forEach(([b]) => {{ lo = Math.min(lo, Number(b.low)); hi = Math.max(hi, Number(b.high)); }});
  shown.forEach(t => {{
    lo = Math.min(lo, Number(t["Open Plot Price"] ?? t["Open Price"]), Number(t["Close Plot Price"] ?? t["Close Price"]));
    hi = Math.max(hi, Number(t["Open Plot Price"] ?? t["Open Price"]), Number(t["Close Plot Price"] ?? t["Close Price"]));
  }});
  const d = digits(), margin = Math.max(d === 2 ? 0.5 : 0.0002, (hi - lo) * 0.08);
  lo -= margin; hi += margin;
  const y = p => pad.t + (hi - p) / (hi - lo) * plotH;
  const priceFromY = yy => hi - ((yy - pad.t) / plotH) * (hi - lo);
  const indexFromX = xx => viewStart + ((xx - pad.l) / plotW) * (viewEnd - viewStart);
  ctx.fillStyle = 'rgb(255,255,255)'; ctx.fillRect(pad.l, pad.t, plotW, plotH);
  ctx.strokeStyle = '#e5e7eb'; ctx.lineWidth = 1; ctx.font = '12px Arial'; ctx.fillStyle = '#4b5563';
  for (let k = 0; k <= 7; k++) {{
    const yy = pad.t + plotH * k / 7;
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(pad.l + plotW, yy); ctx.stroke();
    ctx.fillText((hi - (hi - lo) * k / 7).toFixed(d), 8, yy + 4);
  }}
  const labelStep = Math.max(1, Math.ceil(vb.length / 9));
  for (let i = 0; i < vb.length; i += labelStep) ctx.fillText(vb[i][0].time.slice(5,16), x(vb[i][2]) - 28, H - 38);
  const candleW = vb.length > maxDrawBars ? 1.2 : Math.max(2, Math.min(13, plotW / Math.max(vb.length, 1) * 0.62));
  candleBars.forEach(([b, position]) => {{
    const xx = candleX(position), up = Number(b.close) >= Number(b.open);
    ctx.strokeStyle = up ? '#16a34a' : '#dc2626'; ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath(); ctx.moveTo(xx, y(Number(b.high))); ctx.lineTo(xx, y(Number(b.low))); ctx.stroke();
    const top = y(Math.max(Number(b.open), Number(b.close))), bot = y(Math.min(Number(b.open), Number(b.close)));
    ctx.fillRect(xx - candleW / 2, top, candleW, Math.max(1, bot - top));
  }});
  let lastGapLabelX = -Infinity;
  visibleGapMarkers(x, pad.l, plotW).forEach(g => {{
    const xx = x(g.position);
    ctx.save(); ctx.strokeStyle = g.closed ? '#ffc779' : '#6f8aa2'; ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(xx,pad.t); ctx.lineTo(xx,pad.t+plotH); ctx.stroke(); ctx.setLineDash([]);
    if (xx - lastGapLabelX < 112) {{ ctx.restore(); return; }}
    const label = g.groupedCount > 1
      ? `${{g.closedCount ? '停盘/断点' : '断点'}} ${{g.groupedCount}}段`
      : (g.closed ? `停盘 ${{formatDuration(g.minutes * 60)}}` : `断点 ${{Math.round(g.minutes)}}分`);
    ctx.fillStyle = '#fff7ed'; ctx.fillRect(Math.max(pad.l,xx-52),pad.t+5,104,18); ctx.fillStyle='#92400e'; ctx.fillText(label,Math.max(pad.l+4,xx-47),pad.t+18); ctx.restore();
    lastGapLabelX = xx;
  }});
  shown.forEach(t => {{
    const openPosition=tradePosition(t.openLocation), closePosition=tradePosition(t.closeLocation);
    const xo = x(openPosition), xc = x(closePosition), yo = y(Number(t["Open Plot Price"] ?? t["Open Price"])), yc = y(Number(t["Close Plot Price"] ?? t["Close Price"]));
    ctx.strokeStyle = '#7c3aed'; ctx.lineWidth = 1.6; ctx.setLineDash([5,4]);
    ctx.beginPath(); ctx.moveTo(xo, yo); ctx.lineTo(xc, yc); ctx.stroke(); ctx.setLineDash([]);
    if (openPosition >= viewStart && openPosition <= viewEnd) {{
      const isBuy = t.Type === 'buy';
      ctx.beginPath();
      if (isBuy) {{ ctx.moveTo(xo, yo - 7); ctx.lineTo(xo - 6, yo + 5); ctx.lineTo(xo + 6, yo + 5); }}
      else {{ ctx.moveTo(xo, yo + 7); ctx.lineTo(xo - 6, yo - 5); ctx.lineTo(xo + 6, yo - 5); }}
      ctx.closePath();
      if (t.openLocation.missing) {{ ctx.strokeStyle='#d97706'; ctx.lineWidth=2; ctx.stroke(); }}
      else {{ ctx.fillStyle='#111827'; ctx.fill(); ctx.strokeStyle='#fff'; ctx.lineWidth=1.5; ctx.stroke(); }}
    }}
    if (closePosition >= viewStart && closePosition <= viewEnd) {{
      if (t.closeLocation.missing) {{ ctx.strokeStyle='#ffc779'; ctx.lineWidth=2; ctx.strokeRect(xc-5,yc-5,10,10); }}
      else {{ ctx.fillStyle = '#2563eb'; ctx.fillRect(xc - 4, yc - 4, 8, 8); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.2; ctx.strokeRect(xc - 4, yc - 4, 8, 8); }}
    }}
  }});
  ctx.strokeStyle = '#9ca3af'; ctx.strokeRect(pad.l, pad.t, plotW, plotH);
  drawKdeskBottomPanel(shown, pad, plotW, profitTop, profitH, x);
  const crosshairBottom = profitTop + profitH;
  if (crosshair && crosshair.x >= pad.l && crosshair.x <= pad.l + plotW && crosshair.y >= pad.t && crosshair.y <= crosshairBottom) {{
    const targetPosition=indexFromX(crosshair.x), idx=nearestBarIndex(targetPosition), cx = x(barPosition(idx)), cy = crosshair.y, price = priceFromY(cy);
    const xLabel = Math.max(pad.l, Math.min(cx - 58, pad.l + plotW - 116)), yLabel = Math.max(pad.t, Math.min(cy - 10, pad.t + plotH - 20));
    ctx.save(); ctx.strokeStyle = '#111827'; ctx.setLineDash([3,3]);
    ctx.beginPath(); ctx.moveTo(cx, pad.t); ctx.lineTo(cx, crosshairBottom); ctx.stroke();
    if (cy <= pad.t + plotH) {{
      ctx.beginPath(); ctx.moveTo(pad.l, cy); ctx.lineTo(pad.l + plotW, cy); ctx.stroke();
      const priceLabelX = Math.max(4, pad.l - 68);
      ctx.setLineDash([]); ctx.fillStyle = '#111827'; ctx.fillRect(priceLabelX, yLabel, 64, 20);
      ctx.fillStyle = '#fff'; ctx.fillText(price.toFixed(d), priceLabelX + 6, yLabel + 14);
    }} else {{
      ctx.setLineDash([]);
    }}
    ctx.fillStyle = '#111827'; ctx.fillRect(xLabel, crosshairBottom + 8, 116, 20);
    ctx.fillStyle = '#fff'; ctx.fillText(bars[idx].time.slice(5,16), xLabel + 8, crosshairBottom + 22); ctx.restore();
  }}
  const s = vb[0][1], e = vb[vb.length - 1][1];
  if (updateDom) {{
    const missingEndpoints=shown.reduce((sum,t)=>sum+Number(t.openLocation.missing)+Number(t.closeLocation.missing),0);
    statusEl.textContent = `${{bars[s].time}} - ${{bars[e].time}} | 可见K线 ${{vb.length}} / ${{bars.length}} | 过滤后 ${{allFiltered.length}} | 可见交易 ${{vt.length}} | 实际显示 ${{shown.length}}${{missingEndpoints?` | 无报价成交点 ${{missingEndpoints}}`:''}}`;
    if (syncInputs) setInputsFromView(s, e);
    const tableKey = symbol + '|' + shown.map(t => t.Ticket).join(',');
    if (tableKey !== lastTableKey) {{
      lastTableKey = tableKey;
      updateTable(shown);
    }}
    updateSummary(shown, s, e);
  }}
}}
function updateSummary(rows, s, e) {{
  const total = rows.reduce((sum, t) => sum + (Number(t.Profit) || 0), 0);
  const shownClosedPL = rows.reduce((sum, t) => sum + (Number(t.Profit) || 0) + (Number(t.Commission) || 0) + (Number(t.Taxes) || 0) + (Number(t.Swap) || 0), 0);
  const totalClosedPL = trades.reduce((sum, t) => sum + (Number(t.Profit) || 0) + (Number(t.Commission) || 0) + (Number(t.Taxes) || 0) + (Number(t.Swap) || 0), 0);
  document.getElementById('shownCount').textContent = String(rows.length);
  document.getElementById('shownProfit').textContent = `${{total.toFixed(2)}} / Net ${{shownClosedPL.toFixed(2)}}`;
  document.getElementById('shownProfit').style.color = shownClosedPL >= 0 ? '#dc2626' : '#16a34a';
  document.getElementById('totalClosedPL').textContent = totalClosedPL.toFixed(2);
  document.getElementById('totalClosedPL').style.color = totalClosedPL >= 0 ? '#dc2626' : '#16a34a';
  document.getElementById('windowLabel').textContent = bars.length ? `${{bars[s].time}} 至 ${{bars[e].time}}` : '-';
}}
function updateTable(rows) {{
  const cols = ["Ticket","Type","Volume","Open Time","Open Price","S/L","T/P","Close Time","Close Price","Hold Time","Profit","Comment"];
  document.getElementById('tradeTable').innerHTML = '<thead><tr>' + cols.map(c => `<th class="${{["Ticket","Type","Open Time","Close Time","Hold Time"].includes(c) ? 'left' : ''}}">${{c}}</th>`).join('') + '</tr></thead><tbody>' + rows.map(t => '<tr>' + cols.map(c => {{
    let v = c === "Hold Time" ? formatDuration(holdSeconds(t)) : t[c];
    if (typeof v === 'number') v = Math.abs(v) < 10 ? v.toFixed(5) : v.toFixed(2);
    return `<td class="${{["Ticket","Type","Open Time","Close Time","Hold Time","Comment"].includes(c) ? 'left' : ''}}">${{v ?? ''}}</td>`;
  }}).join('') + '</tr>').join('') + '</tbody>';
}}
function drawKdeskBottomPanel(rows, pad, plotW, top, height, xScale) {{
  ctx.save();
  ctx.fillStyle = 'rgba(248,250,252,0.96)';
  ctx.fillRect(pad.l, top, plotW, height);
  ctx.strokeStyle = '#dbe4ee';
  ctx.strokeRect(pad.l, top, plotW, height);
  ctx.font = '12px Arial';
  const label = panelMode === 'volume' ? 'Volume' : 'Profit';
  ctx.fillStyle = '#4b5563';
  ctx.fillText(label, pad.l + 8, top + 16);
  if (!rows.length) {{ ctx.restore(); return; }}
  const bw = Math.max(5, Math.min(18, plotW / Math.max(1, rows.length) * 0.72));

  if (panelMode === 'volume') {{
    const volumes = rows.map(t => Math.max(0, Number(t.Volume) || 0));
    const maxVol = Math.max(0.01, ...volumes);
    const baseY = top + height - 22;
    ctx.strokeStyle = '#94a3b8';
    ctx.beginPath(); ctx.moveTo(pad.l, baseY); ctx.lineTo(pad.l + plotW, baseY); ctx.stroke();
    ctx.fillStyle = '#4b5563';
    ctx.fillText(maxVol.toFixed(2), pad.l + 8, top + 34);
    ctx.fillText('0', pad.l + 8, baseY - 4);
    rows.forEach(t => {{
      const v = Math.max(0, Number(t.Volume) || 0);
      const h = v / maxVol * (height - 42);
      const cx = xScale(tradePosition(t.openLocation));
      if (cx < pad.l - bw || cx > pad.l + plotW + bw) return;
      ctx.fillStyle = 'rgba(59,130,246,0.86)';
      ctx.fillRect(cx - bw / 2, baseY - h, bw, Math.max(1, h));
    }});
    ctx.fillStyle = '#4b5563';
    ctx.fillText(`当前显示 ${{rows.length}} 笔，柱高代表手数`, pad.l + 8, top + height - 7);
    ctx.restore();
    return;
  }}

  const profits = rows.map(t => Number(t.Profit) || 0);
  const maxAbs = Math.max(1, ...profits.map(v => Math.abs(v)));
  const zeroY = top + height / 2;
  ctx.strokeStyle = '#64748b';
  ctx.setLineDash([5,4]);
  ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(pad.l + plotW, zeroY); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = '#4b5563';
  ctx.fillText(maxAbs.toFixed(2), pad.l + 8, top + 34);
  ctx.fillText('0', pad.l + 8, zeroY - 4);
  ctx.fillText((-maxAbs).toFixed(2), pad.l + 8, top + height - 24);
  rows.forEach(t => {{
    const p = Number(t.Profit) || 0;
    const h = Math.abs(p) / maxAbs * (height / 2 - 14);
    const cx = xScale(tradePosition(t.openLocation));
    if (cx < pad.l - bw || cx > pad.l + plotW + bw) return;
    const y = p >= 0 ? zeroY - h : zeroY;
    ctx.fillStyle = p >= 0 ? 'rgba(239,68,68,0.86)' : 'rgba(34,197,94,0.86)';
    ctx.fillRect(cx - bw / 2, y, bw, Math.max(1, h));
  }});
  ctx.fillStyle = '#4b5563';
  ctx.fillText(`当前显示 ${{rows.length}} 笔，红色为盈利，绿色为亏损`, pad.l + 8, top + height - 7);
  ctx.restore();
}}
function drawProfitPanel(rows, pad, plotW, top, height, xScale) {{
  ctx.save();
  ctx.fillStyle = 'rgba(248,250,252,0.94)';
  ctx.fillRect(pad.l, top, plotW, height);
  ctx.strokeStyle = '#dbe4ee';
  ctx.strokeRect(pad.l, top, plotW, height);
  ctx.font = '12px Arial';
  ctx.fillStyle = '#4b5563';
  ctx.fillText('Profit', 20, top + 16);
  if (!rows.length) {{ ctx.restore(); return; }}
  const profits = rows.map(t => Number(t.Profit) || 0);
  const maxAbs = Math.max(1, ...profits.map(v => Math.abs(v)));
  const zeroY = top + height / 2;
  ctx.strokeStyle = '#64748b';
  ctx.setLineDash([5,4]);
  ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(pad.l + plotW, zeroY); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = '#4b5563';
  ctx.fillText('0', 48, zeroY + 4);
  ctx.fillText(maxAbs.toFixed(2), 10, top + 12);
  ctx.fillText((-maxAbs).toFixed(2), 8, top + height - 6);
  const bw = Math.max(5, Math.min(18, plotW / Math.max(1, rows.length) * 0.72));
  rows.forEach(t => {{
    const p = Number(t.Profit) || 0;
    const h = Math.abs(p) / maxAbs * (height / 2 - 10);
    const cx = xScale(tradePosition(t.openLocation));
    if (cx < pad.l - bw || cx > pad.l + plotW + bw) return;
    const y = p >= 0 ? zeroY - h : zeroY;
    ctx.fillStyle = p >= 0 ? 'rgba(239,68,68,0.86)' : 'rgba(34,197,94,0.86)';
    ctx.fillRect(cx - bw / 2, y, bw, Math.max(1, h));
  }});
  ctx.fillStyle = '#4b5563';
  ctx.fillText(`当前显示 ${{rows.length}} 笔，红色为盈利，绿色为亏损`, pad.l + 4, top + height - 8);
  ctx.restore();
}}
function drawProfitChart(rows) {{
  const rect = profitCanvas.getBoundingClientRect(), W = rect.width, H = rect.height;
  profitCtx.clearRect(0, 0, W, H);
  const pad = {{l:72, r:24, t:22, b:38}}, plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
  profitCtx.fillStyle = '#fff'; profitCtx.fillRect(0, 0, W, H);
  profitCtx.strokeStyle = '#e5e7eb'; profitCtx.strokeRect(pad.l, pad.t, plotW, plotH);
  profitCtx.font = '12px Arial'; profitCtx.fillStyle = '#4b5563'; profitCtx.fillText('Profit', 18, pad.t + 12);
  if (!rows.length) return;
  const profits = rows.map(t => Number(t.Profit) || 0), maxAbs = Math.max(1, ...profits.map(v => Math.abs(v)));
  const zeroY = pad.t + plotH / 2;
  profitCtx.strokeStyle = '#111827'; profitCtx.setLineDash([5,4]); profitCtx.beginPath(); profitCtx.moveTo(pad.l, zeroY); profitCtx.lineTo(pad.l + plotW, zeroY); profitCtx.stroke(); profitCtx.setLineDash([]);
  profitCtx.fillStyle = '#4b5563'; profitCtx.fillText('0', 44, zeroY + 4); profitCtx.fillText(maxAbs.toFixed(2), 16, pad.t + 4); profitCtx.fillText((-maxAbs).toFixed(2), 12, pad.t + plotH + 4);
  const gap = Math.min(3, plotW / rows.length * 0.18), bw = Math.max(1, plotW / rows.length - gap);
  rows.forEach((t, i) => {{
    const p = Number(t.Profit) || 0, h = Math.abs(p) / maxAbs * (plotH / 2 - 8);
    const x = pad.l + i * (plotW / rows.length) + gap / 2, y = p >= 0 ? zeroY - h : zeroY;
    profitCtx.fillStyle = p >= 0 ? '#ef4444' : '#22c55e';
    profitCtx.fillRect(x, y, bw, Math.max(1, h));
  }});
  profitCtx.fillStyle = '#4b5563'; profitCtx.fillText(`当前显示 ${{rows.length}} 笔，红色为盈利，绿色为亏损`, pad.l, H - 13);
}}
canvas.addEventListener('wheel', ev => {{
  ev.preventDefault();
  const rect = canvas.getBoundingClientRect();
  zoom(ev.deltaY < 0 ? 0.72 : 1.38, Math.max(0, Math.min(1, (ev.clientX - rect.left - 72) / (rect.width - 96))));
}}, {{passive:false}});
canvas.addEventListener('mousemove', ev => {{ const rect = canvas.getBoundingClientRect(); crosshair = {{x:ev.clientX - rect.left, y:ev.clientY - rect.top}}; scheduleDraw(false, false); }});
canvas.addEventListener('mouseleave', () => {{ crosshair = null; scheduleDraw(false, false); }});
canvas.addEventListener('mousedown', ev => {{ canvas.classList.add('dragging'); drag = {{x:ev.clientX, start:viewStart, end:viewEnd}}; }});
window.addEventListener('mousemove', ev => {{
  if (!drag) return;
  const rect = canvas.getBoundingClientRect(), span = drag.end - drag.start, deltaPx = ev.clientX - drag.x;
  viewStart = drag.start - deltaPx / Math.max(1, rect.width - 96) * span;
  viewEnd = drag.end - deltaPx / Math.max(1, rect.width - 96) * span;
  clampView(); scheduleDraw();
}});
window.addEventListener('mouseup', () => {{ drag = null; canvas.classList.remove('dragging'); }});
canvas.addEventListener('dblclick', reset);
document.getElementById('zoomIn').addEventListener('click', () => zoom(0.65));
document.getElementById('zoomOut').addEventListener('click', () => zoom(1.55));
document.getElementById('reset').addEventListener('click', reset);
document.querySelector('#fitTrades').addEventListener('click', fitTrades);
function setGapMode(expanded) {{
  showRealGaps = expanded;
  hideGapsButton.classList.toggle('active', !expanded);
  showGapsButton.classList.toggle('active', expanded);
  reset();
}}
hideGapsButton.addEventListener('click', () => setGapMode(false));
showGapsButton.addEventListener('click', () => setGapMode(true));
document.getElementById('applyWindow').addEventListener('click', applyWindow);
windowStartInput.addEventListener('keydown', applyWindowOnEnter);
windowEndInput.addEventListener('keydown', applyWindowOnEnter);
document.getElementById('panelProfit').addEventListener('click', () => {{
  panelMode = 'profit';
  document.getElementById('panelProfit').classList.add('active');
  document.getElementById('panelVolume').classList.remove('active');
  scheduleDraw(false);
}});
document.getElementById('panelVolume').addEventListener('click', () => {{
  panelMode = 'volume';
  document.getElementById('panelVolume').classList.add('active');
  document.getElementById('panelProfit').classList.remove('active');
  scheduleDraw(false);
}});
const positionPanelButton = document.getElementById('panelPosition');
if (positionPanelButton) positionPanelButton.addEventListener('click', () => {{
  panelMode = 'position';
  positionPanelButton.classList.add('active');
  document.getElementById('panelProfit').classList.remove('active');
  document.getElementById('panelVolume').classList.remove('active');
  scheduleDraw(false);
}});
const barStackButton = document.getElementById('barStackToggle');
if (barStackButton) barStackButton.addEventListener('click', () => {{
  barStackMode = barStackMode === 'stack' ? 'single' : 'stack';
  barStackButton.textContent = barStackMode === 'stack' ? 'Profit柱：叠加' : 'Profit柱：单独';
  scheduleDraw(false);
}});
canvas.addEventListener('click', ev => {{
  if (typeof updatePositionSnapshot !== 'function' || drag) return;
  const rect=canvas.getBoundingClientRect(), ratio=Math.max(0,Math.min(1,(ev.clientX-rect.left-72)/Math.max(1,rect.width-96)));
  const position=viewStart+ratio*(viewEnd-viewStart);
  const ms=showRealGaps ? firstBarMinute*60000+position*60000 : barMinutes[Math.max(0,Math.min(bars.length-1,Math.round(position)))]*60000;
  updatePositionSnapshot(ms);
}});
displayLimitInput.addEventListener('input', () => {{ lastTableKey = ''; scheduleDraw(false); }});
[
  filterTypeInput,
  filterVolumeMinInput,
  filterVolumeMaxInput,
  filterProfitMinInput,
  filterProfitMaxInput,
  filterHoldMinInput,
  filterHoldMaxInput,
].forEach(el => el.addEventListener('input', () => {{ invalidateTradeCache(); scheduleDraw(false); }}));
document.getElementById('clearFilters').addEventListener('click', () => {{
  filterTypeInput.value = '';
  filterVolumeMinInput.value = '';
  filterVolumeMaxInput.value = '';
  filterProfitMinInput.value = '';
  filterProfitMaxInput.value = '';
  filterHoldMinInput.value = '';
  filterHoldMaxInput.value = '';
  invalidateTradeCache();
  scheduleDraw(false);
}});
symbolSelect.innerHTML = Object.keys(DATA.barsBySymbol).map(s => `<option value="${{s}}">${{s}}</option>`).join('');
symbolSelect.addEventListener('change', ev => setSymbol(ev.target.value));
window.addEventListener('resize', resize);
setSymbol(symbol); resize();
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build enhanced buy/sell K-line HTML from cached trades and M1 bars.")
    parser.add_argument("--trades", required=True, help="Path to {stem}_trades.csv")
    parser.add_argument("--mapping", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    trades_path = Path(args.trades)
    stem = infer_stem(trades_path)
    account = stem.split("_", 1)[0]
    mapping_path = Path(args.mapping) if args.mapping else trades_path.with_name(f"{stem}_mapping.json")
    out_path = Path(args.out) if args.out else trades_path.with_name(f"{stem}_trade_kline.html")

    trades = pd.read_csv(trades_path, parse_dates=["Open Time", "Close Time"])
    if "Holding Seconds" not in trades.columns:
        trades["Holding Seconds"] = (trades["Close Time"] - trades["Open Time"]).dt.total_seconds()
    mapping_by_symbol = json.loads(mapping_path.read_text(encoding="utf-8"))
    bars_by_symbol = {}
    for report_symbol, mapping in mapping_by_symbol.items():
        if not isinstance(mapping, dict) or mapping.get("validation_status") == "rejected" or not mapping.get("mt5_symbol"):
            continue
        symbol_trades = trades[trades["Item"] == report_symbol] if "Item" in trades.columns else trades.iloc[0:0]
        bars = load_bars_for_symbol(trades_path.parent, stem, report_symbol, mapping)
        bars_by_symbol[report_symbol] = apply_display_price_alignment(report_symbol, bars, symbol_trades, mapping)
    statement_path = find_statement_for_stem(trades_path.parent, account)
    html = enhance_trade_kline_html(build_html(account, stem, trades, bars_by_symbol, mapping_by_symbol), statement_path, trades)
    out_path.write_text(html, encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
