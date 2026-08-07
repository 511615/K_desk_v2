from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

OUT_DIR = Path(r"D:\risk\output_data")
TRADES = OUT_DIR / "214693_20250402_161100_20260615_121909_trades.csv"
OUT_HTML = OUT_DIR / "214693_20250402_161100_20260615_121909_trade_kline.html"


def parse_number(value) -> float:
    text = str(value).replace("\xa0", "").replace(" ", "").strip()
    text = re.sub(r"[^0-9.\-]+", "", text)
    return float(text) if text and text not in {"-", "."} else 0.0


def read_report_tables(report_html: Path) -> list[pd.DataFrame]:
    attempts = [
        {"flavor": "lxml"},
        {"flavor": "lxml", "encoding": "utf-8"},
        {"flavor": "lxml", "encoding": "utf-16"},
    ]
    errors = []
    for kwargs in attempts:
        try:
            return pd.read_html(report_html, **kwargs)
        except Exception as exc:
            errors.append(f"{kwargs}: {exc}")
    raise RuntimeError(f"Unable to parse report HTML for position metadata: {report_html}; " + " | ".join(errors))


def fallback_position_meta(trades: pd.DataFrame, report_html: Path | str = "") -> dict:
    try:
        money_scale = float(trades["Money Scale"].dropna().iloc[0]) if "Money Scale" in trades.columns and not trades["Money Scale"].dropna().empty else 1.0
    except (TypeError, ValueError):
        money_scale = 1.0
    currency = str(trades["Account Currency"].dropna().iloc[0]).upper() if "Account Currency" in trades.columns and not trades["Account Currency"].dropna().empty else ""
    display_currency = str(trades["Display Currency"].dropna().iloc[0]).upper() if "Display Currency" in trades.columns and not trades["Display Currency"].dropna().empty else currency
    is_cent = bool(str(trades["Is Cent Account"].dropna().iloc[0]).lower() == "true") if "Is Cent Account" in trades.columns and not trades["Is Cent Account"].dropna().empty else False
    return {
        "initialBalance": 10000.0 * money_scale,
        "leverage": 500.0,
        "balanceEvents": [],
        "symbolMultipliers": {},
        "currency": currency,
        "displayCurrency": display_currency,
        "moneyScale": money_scale,
        "isCentAccount": is_cent,
        "reportHtml": str(report_html),
        "positionMetaWarning": "Report balance/leverage metadata could not be parsed; using default balance/leverage.",
    }


def load_position_meta(report_html: Path, trades: pd.DataFrame) -> dict:
    tables = read_report_tables(report_html)
    report = tables[0]
    try:
        money_scale = float(trades["Money Scale"].dropna().iloc[0]) if "Money Scale" in trades.columns and not trades["Money Scale"].dropna().empty else 1.0
    except (TypeError, ValueError):
        money_scale = 1.0
    currency = str(trades["Account Currency"].dropna().iloc[0]).upper() if "Account Currency" in trades.columns and not trades["Account Currency"].dropna().empty else ""
    display_currency = str(trades["Display Currency"].dropna().iloc[0]).upper() if "Display Currency" in trades.columns and not trades["Display Currency"].dropna().empty else currency
    is_cent = bool(str(trades["Is Cent Account"].dropna().iloc[0]).lower() == "true") if "Is Cent Account" in trades.columns and not trades["Is Cent Account"].dropna().empty else False
    balance_rows = report[report[3].astype(str).str.lower().eq("balance")].copy()
    balance_events: list[dict] = []
    for _, row in balance_rows.iterrows():
        ts = pd.to_datetime(str(row[0]).replace(".", "-"), errors="coerce")
        if pd.isna(ts):
            continue
        balance_events.append(
            {
                "time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "delta": (parse_number(row[11]) if len(row) > 11 else 0.0) * money_scale,
                "balanceAfter": (parse_number(row[12]) if len(row) > 12 else 0.0) * money_scale,
            }
        )
    initial_balance = balance_events[0]["balanceAfter"] if balance_events else 10000.0
    balance_events = balance_events[1:] if len(balance_events) > 1 else []
    leverage_match = re.search(r"\b1:(\d+)\b", report_html.read_text(encoding="utf-16", errors="ignore"))
    leverage = float(leverage_match.group(1)) if leverage_match else 500.0

    symbol_multipliers: dict[str, float] = {}
    for symbol, group in trades.groupby("Item"):
        samples = []
        for _, row in group.iterrows():
            diff = abs(float(row["Close Price"]) - float(row["Open Price"]))
            volume = float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0
            profit = abs(float(row["Profit"])) if pd.notna(row["Profit"]) else 0.0
            if diff > 1e-12 and volume > 0 and profit > 0:
                samples.append(profit / (diff * volume))
        if samples:
            symbol_multipliers[str(symbol)] = float(pd.Series(samples).median())

    return {
        "initialBalance": float(initial_balance),
        "leverage": float(leverage),
        "balanceEvents": balance_events,
        "symbolMultipliers": symbol_multipliers,
        "currency": currency,
        "displayCurrency": display_currency,
        "moneyScale": money_scale,
        "isCentAccount": is_cent,
        "reportHtml": str(report_html),
    }


EXTRA_CSS = """
.positionSnapshot { display:grid; grid-template-columns:repeat(8,minmax(130px,1fr)); gap:8px; margin-top:12px; }
.positionSnapshot .metric { border-color:#dbe4ee; }
.positionSnapshot .metric.clickable { cursor:pointer; }
.positionSnapshot .metric.clickable:hover { border-color:#2563eb; background:#eff6ff; }
.positionPanel { background:#fff; border:1px solid #e5e7eb; margin-top:12px; padding:10px 12px; }
.positionPanelHead { display:flex; gap:12px; align-items:center; flex-wrap:wrap; font-weight:700; }
.positionPanelHead span { color:#64748b; font-weight:400; font-size:12px; }
.positionTableWrap { overflow:auto; max-height:300px; border:1px solid #e5e7eb; margin-top:8px; }
.metricSub { margin-top:4px; color:#64748b; font-size:12px; line-height:1.35; font-weight:400; }
.riskGood { color:#16a34a; } .riskWarn { color:#f59e0b; } .riskBad { color:#dc2626; }
@media (max-width: 900px) { .positionSnapshot { grid-template-columns:repeat(1,minmax(130px,1fr)); } }
""" 


EXTRA_JS = r"""
const POSITION_CONTRACT_SIZE = 100;
let POSITION_LEVERAGE = 500;
let POSITION_INITIAL_BALANCE = 10000;
let POSITION_BALANCE_EVENTS = [];
let POSITION_SYMBOL_MULTIPLIERS = {};
const QUOTE_GAP_MINUTES = 5;
let selectedSnapshotMs = null;
let showNoQuoteTime = false;
let timeViewStartMs = null;
let timeViewEndMs = null;
let barStackMode = 'single';
let positionPanelCacheKey = '';
let positionPanelCache = null;
let positionSnapshotCache = new Map();
let positionExtremeCacheKey = '';
let positionExtremeCache = null;

function toMs(text) {
  return Date.parse(String(text).replace(' ', 'T'));
}
function barMs(idx) {
  idx = Math.max(0, Math.min(bars.length - 1, Math.round(idx)));
  return bars.length ? toMs(bars[idx].time) : 0;
}
function findIndexByMs(ms) {
  if (!bars.length) return 0;
  let lo = 0, hi = bars.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const bt = toMs(bars[mid].time);
    if (bt <= ms) lo = mid + 1; else hi = mid - 1;
  }
  const left = Math.max(0, Math.min(bars.length - 1, hi));
  const right = Math.max(0, Math.min(bars.length - 1, lo));
  return Math.abs(barMs(right) - ms) < Math.abs(barMs(left) - ms) ? right : left;
}
function ensureTimeView() {
  if (!bars.length) return;
  if (!Number.isFinite(timeViewStartMs) || !Number.isFinite(timeViewEndMs) || timeViewEndMs <= timeViewStartMs) {
    timeViewStartMs = barMs(Math.max(0, Math.floor(viewStart)));
    timeViewEndMs = barMs(Math.min(bars.length - 1, Math.ceil(viewEnd)));
    if (timeViewEndMs <= timeViewStartMs) timeViewEndMs = timeViewStartMs + 8 * 60000;
  }
}
function syncIndexViewFromTime() {
  if (!bars.length || !showNoQuoteTime) return;
  ensureTimeView();
  viewStart = findIndexByMs(timeViewStartMs);
  viewEnd = findIndexByMs(timeViewEndMs);
  if (viewEnd <= viewStart) viewEnd = Math.min(bars.length - 1, viewStart + 8);
}
function clampTimeView() {
  if (!bars.length) return;
  ensureTimeView();
  const first = barMs(0), last = barMs(bars.length - 1);
  const minSpan = 8 * 60000;
  if (timeViewEndMs - timeViewStartMs < minSpan) {
    const mid = (timeViewStartMs + timeViewEndMs) / 2;
    timeViewStartMs = mid - minSpan / 2;
    timeViewEndMs = mid + minSpan / 2;
  }
  let span = timeViewEndMs - timeViewStartMs;
  const maxSpan = Math.max(minSpan, last - first);
  span = Math.min(span, maxSpan);
  if (timeViewStartMs < first) { timeViewStartMs = first; timeViewEndMs = first + span; }
  if (timeViewEndMs > last) { timeViewEndMs = last; timeViewStartMs = last - span; }
  timeViewStartMs = Math.max(first, timeViewStartMs);
  timeViewEndMs = Math.min(last, timeViewEndMs);
  syncIndexViewFromTime();
}
function visibleIndexBounds() {
  if (!bars.length) return {s:0, e:0};
  if (!showNoQuoteTime) {
    return {s: Math.max(0, Math.floor(viewStart)), e: Math.min(bars.length - 1, Math.ceil(viewEnd))};
  }
  ensureTimeView();
  const startIdx = findIndexByMs(timeViewStartMs);
  const endIdx = findIndexByMs(timeViewEndMs);
  return {s: Math.max(0, Math.min(startIdx, endIdx) - 1), e: Math.min(bars.length - 1, Math.max(startIdx, endIdx) + 1)};
}
function timeToCanvasX(ms, pad, plotW) {
  if (!showNoQuoteTime) {
    const idx = findIndexByMs(ms);
    return pad.l + (idx - viewStart) / Math.max(1e-9, viewEnd - viewStart) * plotW;
  }
  ensureTimeView();
  return pad.l + (ms - timeViewStartMs) / Math.max(1, timeViewEndMs - timeViewStartMs) * plotW;
}
function xForIndex(idx, pad, plotW) {
  return showNoQuoteTime ? timeToCanvasX(barMs(idx), pad, plotW) : pad.l + (idx - viewStart) / Math.max(1e-9, viewEnd - viewStart) * plotW;
}
function indexFromCanvasX(xx, pad, plotW) {
  const ratio = Math.max(0, Math.min(1, (xx - pad.l) / Math.max(1, plotW)));
  if (!showNoQuoteTime) return viewStart + ratio * (viewEnd - viewStart);
  ensureTimeView();
  return findIndexByMs(timeViewStartMs + ratio * (timeViewEndMs - timeViewStartMs));
}
function msFromCanvasX(xx, pad, plotW) {
  const ratio = Math.max(0, Math.min(1, (xx - pad.l) / Math.max(1, plotW)));
  if (showNoQuoteTime) {
    ensureTimeView();
    return timeViewStartMs + ratio * (timeViewEndMs - timeViewStartMs);
  }
  return barMs(viewStart + ratio * (viewEnd - viewStart));
}
function fmtAxisTime(ms, withDate=false) {
  const d = new Date(ms);
  const md = String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
  const hm = String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
  return withDate ? `${md} ${hm}` : `${md} ${hm}`;
}
function fmtInputTime(ms) {
  const d = new Date(ms);
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0') + ' ' +
    String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}
function fmtMoney(value, digits=2) {
  return Number(value || 0).toLocaleString(undefined, {minimumFractionDigits: digits, maximumFractionDigits: digits});
}
function fmtSnapshotTime(ms) {
  const d = new Date(ms);
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0') + ' ' +
    String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0') + ':' + String(d.getSeconds()).padStart(2,'0');
}
function indexForMs(ms) {
  let lo = 0, hi = bars.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const bt = toMs(bars[mid].time);
    if (bt <= ms) lo = mid + 1; else hi = mid - 1;
  }
  return Math.max(0, Math.min(bars.length - 1, hi));
}
function holdingText(minutes) {
  const h = Math.floor(minutes / 60), m = Math.floor(minutes % 60);
  return h ? `${h}小时${m}分` : `${m}分`;
}
function avgHoldingText(rows) {
  if (!rows || !rows.length) return '-';
  const seconds = rows.reduce((sum, t) => sum + holdSeconds(t), 0) / rows.length;
  return formatDuration(seconds);
}
function focusTimeMs(ms, spanMinutes=90) {
  if (!bars.length || !Number.isFinite(ms)) return;
  selectedSnapshotMs = ms;
  if (showNoQuoteTime) {
    const half = spanMinutes * 60000 / 2;
    timeViewStartMs = ms - half;
    timeViewEndMs = ms + half;
    clampTimeView();
  } else {
    const idx = indexForMs(ms);
    const halfBars = Math.max(8, Math.round(spanMinutes / 2));
    viewStart = Math.max(0, idx - halfBars);
    viewEnd = Math.min(bars.length - 1, idx + halfBars);
    clampView();
  }
  draw(false);
}
function snapshotAtIndex(idx) {
  if (!bars.length) return {rows: [], count: 0, volume: 0, floating: 0, balance: POSITION_INITIAL_BALANCE, equity: POSITION_INITIAL_BALANCE, margin: 0, used: 0, level: Infinity, price: 0, ms: 0};
  idx = Math.max(0, Math.min(bars.length - 1, Math.round(idx)));
  const b = bars[idx], ms = toMs(b.time), price = Number(b.close);
  const rows = trades.filter(t => toMs(t["Open Time"]) <= ms && toMs(t["Close Time"]) > ms).map(t => {
    const volume = Number(t.Volume) || 0;
    const open = Number(t["Open Price"]) || 0;
    const dir = t.Type === 'buy' ? 1 : -1;
    const contractSize = contractSizeForTrade(t);
    const floating = (price - open) * dir * volume * contractSize;
    const margin = estimateMargin(t, price, contractSize);
    return {...t, markPrice: price, contractSize, floating, margin, holdingMin: (ms - toMs(t["Open Time"])) / 60000};
  });
  const floating = rows.reduce((sum, row) => sum + row.floating, 0);
  const margin = rows.reduce((sum, row) => sum + row.margin, 0);
  const balance = singleSymbolBalanceAtMs(ms);
  const equity = balance + floating;
  const ratios = marginRatios(margin, equity);
  const used = ratios.used, level = ratios.level;
  return {rows, count: rows.length, volume: rows.reduce((sum, row) => sum + Number(row.Volume || 0), 0), floating, balance, equity, margin, used, level, price, ms};
}
function cachedSnapshotAtIndex(idx) {
  idx = Math.max(0, Math.min(bars.length - 1, Math.round(idx)));
  const key = `${symbol}|${idx}`;
  const cached = positionSnapshotCache.get(key);
  if (cached) return cached;
  if (positionSnapshotCache.size > 5000) positionSnapshotCache.clear();
  const snap = snapshotAtIndex(idx);
  positionSnapshotCache.set(key, snap);
  return snap;
}
function positionExtremes() {
  const key = `${symbol}|${bars.length}|${trades.length}`;
  if (positionExtremeCacheKey === key && positionExtremeCache) return positionExtremeCache;
  let maxPosition = {volume: 0, count: 0, margin: 0, ms: NaN};
  for (let i = 0; i < bars.length; i++) {
    const snap = cachedSnapshotAtIndex(i);
    const score = [Number(snap.volume) || 0, Number(snap.count) || 0, Number(snap.margin) || 0];
    const best = [Number(maxPosition.volume) || 0, Number(maxPosition.count) || 0, Number(maxPosition.margin) || 0];
    if (score[0] > best[0] || (score[0] === best[0] && (score[1] > best[1] || (score[1] === best[1] && score[2] > best[2])))) {
      maxPosition = {volume: snap.volume, count: snap.count, margin: snap.margin, ms: snap.ms};
    }
  }
  let longest = {seconds: 0, ms: NaN, ticket: ''};
  trades.forEach(t => {
    const sec = holdSeconds(t);
    if (sec > longest.seconds) longest = {seconds: sec, ms: tradeOpenMs(t), ticket: t.Ticket};
  });
  positionExtremeCache = {maxPosition, longest};
  positionExtremeCacheKey = key;
  return positionExtremeCache;
}
function updatePositionExtremes() {
  const maxEl = document.getElementById('posMaxPosition');
  const maxSub = document.getElementById('posMaxPositionSub');
  const maxCard = document.getElementById('posMaxPositionJump');
  const longEl = document.getElementById('posLongestHold');
  const longSub = document.getElementById('posLongestHoldSub');
  const longCard = document.getElementById('posLongestHoldJump');
  if (!maxEl || !longEl) return;
  const ext = positionExtremes();
  maxEl.textContent = `${fmtMoney(ext.maxPosition.volume, 2)}手 / ${ext.maxPosition.count}笔`;
  maxSub.textContent = Number.isFinite(ext.maxPosition.ms) ? fmtSnapshotTime(ext.maxPosition.ms) : '-';
  longEl.textContent = ext.longest.seconds ? formatDuration(ext.longest.seconds) : '-';
  longSub.textContent = ext.longest.ticket ? `#${ext.longest.ticket} ${fmtSnapshotTime(ext.longest.ms)}` : '-';
  if (maxCard) maxCard.onclick = () => focusTimeMs(ext.maxPosition.ms);
  if (longCard) longCard.onclick = () => focusTimeMs(ext.longest.ms);
}
function riskClass(used) {
  return used >= 80 ? 'riskBad' : used >= 50 ? 'riskWarn' : 'riskGood';
}
function tradeOpenMs(t) {
  return toMs(t["Open Time"]);
}
function tradeCloseMs(t) {
  return toMs(t["Close Time"]);
}
function tradeNet(t) {
  return (Number(t.Profit) || 0) + (Number(t.Commission) || 0) + (Number(t.Taxes) || 0) + (Number(t.Swap) || 0);
}
function contractSizeForTrade(t) {
  const key = String(t.Item || '').toUpperCase();
  return Number(POSITION_SYMBOL_MULTIPLIERS[key] || POSITION_CONTRACT_SIZE);
}
function marginRatios(margin, equity) {
  const used = equity > 0 && margin > 0 ? margin / equity * 100 : 0;
  const level = margin > 0 ? equity / margin * 100 : Infinity;
  return {used, level};
}
function balanceEventsAtMs(ms) {
  return POSITION_BALANCE_EVENTS.reduce((sum, ev) => sum + (toMs(ev.time) <= ms ? Number(ev.delta || 0) : 0), 0);
}
function singleSymbolBalanceAtMs(ms) {
  const closedNet = trades.reduce((sum, t) => sum + (tradeCloseMs(t) <= ms ? tradeNet(t) : 0), 0);
  return POSITION_INITIAL_BALANCE + balanceEventsAtMs(ms) + closedNet;
}
function estimateMargin(t, markPrice, contractSize) {
  const symbolKey = String(t.Item || '').toUpperCase();
  const volume = Number(t.Volume) || 0;
  if (!volume || !contractSize || !POSITION_LEVERAGE) return 0;
  if (/^[A-Z]{6}$/.test(symbolKey) && symbolKey.startsWith('USD')) {
    return volume * 100000 / POSITION_LEVERAGE;
  }
  return Number(markPrice || 0) * volume * contractSize / POSITION_LEVERAGE;
}
function barsForSymbol(sym) {
  return DATA.barsBySymbol[String(sym || '').toUpperCase()] || DATA.barsBySymbol[sym] || [];
}
function barIndexForSymbol(symbolBars, ms) {
  if (!symbolBars.length) return -1;
  let lo = 0, hi = symbolBars.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const bt = toMs(symbolBars[mid].time);
    if (bt <= ms) lo = mid + 1; else hi = mid - 1;
  }
  return Math.max(0, Math.min(symbolBars.length - 1, hi));
}
function markPriceForTrade(t, ms) {
  const symbolBars = barsForSymbol(t.Item);
  const idx = barIndexForSymbol(symbolBars, ms);
  if (idx >= 0) return {price: Number(symbolBars[idx].close), time: symbolBars[idx].time, source: 'M1'};
  return {price: Number(t["Open Price"]) || 0, time: '', source: 'open'};
}
function balanceAtMs(ms) {
  const closedNet = DATA.trades.reduce((sum, t) => sum + (tradeCloseMs(t) <= ms ? tradeNet(t) : 0), 0);
  const balanceDelta = balanceEventsAtMs(ms);
  return POSITION_INITIAL_BALANCE + closedNet + balanceDelta;
}
function accountSnapshotAtIndex(idx) {
  if (!bars.length) return {rows: [], count: 0, volume: 0, floating: 0, balance: POSITION_INITIAL_BALANCE, equity: POSITION_INITIAL_BALANCE, margin: 0, used: 0, level: Infinity, price: 0, ms: 0};
  idx = Math.max(0, Math.min(bars.length - 1, Math.round(idx)));
  const b = bars[idx], ms = toMs(b.time), price = Number(b.close);
  const rows = DATA.trades.filter(t => tradeOpenMs(t) <= ms && tradeCloseMs(t) > ms).map(t => {
    const volume = Number(t.Volume) || 0;
    const open = Number(t["Open Price"]) || 0;
    const dir = t.Type === 'buy' ? 1 : -1;
    const contractSize = contractSizeForTrade(t);
    const mark = markPriceForTrade(t, ms);
    const floating = (mark.price - open) * dir * volume * contractSize;
    const margin = estimateMargin(t, mark.price, contractSize);
    return {...t, markPrice: mark.price, markTime: mark.time, markSource: mark.source, contractSize, floating, margin, holdingMin: (ms - tradeOpenMs(t)) / 60000};
  });
  const floating = rows.reduce((sum, row) => sum + row.floating, 0);
  const margin = rows.reduce((sum, row) => sum + row.margin, 0);
  const balance = balanceAtMs(ms);
  const equity = balance + floating;
  const ratios = marginRatios(margin, equity);
  const used = ratios.used, level = ratios.level;
  return {rows, count: rows.length, volume: rows.reduce((sum, row) => sum + Number(row.Volume || 0), 0), floating, balance, equity, margin, used, level, price, ms};
}
function quoteGaps() {
  // Use intervals calculated from the full M1 cache; compressed display bars
  // are intentionally sparse and must not be interpreted as market gaps.
  const stored = DATA.quoteGapsBySymbol && (DATA.quoteGapsBySymbol[symbol] || DATA.quoteGapsBySymbol[String(symbol || '').toUpperCase()]);
  if (Array.isArray(stored)) {
    return stored.map(g => ({
      startMs: toMs(g.start),
      endMs: toMs(g.end),
      minutes: Number(g.minutes) || 0,
    })).filter(g => Number.isFinite(g.startMs) && Number.isFinite(g.endMs) && g.endMs > g.startMs && g.minutes > QUOTE_GAP_MINUTES);
  }
  const gaps = [];
  for (let i = 1; i < bars.length; i++) {
    const prev = toMs(bars[i - 1].time), next = toMs(bars[i].time);
    const minutes = (next - prev) / 60000;
    if (minutes > QUOTE_GAP_MINUTES) gaps.push({startIdx: i - 1, endIdx: i, startMs: prev, endMs: next, minutes});
  }
  return gaps;
}
function gapLabel(minutes) {
  if (minutes >= 1440) return `停盘 ${(minutes / 1440).toFixed(1)}天`;
  if (minutes >= 60) return `停盘 ${(minutes / 60).toFixed(1)}h`;
  return `停盘 ${Math.round(minutes)}m`;
}
function drawQuoteGaps(pad, plotW, plotH, xScale, xMsScale) {
  if (!showNoQuoteTime) return;
  ensureTimeView();
  const visible = quoteGaps().filter(g => g.endMs >= timeViewStartMs && g.startMs <= timeViewEndMs);
  if (!visible.length) return;
  ctx.save();
  ctx.font = '11px Arial';
  visible.forEach(g => {
    const x1 = Math.max(pad.l, xMsScale(g.startMs));
    const x2 = Math.min(pad.l + plotW, xMsScale(g.endMs));
    const width = Math.max(2, x2 - x1);
    const x = Math.max(pad.l, Math.min(pad.l + plotW - width, x1));
    const alpha = g.minutes >= 1440 ? 0.18 : g.minutes >= 60 ? 0.13 : 0.09;
    ctx.fillStyle = `rgba(220,38,38,${alpha})`;
    ctx.fillRect(x, pad.t, width, plotH);
    ctx.strokeStyle = g.minutes >= 60 ? 'rgba(220,38,38,0.75)' : 'rgba(220,38,38,0.38)';
    ctx.setLineDash(g.minutes >= 60 ? [] : [3,3]);
    ctx.beginPath(); ctx.moveTo(x + width / 2, pad.t); ctx.lineTo(x + width / 2, pad.t + plotH); ctx.stroke();
    ctx.setLineDash([]);
    if (width >= 6 || g.minutes >= 60) {
      ctx.save();
      ctx.translate(x + width / 2 + 4, pad.t + 16);
      ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = '#dc2626';
      ctx.fillText(gapLabel(g.minutes), 0, 0);
      ctx.restore();
    }
  });
  ctx.restore();
}
function updatePositionSnapshotLegacy(ms) {
  if (!bars.length) return;
  const snap = snapshotAtIndex(indexForMs(ms));
  const set = (id, value, cls='') => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    el.className = 'v ' + cls;
  };
  set('posTime', fmtSnapshotTime(snap.ms));
  set('posCount', String(snap.count));
  set('posVolume', fmtMoney(snap.volume, 2));
  set('posFloating', fmtMoney(snap.floating, 2), snap.floating >= 0 ? 'riskGood' : 'riskBad');
  set('posMargin', fmtMoney(snap.margin, 2));
  set('posUsed', `${fmtMoney(snap.used, 1)}%`, riskClass(snap.used));
  set('posLevel', Number.isFinite(snap.level) ? `${fmtMoney(snap.level, 1)}%` : '∞', riskClass(snap.used));
  const rows = snap.rows.sort((a, b) => b.margin - a.margin);
  const cols = ["Ticket","Type","Volume","Open Time","Open Price","Mark Price","Floating","Margin","Holding"];
  let html = '<thead><tr>' + cols.map(c => `<th class="${["Ticket","Type","Open Time","Holding"].includes(c) ? 'left' : ''}">${c}</th>`).join('') + '</tr></thead><tbody>';
  if (!rows.length) {
    html += '<tr><td colspan="9" class="left">璇ユ椂鍒绘棤鎸佷粨</td></tr>';
  } else {
    html += rows.map(r => {
      const vals = {
        "Ticket": r.Ticket,
        "Type": r.Type,
        "Volume": fmtMoney(r.Volume, 2),
        "Open Time": r["Open Time"],
        "Open Price": fmtMoney(r["Open Price"], digits()),
        "Mark Price": fmtMoney(r.markPrice, digits()),
        "Floating": fmtMoney(r.floating, 2),
        "Margin": fmtMoney(r.margin, 2),
        "Holding": holdingText(r.holdingMin),
      };
      return '<tr>' + cols.map(c => {
        const cls = ["Ticket","Type","Open Time","Holding"].includes(c) ? 'left' : '';
        const style = c === 'Floating' ? ` style="color:${r.floating >= 0 ? '#16a34a' : '#dc2626'}"` : '';
        return `<td class="${cls}"${style}>${vals[c] ?? ''}</td>`;
      }).join('') + '</tr>';
    }).join('');
  }
  html += '</tbody>';
  const table = document.getElementById('positionTable');
  if (table) table.innerHTML = html;
  const head = document.getElementById('positionPanelStatus');
  if (head) head.textContent = `标记价格 ${fmtMoney(snap.price, digits())}；Balance估算 ${fmtMoney(snap.balance, 2)}；Equity估算 ${fmtMoney(snap.equity, 2)}。`;
}
function drawPositionPanel(pad, plotW, top, height, xScale) {
  ctx.save();
  ctx.fillStyle = 'rgba(248,250,252,0.96)';
  ctx.fillRect(pad.l, top, plotW, height);
  ctx.strokeStyle = '#dbe4ee';
  ctx.strokeRect(pad.l, top, plotW, height);
  const vb = visibleBars();
  if (!vb.length) { ctx.restore(); return; }
  const bounds = visibleIndexBounds();
  const cacheKey = `${symbol}|${bounds.s}|${bounds.e}|${Math.round(plotW)}|${showNoQuoteTime ? Math.round(timeViewStartMs || 0) + ':' + Math.round(timeViewEndMs || 0) : 'compressed'}`;
  let points = positionPanelCacheKey === cacheKey && positionPanelCache ? positionPanelCache.points : null;
  if (!points) {
    const maxPoints = Math.max(24, Math.min(180, Math.floor(plotW / 8)));
    const step = Math.max(1, Math.ceil(vb.length / maxPoints));
    points = [];
    for (let i = 0; i < vb.length; i += step) {
      const idx = vb[i][1], snap = cachedSnapshotAtIndex(idx);
      points.push({idx, used: snap.used, count: snap.count});
    }
    const lastIdx = vb[vb.length - 1][1];
    if (!points.length || points[points.length - 1].idx !== lastIdx) {
      const snap = cachedSnapshotAtIndex(lastIdx);
      points.push({idx: lastIdx, used: snap.used, count: snap.count});
    }
    positionPanelCacheKey = cacheKey;
    positionPanelCache = {points};
  }
  const maxUsed = Math.max(10, ...points.map(p => p.used), 80);
  const maxCount = Math.max(1, ...points.map(p => p.count));
  const chartTop = top + 30, chartBottom = top + height - 22;
  const yUsed = v => chartTop + (maxUsed - v) / maxUsed * (chartBottom - chartTop);
  const yCount = v => chartTop + (maxCount - v) / maxCount * (chartBottom - chartTop);
  ctx.font = '11px Arial';
  ctx.textBaseline = 'alphabetic';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#f59e0b';
  ctx.fillText('Margin/Equity %', pad.l + 8, top + 15);
  ctx.textAlign = 'right';
  ctx.fillStyle = '#2563eb';
  ctx.fillText('Open positions', pad.l + plotW - 8, top + 15);
  ctx.textAlign = 'left';
  [0, 50, 80, Math.ceil(maxUsed)].filter((v, i, arr) => v <= maxUsed && arr.indexOf(v) === i).forEach(level => {
    if (level <= maxUsed) {
      const yy = yUsed(level);
      ctx.strokeStyle = level === 0 ? '#cbd5e1' : level >= 80 ? 'rgba(220,38,38,0.45)' : 'rgba(245,158,11,0.35)';
      ctx.setLineDash(level === 0 ? [] : [5,4]);
      ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(pad.l + plotW, yy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = level >= 80 ? '#dc2626' : '#f59e0b';
      ctx.fillText(level + '%', pad.l + 4, Math.max(top + 12, yy - 3));
    }
  });
  [0, Math.ceil(maxCount / 2), maxCount].filter((v, i, arr) => arr.indexOf(v) === i).forEach(count => {
    const yy = yCount(count);
    ctx.fillStyle = '#2563eb';
    ctx.textAlign = 'right';
    ctx.fillText(String(count), pad.l + plotW - 8, Math.max(top + 28, yy + 4));
    ctx.textAlign = 'left';
  });
  ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((p, i) => { const xx = xScale(p.idx), yy = yUsed(p.used); if (i) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy); });
  ctx.stroke();
  ctx.strokeStyle = '#2563eb'; ctx.lineWidth = 1.6; ctx.beginPath();
  points.forEach((p, i) => { const xx = xScale(p.idx), yy = yCount(p.count); if (i) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy); });
  ctx.stroke();
  ctx.textBaseline = 'alphabetic';
  ctx.textAlign = 'left';
  ctx.restore();
}

function updatePositionSnapshot(ms) {
  if (!bars.length) return;
  const snap = cachedSnapshotAtIndex(indexForMs(ms));
  const set = (id, value, cls='') => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    el.className = 'v ' + cls;
  };
  set('posTime', fmtSnapshotTime(snap.ms));
  set('posCount', String(snap.count));
  set('posVolume', fmtMoney(snap.volume, 2));
  set('posFloating', fmtMoney(snap.floating, 2), snap.floating >= 0 ? 'riskGood' : 'riskBad');
  set('posMargin', fmtMoney(snap.margin, 2));
  set('posUsed', `${fmtMoney(snap.used, 1)}%`, riskClass(snap.used));
  set('posLevel', Number.isFinite(snap.level) ? `${fmtMoney(snap.level, 1)}%` : '∞', riskClass(snap.used));
  updatePositionExtremes();

  const rows = snap.rows.sort((a, b) => b.margin - a.margin);
  const cols = ["Ticket","Type","Volume","Open Time","Open Price","Mark Price","Floating","Margin","Holding"];
  let html = '<thead><tr>' + cols.map(c => `<th class="${["Ticket","Type","Open Time","Holding"].includes(c) ? 'left' : ''}">${c}</th>`).join('') + '</tr></thead><tbody>';
  if (!rows.length) {
    html += '<tr><td colspan="9" class="left">该时刻无持仓</td></tr>';
  } else {
    html += rows.map(r => {
      const vals = {
        "Ticket": r.Ticket,
        "Type": r.Type,
        "Volume": fmtMoney(r.Volume, 2),
        "Open Time": r["Open Time"],
        "Open Price": fmtMoney(r["Open Price"], digits()),
        "Mark Price": fmtMoney(r.markPrice, digits()),
        "Floating": fmtMoney(r.floating, 2),
        "Margin": fmtMoney(r.margin, 2),
        "Holding": holdingText(r.holdingMin),
      };
      return '<tr>' + cols.map(c => {
        const cls = ["Ticket","Type","Open Time","Holding"].includes(c) ? 'left' : '';
        const style = c === 'Floating' ? ` style="color:${r.floating >= 0 ? '#16a34a' : '#dc2626'}"` : '';
        return `<td class="${cls}"${style}>${vals[c] ?? ''}</td>`;
      }).join('') + '</tr>';
    }).join('');
  }
  html += '</tbody>';
  const table = document.getElementById('positionTable');
  if (table) table.innerHTML = html;
  const head = document.getElementById('positionPanelStatus');
  if (head) head.textContent = `当前品种 ${symbol}；Balance ${fmtMoney(snap.balance, 2)}，Equity ${fmtMoney(snap.equity, 2)}；使用率=Margin/Equity，保证金比例=Equity/Margin。`;
}
"""


def inject_fused_features(html: str) -> str:
    html = html.replace("</style>", EXTRA_CSS + "\n</style>")
    html = html.replace(
        '<button id="fitTrades">只看交易区间</button>',
        '<button id="fitTrades">只看交易区间</button>\n'
        '<button id="toggleNoQuoteTime" title="开启后按真实时间展开周末和无报价区间，并用红色标出">显示周末/停盘</button>',
        1,
    )
    html = html.replace(
        '<button id="panelVolume">手数</button>',
        '<button id="panelVolume">手数</button>\n<button id="panelPosition">仓位</button>\n<button id="barStackToggle" title="切换底部 Profit 柱的单独或重叠合并显示">Profit柱：单独</button>',
        1,
    )
    html = html.replace(
        '<span><i class="sw" style="background:#16a34a"></i>买入开仓</span>',
        '<span><i class="sw" style="background:#111827;clip-path:polygon(50% 0,0 100%,100% 100%)"></i>买入开仓 ▲</span>',
        1,
    )
    html = html.replace(
        '<span><i class="sw" style="background:#dc2626"></i>卖出开仓</span>',
        '<span><i class="sw" style="background:#111827;clip-path:polygon(0 0,100% 0,50% 100%)"></i>卖出开仓 ▼</span>',
        1,
    )
    html = html.replace(
        '<span><i class="sw" style="background:#3b82f6"></i>手数柱</span>',
        '<span><i class="sw" style="background:#3b82f6"></i>手数柱</span>\n'
        '<span><i class="sw" style="background:#f59e0b"></i>仓位使用率</span>\n'
        '<span><i class="sw" style="background:#2563eb"></i>持仓笔数</span>\n'
        '<span><i class="sw" style="background:rgba(220,38,38,0.28)"></i>停盘/无报价</span>',
        1,
    )
    html = html.replace(
        '<div class="metric"><div class="k">当前显示订单</div><div class="v" id="shownCount">0</div></div>',
        '<div class="metric"><div class="k">当前显示订单</div><div class="v" id="shownCount">0</div><div class="metricSub">均持仓 <span id="shownAvgHold">-</span> / 全局 <span id="globalAvgHold">-</span></div></div>',
        1,
    )
    html = html.replace(
        '<div class="tableWrap"><table id="tradeTable"></table></div>',
        '''<div class="positionSnapshot">
<div class="metric"><div class="k">快照时刻</div><div class="v" id="posTime">-</div></div>
<div class="metric"><div class="k">持仓笔数</div><div class="v" id="posCount">-</div></div>
<div class="metric"><div class="k">总手数</div><div class="v" id="posVolume">-</div></div>
<div class="metric"><div class="k">浮动盈亏</div><div class="v" id="posFloating">-</div></div>
<div class="metric"><div class="k">占用保证金</div><div class="v" id="posMargin">-</div></div>
<div class="metric"><div class="k">使用率 / 保证金比例</div><div class="v"><span id="posUsed">-</span> / <span id="posLevel">-</span></div></div>
<div class="metric clickable" id="posMaxPositionJump"><div class="k">最大仓位</div><div class="v" id="posMaxPosition">-</div><div class="metricSub" id="posMaxPositionSub">点击定位</div></div>
<div class="metric clickable" id="posLongestHoldJump"><div class="k">最长持仓</div><div class="v" id="posLongestHold">-</div><div class="metricSub" id="posLongestHoldSub">点击定位</div></div>
</div>
<div class="positionPanel">
  <div class="positionPanelHead">点击图表查看该时刻仓位 <span id="positionPanelStatus"></span></div>
  <div class="positionTableWrap"><table id="positionTable"></table></div>
</div>
<div class="tableWrap" data-role="trades"><table id="tradeTable"></table></div>''',
        1,
    )
    html = html.replace(
        "  const s = Math.max(0, Math.floor(viewStart)), e = Math.min(bars.length - 1, Math.floor(viewEnd));\n  statusEl.textContent = `${bars[s].time} - ${bars[e].time} | 可见K线 ${e - s + 1} / ${bars.length} | 过滤后 ${allFiltered.length} | 可见交易 ${vt.length} | 实际显示 ${shown.length}`;",
        "  const {s, e} = visibleIndexBounds();\n  const rangeText = showNoQuoteTime ? `${fmtSnapshotTime(timeViewStartMs)} - ${fmtSnapshotTime(timeViewEndMs)}` : `${bars[s].time} - ${bars[e].time}`;\n  statusEl.textContent = `${rangeText} | ${showNoQuoteTime ? '真实时间轴，周末/停盘已展开' : '压缩报价轴'} | 可见K线 ${e - s + 1} / ${bars.length} | 过滤后 ${allFiltered.length} | 可见交易 ${vt.length} | 实际显示 ${shown.length}`;",
        1,
    )
    html = html.replace(
        "document.getElementById('fitTrades').addEventListener('click', fitTrades);",
        """const fitTradesButton = document.getElementById('fitTrades');
fitTradesButton.addEventListener('click', fitTrades);
document.getElementById('toggleNoQuoteTime').addEventListener('click', () => {
  showNoQuoteTime = !showNoQuoteTime;
  const btn = document.getElementById('toggleNoQuoteTime');
  btn.classList.toggle('active', showNoQuoteTime);
  btn.textContent = showNoQuoteTime ? '隐藏周末/停盘' : '显示周末/停盘';
  if (showNoQuoteTime) {
    timeViewStartMs = barMs(Math.max(0, Math.floor(viewStart)));
    timeViewEndMs = barMs(Math.min(bars.length - 1, Math.ceil(viewEnd)));
    clampTimeView();
  } else {
    syncIndexViewFromTime();
    clampView();
  }
  draw();
});""",
        1,
    )
    html = html.replace("const DATA = ", EXTRA_JS + "\nconst DATA = ", 1)
    html = html.replace(
        "  viewStart = 0; viewEnd = Math.max(1, bars.length - 1);\n  const m = DATA.mappingBySymbol[symbol] || {};",
        "  viewStart = 0; viewEnd = Math.max(1, bars.length - 1);\n  timeViewStartMs = null; timeViewEndMs = null;\n  positionPanelCacheKey = ''; positionPanelCache = null; positionSnapshotCache.clear(); positionExtremeCacheKey = ''; positionExtremeCache = null;\n  const m = DATA.mappingBySymbol[symbol] || {};",
        1,
    )
    html = html.replace(
        """function setInputsFromView() {
  if (!bars.length) return;
  const s = Math.max(0, Math.floor(viewStart)), e = Math.min(bars.length - 1, Math.floor(viewEnd));
  windowStartInput.value = bars[s].time.slice(0, 16);
  windowEndInput.value = bars[e].time.slice(0, 16);
}""",
        """function setInputsFromView() {
  if (!bars.length) return;
  if (showNoQuoteTime) {
    ensureTimeView();
    windowStartInput.value = fmtInputTime(timeViewStartMs);
    windowEndInput.value = fmtInputTime(timeViewEndMs);
    return;
  }
  const s = Math.max(0, Math.floor(viewStart)), e = Math.min(bars.length - 1, Math.floor(viewEnd));
  windowStartInput.value = bars[s].time.slice(0, 16);
  windowEndInput.value = bars[e].time.slice(0, 16);
}""",
        1,
    )
    html = html.replace(
        """function applyWindow() {
  const start = parseTimeInput(windowStartInput.value), end = parseTimeInput(windowEndInput.value);
  if (!start || !end || !bars.length) return;
  const startIdx = findIndex(start), endIdx = findIndex(end);
  viewStart = Math.max(0, Math.min(startIdx, endIdx));
  viewEnd = Math.min(bars.length - 1, Math.max(startIdx, endIdx));
  clampView();
  draw(false);
}""",
        """function applyWindow() {
  const start = parseTimeInput(windowStartInput.value), end = parseTimeInput(windowEndInput.value);
  if (!start || !end || !bars.length) return;
  if (showNoQuoteTime) {
    const startMs = toMs(start), endMs = toMs(end);
    timeViewStartMs = Math.min(startMs, endMs);
    timeViewEndMs = Math.max(startMs, endMs);
    clampTimeView();
  } else {
    const startIdx = findIndex(start), endIdx = findIndex(end);
    viewStart = Math.max(0, Math.min(startIdx, endIdx));
    viewEnd = Math.min(bars.length - 1, Math.max(startIdx, endIdx));
    clampView();
  }
  draw(false);
}""",
        1,
    )
    html = html.replace(
        """function clampView() {
  const minSpan = 8;
  if (viewEnd - viewStart < minSpan) {
    const mid = (viewStart + viewEnd) / 2;
    viewStart = mid - minSpan / 2; viewEnd = mid + minSpan / 2;
  }
  const span = viewEnd - viewStart;
  if (viewStart < 0) { viewStart = 0; viewEnd = span; }
  if (viewEnd > bars.length - 1) { viewEnd = bars.length - 1; viewStart = viewEnd - span; }
  viewStart = Math.max(0, viewStart); viewEnd = Math.min(bars.length - 1, viewEnd);
}""",
        """function clampView() {
  if (showNoQuoteTime) { clampTimeView(); return; }
  const minSpan = 8;
  if (viewEnd - viewStart < minSpan) {
    const mid = (viewStart + viewEnd) / 2;
    viewStart = mid - minSpan / 2; viewEnd = mid + minSpan / 2;
  }
  const span = viewEnd - viewStart;
  if (viewStart < 0) { viewStart = 0; viewEnd = span; }
  if (viewEnd > bars.length - 1) { viewEnd = bars.length - 1; viewStart = viewEnd - span; }
  viewStart = Math.max(0, viewStart); viewEnd = Math.min(bars.length - 1, viewEnd);
}""",
        1,
    )
    html = html.replace(
        """function zoom(factor, anchorRatio=0.5) {
  const span = viewEnd - viewStart, anchor = viewStart + span * anchorRatio;
  const newSpan = Math.max(8, Math.min(bars.length - 1, span * factor));
  viewStart = anchor - newSpan * anchorRatio;
  viewEnd = anchor + newSpan * (1 - anchorRatio);
  clampView(); draw();
}""",
        """function zoom(factor, anchorRatio=0.5) {
  if (showNoQuoteTime) {
    ensureTimeView();
    const span = timeViewEndMs - timeViewStartMs, anchor = timeViewStartMs + span * anchorRatio;
    const first = barMs(0), last = barMs(bars.length - 1);
    const newSpan = Math.max(8 * 60000, Math.min(Math.max(8 * 60000, last - first), span * factor));
    timeViewStartMs = anchor - newSpan * anchorRatio;
    timeViewEndMs = anchor + newSpan * (1 - anchorRatio);
    clampTimeView(); draw();
    return;
  }
  const span = viewEnd - viewStart, anchor = viewStart + span * anchorRatio;
  const newSpan = Math.max(8, Math.min(bars.length - 1, span * factor));
  viewStart = anchor - newSpan * anchorRatio;
  viewEnd = anchor + newSpan * (1 - anchorRatio);
  clampView(); draw();
}""",
        1,
    )
    html = html.replace(
        "function reset() { viewStart = 0; viewEnd = Math.max(1, bars.length - 1); draw(); }",
        "function reset() { viewStart = 0; viewEnd = Math.max(1, bars.length - 1); timeViewStartMs = barMs(0); timeViewEndMs = barMs(bars.length - 1); draw(); }",
        1,
    )
    html = html.replace(
        """  viewStart = Math.max(0, Math.min(...idxs) - 20);
  viewEnd = Math.min(bars.length - 1, Math.max(...idxs) + 20);
  draw();""",
        """  viewStart = Math.max(0, Math.min(...idxs) - 20);
  viewEnd = Math.min(bars.length - 1, Math.max(...idxs) + 20);
  timeViewStartMs = barMs(viewStart);
  timeViewEndMs = barMs(viewEnd);
  draw();""",
        1,
    )
    html = html.replace(
        """function visibleBars() {
  const s = Math.max(0, Math.floor(viewStart)), e = Math.min(bars.length - 1, Math.ceil(viewEnd));
  return bars.slice(s, e + 1).map((b, i) => [b, s + i]);
}""",
        """function visibleBars() {
  const {s, e} = visibleIndexBounds();
  return bars.slice(s, e + 1).map((b, i) => [b, s + i]);
}""",
        1,
    )
    html = html.replace(
        "function visibleTrades() {\n  return filteredTrades().filter(t => (t.openIdx >= viewStart && t.openIdx <= viewEnd) || (t.closeIdx >= viewStart && t.closeIdx <= viewEnd));\n}",
        """function visibleTrades() {
  if (!showNoQuoteTime) {
    return filteredTrades().filter(t => (t.openIdx >= viewStart && t.openIdx <= viewEnd) || (t.closeIdx >= viewStart && t.closeIdx <= viewEnd));
  }
  ensureTimeView();
  return filteredTrades().filter(t => {
    const openMs = toMs(t["Open Time"]), closeMs = toMs(t["Close Time"]);
    return (openMs >= timeViewStartMs && openMs <= timeViewEndMs) || (closeMs >= timeViewStartMs && closeMs <= timeViewEndMs);
  });
}""",
        1,
    )
    html = html.replace(
        "const label = panelMode === 'volume' ? 'Volume' : 'Profit';",
        "if (panelMode === 'position') { drawPositionPanel(pad, plotW, top, height, xScale); return; }\n  const label = panelMode === 'volume' ? 'Volume' : 'Profit';",
    )
    html = html.replace(
        """    if (t.openIdx >= viewStart && t.openIdx <= viewEnd) {
      ctx.fillStyle = t.Type === 'buy' ? '#16a34a' : '#dc2626';
      ctx.beginPath(); ctx.arc(xo, yo, 5, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
    }""",
        """    if (xo >= pad.l && xo <= pad.l + plotW) {
      const size = 7;
      ctx.fillStyle = '#111827';
      ctx.beginPath();
      if (t.Type === 'buy') {
        ctx.moveTo(xo, yo - size);
        ctx.lineTo(xo - size, yo + size);
        ctx.lineTo(xo + size, yo + size);
      } else {
        ctx.moveTo(xo, yo + size);
        ctx.lineTo(xo - size, yo - size);
        ctx.lineTo(xo + size, yo - size);
      }
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
    }""",
        1,
    )
    html = html.replace(
        "    ctx.strokeStyle = '#7c3aed'; ctx.lineWidth = 1.6; ctx.setLineDash([5,4]);\n    ctx.beginPath(); ctx.moveTo(xo, yo); ctx.lineTo(xc, yc); ctx.stroke(); ctx.setLineDash([]);",
        "    const lineAlpha = shown.length > 120 ? 0.26 : shown.length > 60 ? 0.42 : 0.76;\n    ctx.strokeStyle = `rgba(124,58,237,${lineAlpha})`; ctx.lineWidth = shown.length > 120 ? 1.0 : 1.6; ctx.setLineDash([5,4]);\n    ctx.beginPath(); ctx.moveTo(xo, yo); ctx.lineTo(xc, yc); ctx.stroke(); ctx.setLineDash([]);",
        1,
    )
    html = re.sub(
        r"function drawBottomPanel\(rows, pad, plotW, top, height, xScale\) \{.*?\n\}\nfunction drawProfitPanel",
        """function drawBottomPanel(rows, pad, plotW, top, height, xScale) {
  if (panelMode === 'position') { drawPositionPanel(pad, plotW, top, height, xScale); return; }
  ctx.save();
  ctx.fillStyle = 'rgba(248,250,252,0.96)';
  ctx.fillRect(pad.l, top, plotW, height);
  ctx.strokeStyle = '#dbe4ee';
  ctx.strokeRect(pad.l, top, plotW, height);
  ctx.font = '12px Arial';
  const label = panelMode === 'volume' ? 'Volume' : 'Profit';
  const modeText = barStackMode === 'stack' ? '叠加' : '单独';
  ctx.fillStyle = '#4b5563';
  ctx.fillText(`${label} | ${modeText}`, pad.l + 8, top + 16);
  if (!rows.length) { ctx.restore(); return; }

  const makeGroups = (barWidth) => {
    const items = rows.map(t => {
      const idx = Number.isFinite(t.openIdx) ? t.openIdx : 0;
      const cx = xScale(idx);
      return {t, idx, cx, left: cx - barWidth / 2, right: cx + barWidth / 2};
    }).sort((a, b) => a.left - b.left);
    const groups = [];
    items.forEach(item => {
      let g = groups[groups.length - 1];
      if (!g || item.left > g.right + 0.75) {
        g = {idxSum: 0, count: 0, xSum: 0, left: item.left, right: item.right, rows: [], volume: 0, posProfit: 0, negProfit: 0};
        groups.push(g);
      } else {
        g.right = Math.max(g.right, item.right);
      }
      const p = Number(item.t.Profit) || 0;
      g.idxSum += item.idx;
      g.xSum += item.cx;
      g.count += 1;
      g.rows.push(item.t);
      g.volume += Math.max(0, Number(item.t.Volume) || 0);
      if (p >= 0) g.posProfit += p; else g.negProfit += p;
    });
    return groups
      .map(g => ({...g, idx: g.idxSum / Math.max(1, g.count), cx: g.xSum / Math.max(1, g.count)}))
      .sort((a, b) => a.cx - b.cx);
  };
  const bw = Math.max(5, Math.min(18, plotW / Math.max(1, rows.length) * 0.72));
  const groups = barStackMode === 'stack' ? makeGroups(bw) : [];

  if (panelMode === 'volume') {
    const values = rows.map(t => Math.max(0, Number(t.Volume) || 0));
    const maxVol = Math.max(0.01, ...values);
    const baseY = top + height - 22;
    ctx.strokeStyle = '#94a3b8';
    ctx.beginPath(); ctx.moveTo(pad.l, baseY); ctx.lineTo(pad.l + plotW, baseY); ctx.stroke();
    ctx.fillStyle = '#4b5563';
    ctx.fillText(maxVol.toFixed(2), pad.l + 8, top + 34);
    ctx.fillText('0', pad.l + 8, baseY - 4);
    rows.forEach(t => {
      const v = Math.max(0, Number(t.Volume) || 0);
      const h = v / maxVol * (height - 42);
      const cx = xScale(t.openIdx);
      if (cx < pad.l - bw || cx > pad.l + plotW + bw) return;
      ctx.fillStyle = 'rgba(59,130,246,0.86)';
      ctx.fillRect(cx - bw / 2, baseY - h, bw, Math.max(1, h));
    });
    ctx.fillStyle = '#4b5563';
    ctx.fillText(`当前显示 ${rows.length} 笔，手数柱保持单笔显示`, pad.l + 8, top + height - 7);
    ctx.restore();
    return;
  }

  const posValues = barStackMode === 'stack'
    ? groups.map(g => Math.max(0, Number(g.posProfit) || 0))
    : rows.map(t => Math.max(0, Number(t.Profit) || 0));
  const negValues = barStackMode === 'stack'
    ? groups.map(g => Math.abs(Math.min(0, Number(g.negProfit) || 0)))
    : rows.map(t => Math.abs(Math.min(0, Number(t.Profit) || 0)));
  const maxAbs = Math.max(1, ...posValues, ...negValues);
  const zeroY = top + height / 2;
  ctx.strokeStyle = '#64748b';
  ctx.setLineDash([5,4]);
  ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(pad.l + plotW, zeroY); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = '#4b5563';
  ctx.fillText(maxAbs.toFixed(2), pad.l + 8, top + 34);
  ctx.fillText('0', pad.l + 8, zeroY - 4);
  ctx.fillText((-maxAbs).toFixed(2), pad.l + 8, top + height - 24);
  if (barStackMode === 'stack') {
    groups.forEach(g => {
      const cx = g.cx;
      if (cx < pad.l - bw || cx > pad.l + plotW + bw) return;
      const posH = Math.max(0, Number(g.posProfit) || 0) / maxAbs * (height / 2 - 14);
      const negH = Math.abs(Math.min(0, Number(g.negProfit) || 0)) / maxAbs * (height / 2 - 14);
      if (posH > 0) {
        ctx.fillStyle = 'rgba(239,68,68,0.88)';
        ctx.fillRect(cx - bw / 2, zeroY - posH, bw, Math.max(1, posH));
      }
      if (negH > 0) {
        ctx.fillStyle = 'rgba(34,197,94,0.88)';
        ctx.fillRect(cx - bw / 2, zeroY, bw, Math.max(1, negH));
      }
    });
  } else {
    rows.forEach(t => {
      const p = Number(t.Profit) || 0;
      const h = Math.abs(p) / maxAbs * (height / 2 - 14);
      const cx = xScale(t.openIdx);
      if (cx < pad.l - bw || cx > pad.l + plotW + bw) return;
      const y = p >= 0 ? zeroY - h : zeroY;
      ctx.fillStyle = p >= 0 ? 'rgba(239,68,68,0.86)' : 'rgba(34,197,94,0.86)';
      ctx.fillRect(cx - bw / 2, y, bw, Math.max(1, h));
    });
  }
  ctx.fillStyle = '#4b5563';
  ctx.fillText(`当前显示 ${rows.length} 笔，Profit柱模式：${modeText}${barStackMode === 'stack' ? '（按当前屏幕重叠合并）' : ''}，红色为盈利，绿色为亏损`, pad.l + 8, top + height - 7);
  ctx.restore();
}
function drawProfitPanel""",
        html,
        count=1,
        flags=re.S,
    )
    html = html.replace(
        "  const x = idx => pad.l + (idx - viewStart) / (viewEnd - viewStart) * plotW;\n  const candleX = idx => x(idx);\n  const priceFromY = yy => hi - ((yy - pad.t) / plotH) * (hi - lo);\n  const indexFromX = xx => viewStart + ((xx - pad.l) / plotW) * (viewEnd - viewStart);",
        "  const x = idx => xForIndex(idx, pad, plotW);\n  const candleX = idx => x(idx);\n  const xMs = ms => timeToCanvasX(ms, pad, plotW);\n  const priceFromY = yy => hi - ((yy - pad.t) / plotH) * (hi - lo);\n  const indexFromX = xx => indexFromCanvasX(xx, pad, plotW);\n  const msFromX = xx => msFromCanvasX(xx, pad, plotW);",
        1,
    )
    html = html.replace(
        "  const x = idx => pad.l + (idx - viewStart) / (viewEnd - viewStart) * plotW;\n  const priceFromY = yy => hi - ((yy - pad.t) / plotH) * (hi - lo);\n  const indexFromX = xx => viewStart + ((xx - pad.l) / plotW) * (viewEnd - viewStart);",
        "  const x = idx => xForIndex(idx, pad, plotW);\n  const xMs = ms => timeToCanvasX(ms, pad, plotW);\n  const priceFromY = yy => hi - ((yy - pad.t) / plotH) * (hi - lo);\n  const indexFromX = xx => indexFromCanvasX(xx, pad, plotW);\n  const msFromX = xx => msFromCanvasX(xx, pad, plotW);",
        1,
    )
    html = html.replace(
        "ctx.fillStyle = '#fff'; ctx.fillRect(pad.l, pad.t, plotW, plotH);",
        "ctx.fillStyle = '#fff'; ctx.fillRect(pad.l, pad.t, plotW, plotH);\n  drawQuoteGaps(pad, plotW, plotH, x, xMs);",
        1,
    )
    html = html.replace(
        """  const span = viewEnd - viewStart, labelStep = Math.max(1, Math.ceil(span / 9));
  for (let i = Math.ceil(viewStart); i <= Math.floor(viewEnd); i += labelStep) ctx.fillText(bars[i].time.slice(5,16), x(i) - 28, H - 38);""",
        """  if (showNoQuoteTime) {
    ensureTimeView();
    const timeSpan = Math.max(1, timeViewEndMs - timeViewStartMs);
    const steps = 8;
    for (let k = 0; k <= steps; k++) {
      const ms = timeViewStartMs + timeSpan * k / steps;
      ctx.fillText(fmtAxisTime(ms), xMs(ms) - 34, H - 38);
    }
  } else {
    const span = viewEnd - viewStart, labelStep = Math.max(1, Math.ceil(span / 9));
    for (let i = Math.ceil(viewStart); i <= Math.floor(viewEnd); i += labelStep) ctx.fillText(bars[i].time.slice(5,16), x(i) - 28, H - 38);
  }
  const span = viewEnd - viewStart;""",
        1,
    )
    html = html.replace(
        "    const idx = Math.max(0, Math.min(bars.length - 1, Math.round(indexFromX(crosshair.x)))), cx = x(idx), cy = crosshair.y, price = priceFromY(cy);",
        "    const idx = Math.max(0, Math.min(bars.length - 1, Math.round(indexFromX(crosshair.x)))), crossMs = msFromX(crosshair.x), cx = showNoQuoteTime ? crosshair.x : x(idx), cy = crosshair.y, price = priceFromY(cy);",
        1,
    )
    html = html.replace(
        "    ctx.fillStyle = '#fff'; ctx.fillText(bars[idx].time.slice(5,16), xLabel + 8, crosshairBottom + 22); ctx.restore();",
        "    ctx.fillStyle = '#fff'; ctx.fillText(showNoQuoteTime ? fmtAxisTime(crossMs) : bars[idx].time.slice(5,16), xLabel + 8, crosshairBottom + 22); ctx.restore();",
        1,
    )
    html = html.replace(
        "canvas.addEventListener('mousedown', ev => { canvas.classList.add('dragging'); drag = {x:ev.clientX, start:viewStart, end:viewEnd}; });",
        """canvas.addEventListener('mousedown', ev => {
  canvas.classList.add('dragging');
  ensureTimeView();
  drag = {x:ev.clientX, start:viewStart, end:viewEnd, timeStart:timeViewStartMs, timeEnd:timeViewEndMs};
});""",
        1,
    )
    html = html.replace(
        """  const rect = canvas.getBoundingClientRect(), span = drag.end - drag.start, deltaPx = ev.clientX - drag.x;
  viewStart = drag.start - deltaPx / Math.max(1, rect.width - 96) * span;
  viewEnd = drag.end - deltaPx / Math.max(1, rect.width - 96) * span;
  clampView(); draw();""",
        """  const rect = canvas.getBoundingClientRect(), deltaPx = ev.clientX - drag.x;
  if (showNoQuoteTime) {
    const span = drag.timeEnd - drag.timeStart;
    timeViewStartMs = drag.timeStart - deltaPx / Math.max(1, rect.width - 96) * span;
    timeViewEndMs = drag.timeEnd - deltaPx / Math.max(1, rect.width - 96) * span;
    clampTimeView();
  } else {
    const span = drag.end - drag.start;
    viewStart = drag.start - deltaPx / Math.max(1, rect.width - 96) * span;
    viewEnd = drag.end - deltaPx / Math.max(1, rect.width - 96) * span;
    clampView();
  }
  draw();""",
        1,
    )
    html = html.replace(
        "document.getElementById('panelProfit').classList.add('active');\n  document.getElementById('panelVolume').classList.remove('active');",
        "document.getElementById('panelProfit').classList.add('active');\n  document.getElementById('panelVolume').classList.remove('active');\n  document.getElementById('panelPosition').classList.remove('active');",
        1,
    )
    html = html.replace(
        "document.getElementById('panelVolume').classList.add('active');\n  document.getElementById('panelProfit').classList.remove('active');",
        "document.getElementById('panelVolume').classList.add('active');\n  document.getElementById('panelProfit').classList.remove('active');\n  document.getElementById('panelPosition').classList.remove('active');",
        1,
    )
    html = html.replace(
        "displayLimitInput.addEventListener('input', () => draw(false));",
        """document.getElementById('panelPosition').addEventListener('click', () => {
  panelMode = 'position';
  document.getElementById('panelPosition').classList.add('active');
  document.getElementById('panelProfit').classList.remove('active');
  document.getElementById('panelVolume').classList.remove('active');
  draw(false);
});
canvas.addEventListener('click', ev => {
  if (drag) return;
  const rect = canvas.getBoundingClientRect();
  const padL = 72, padR = 24, plotW = rect.width - padL - padR;
  const pad = {l: padL, r: padR};
  const canvasX = ev.clientX - rect.left;
  selectedSnapshotMs = showNoQuoteTime ? msFromCanvasX(canvasX, pad, plotW) : toMs(bars[Math.max(0, Math.min(bars.length - 1, Math.round(indexFromCanvasX(canvasX, pad, plotW))))].time);
  updatePositionSnapshot(selectedSnapshotMs);
});
document.getElementById('barStackToggle').addEventListener('click', () => {
  barStackMode = barStackMode === 'stack' ? 'single' : 'stack';
  const btn = document.getElementById('barStackToggle');
  btn.textContent = barStackMode === 'stack' ? 'Profit柱：合并' : 'Profit柱：单独';
  btn.classList.toggle('active', barStackMode === 'stack');
  draw(false);
});
displayLimitInput.addEventListener('input', () => draw(false));""",
        1,
    )
    html = html.replace(
        "updateTable(shown); updateSummary(shown, s, e);",
        "updateTable(shown); updateSummary(shown, s, e); updatePositionSnapshot(selectedSnapshotMs || toMs(bars[Math.round((s + e) / 2)].time));",
        1,
    )
    html = html.replace(
        "  document.getElementById('shownCount').textContent = String(rows.length);\n  document.getElementById('shownProfit').textContent = `${total.toFixed(2)} / Net ${shownClosedPL.toFixed(2)}`;",
        "  document.getElementById('shownCount').textContent = String(rows.length);\n  const shownAvgHoldEl = document.getElementById('shownAvgHold');\n  const globalAvgHoldEl = document.getElementById('globalAvgHold');\n  if (shownAvgHoldEl) shownAvgHoldEl.textContent = avgHoldingText(rows);\n  if (globalAvgHoldEl) globalAvgHoldEl.textContent = avgHoldingText(trades);\n  document.getElementById('shownProfit').textContent = `${total.toFixed(2)} / Net ${shownClosedPL.toFixed(2)}`;",
        1,
    )
    return html


def inject_position_meta(html: str, meta: dict) -> str:
    marker = "const DATA = "
    idx = html.find(marker)
    if idx < 0:
        return html
    start = idx + len(marker)
    end = html.find(";\nconst canvas", start)
    if end < 0:
        return html
    payload = json.loads(html[start:end])
    payload["positionMeta"] = meta
    html = html[:start] + json.dumps(payload, ensure_ascii=False) + html[end:]
    init = """
POSITION_LEVERAGE = Number(DATA.positionMeta && DATA.positionMeta.leverage) || 500;
POSITION_INITIAL_BALANCE = Number(DATA.positionMeta && DATA.positionMeta.initialBalance) || 10000;
POSITION_BALANCE_EVENTS = (DATA.positionMeta && DATA.positionMeta.balanceEvents) || [];
POSITION_SYMBOL_MULTIPLIERS = (DATA.positionMeta && DATA.positionMeta.symbolMultipliers) || {};
"""
    return html.replace("const canvas = document.getElementById('chart');", init + "const canvas = document.getElementById('chart');", 1)


def main() -> None:
    from build_enhanced_trade_kline_from_cache import build_html, infer_stem, load_bars_for_symbol

    trades_path = TRADES
    stem = infer_stem(trades_path)
    account = stem.split("_", 1)[0]
    trades = pd.read_csv(trades_path, parse_dates=["Open Time", "Close Time"])
    mapping = json.loads(trades_path.with_name(f"{stem}_mapping.json").read_text(encoding="utf-8"))
    bars_by_symbol = {
        report_symbol: load_bars_for_symbol(trades_path.parent, stem, report_symbol, item)
        for report_symbol, item in mapping.items()
    }
    html = build_html(account, stem, trades, bars_by_symbol, mapping)
    report_html = OUT_DIR / f"ReportHistory-{account}.html"
    meta = load_position_meta(report_html, trades) if report_html.exists() else {
        "initialBalance": 10000.0,
        "leverage": 500.0,
        "balanceEvents": [],
        "symbolMultipliers": {},
        "reportHtml": "",
    }
    html = inject_fused_features(html)
    html = inject_position_meta(html, meta)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(OUT_HTML)


if __name__ == "__main__":
    main()
