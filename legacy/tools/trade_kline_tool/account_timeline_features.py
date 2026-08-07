"""Inject factual Balance/Credit replay controls into the standalone K-line HTML."""

from __future__ import annotations

import json
from typing import Any

_EVENT_FIELDS = (
    "eventIndex", "id", "timestamp", "kind", "category", "orderId", "positionId", "symbol", "comment",
    "deltaBalance", "deltaCredit", "realizedPnl", "balance", "credit", "equity", "equityStatus", "liquidation",
)
_CURVE_FIELDS = ("timestamp", "kind", "balance", "credit", "equity", "equityStatus")


def _compact_rows(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[list[Any]]:
    return [[row.get(field) for field in fields] for row in rows]


def _compact_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    """Store repetitive replay rows as ordered arrays until the artifact is idle."""

    return {
        "format": "kdesk-timeline-v1",
        "meta": {key: value for key, value in timeline.items() if key not in {"events", "curve"}},
        "eventFields": _EVENT_FIELDS,
        "events": _compact_rows(list(timeline.get("events") or []), _EVENT_FIELDS),
        "curveFields": _CURVE_FIELDS,
        "curve": _compact_rows(list(timeline.get("curve") or []), _CURVE_FIELDS),
    }

_CSS = """
.timelinePanel { margin-top:18px; border:1px solid #d1d5db; border-radius:8px; background:#fff; color:#111827; padding:16px; }
.timelineHead { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; }.timelineHead h2 { margin:0; color:#111827; font-size:20px; }.timelineHead small { display:block; margin-top:5px; color:#64748b; }
.timelineSummary { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin:14px 0; border:1px solid #d1d5db; border-radius:7px; overflow:hidden; }.timelineSummary div { min-height:70px; padding:11px 13px; border-left:1px solid #e5e7eb; background:#fff; }.timelineSummary div:nth-child(4n+1) { border-left:0; }.timelineSummary span,.timelineSummary b { display:block; }.timelineSummary span { color:#6b7280; font-size:12px; }.timelineSummary b { margin-top:7px; color:#111827; font-size:18px; }.timelineSummary b.positive { color:#059669; }.timelineSummary b.negative { color:#dc2626; }
.timelineNote { color:#64748b; font-size:12px; line-height:1.6; }
.timelineLiquidations { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:12px 0; padding:10px 12px; border:1px solid #fecaca; border-radius:6px; background:#fff1f2; }.timelineLiquidations[hidden] { display:none; }.timelineLiquidations b { color:#991b1b; font-size:12px; }.timelineLiquidations button { min-height:28px; padding:4px 8px; color:#991b1b; border-color:#fca5a5; background:#fff; font-size:12px; }.timelineLiquidations button:hover,.timelineLiquidations button:focus-visible { color:#7f1d1d; border-color:#dc2626; background:#fee2e2; }
.timelineEventsHead { display:flex; align-items:end; justify-content:space-between; gap:12px; margin:16px 0 8px; }.timelineEventsHead b { color:#111827; font-size:16px; }.timelineTableViewport { max-height:680px; overflow:auto; border:1px solid #d1d5db; border-radius:7px; background:#fff; }.timelineTableViewport .tableWrap { margin:0; overflow:visible; }.timelineTable { min-width:1280px; color:#111827; }.timelineTable th { position:sticky; top:0; z-index:2; color:#374151; background:#f3f4f6; }.timelineTable td { border-color:#e5e7eb; vertical-align:top; }.timelineTable td.event-order { color:#1d4ed8; }.timelineTable td.event-funds { color:#92400e; }.timelineTable tr.event-liquidation { background:#fff1f2; }.timelineTable .timelineSpacer td { height:0; min-height:0; padding:0 !important; border:0 !important; }.timelineTable .timelineKind { display:inline-flex; padding:3px 6px; border:1px solid #9ca3af; border-radius:4px; color:#374151; font-size:11px; white-space:nowrap; }.timelineTable .timelineKind.deposit,.timelineTable .timelineKind.bonus_grant,.timelineTable .timelineKind.negative_balance_clear { color:#047857; border-color:#6ee7b7; background:#ecfdf5; }.timelineTable .timelineKind.withdrawal,.timelineTable .timelineKind.bonus_remove { color:#b45309; border-color:#fcd34d; background:#fffbeb; }.timelineTable .timelineKind.internal_transfer { color:#6d28d9; border-color:#c4b5fd; background:#f5f3ff; }.timelineTable .timelineSub { display:block; margin-top:4px; color:#6b7280; font-size:11px; white-space:nowrap; }.timelineTable .timelineLiquidationLabel { color:#b91c1c; }.timelineTable button { padding:3px 6px; font-size:12px; }.timelineTable .timelineJump { margin-right:4px; color:#991b1b; border-color:#fca5a5; background:#fff; }.timelineTableStatus { margin-top:8px; color:#64748b; font-size:12px; text-align:right; }
@media (max-width:900px) { .timelineSummary { grid-template-columns:repeat(2,minmax(0,1fr)); }.timelineSummary div:nth-child(odd) { border-left:0; } } @media (max-width:620px) { .timelineSummary { grid-template-columns:1fr; }.timelineSummary div { border-left:0; border-top:1px solid #214f78; }.timelineSummary div:first-child { border-top:0; } }
"""


_HTML = """
<section class="timelinePanel" id="accountTimelinePanel">
  <div class="timelineHead"><div><h2>历史资金回溯</h2><small id="timelineCoverage">读取中</small></div><div class="timelineNote" id="timelineSource"></div></div>
  <div class="timelineSummary" id="timelineSummary"></div>
  <div class="timelineLiquidations" id="timelineLiquidations" hidden></div>
  <div class="timelineEventsHead"><b>资金与订单事件</b><span class="timelineNote" id="timelineEventNote"></span></div>
  <div class="timelineTableViewport" id="timelineTableViewport"><div class="tableWrap"><table class="timelineTable" id="timelineTable"></table></div></div>
  <div class="timelineTableStatus" id="timelineTableStatus"></div>
</section>
"""


_JS = r"""
(() => {
  const timelineNode = document.getElementById('accountTimelineData');
  const decodeTimeline = raw => {
    const decodeRows = (fields, rows) => (rows || []).map(values => Object.fromEntries((fields || []).map((field, index) => [field, values[index]])));
    if (!raw || raw.format !== 'kdesk-timeline-v1') return raw || {};
    return {...(raw.meta || {}), events:decodeRows(raw.eventFields, raw.events), curve:decodeRows(raw.curveFields, raw.curve)};
  };
  const startTimeline = () => {
  let timeline;
  try { timeline = decodeTimeline(JSON.parse(timelineNode?.textContent || '{}')); } catch (_) { return; }
  if (!Array.isArray(timeline.events)) return;
  const ROW_HEIGHT = 62;
  const VIRTUAL_BUFFER = 36;
  let virtualStart = -1, virtualEnd = -1, renderScheduled = false;
  const escTimeline = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => value == null || value === '' || !Number.isFinite(Number(value)) ? '数据不足' : Number(value).toFixed(2);
  const moneyClass = value => Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : '';
  const curve = (timeline.curve || []).filter(row => row.balance != null && row.credit != null && Number.isFinite(toMs(row.timestamp)));
  const curveTimes = curve.map(row => toMs(row.timestamp));
  const curveBarIndexes = curve.map(row => findIndexByMs(toMs(row.timestamp)));
  const lowerBoundTimelineTime = ms => {
    let low = 0, high = curveTimes.length;
    while (low < high) { const middle = (low + high) >> 1; if (curveTimes[middle] <= ms) low = middle + 1; else high = middle; }
    return low;
  };
  const lowerBoundTimelineIndex = value => {
    let low = 0, high = curveBarIndexes.length;
    while (low < high) { const middle = (low + high) >> 1; if (curveBarIndexes[middle] < value) low = middle + 1; else high = middle; }
    return low;
  };
  const stateAt = ms => {
    const index = lowerBoundTimelineTime(ms) - 1;
    return index >= 0 ? {...curve[index], known:true} : (timeline.openingState || {known:false, balance:null, credit:null});
  };
  const kindLabel = row => ({trade_open:'订单开仓',trade_close:'订单平仓',deposit:'外部入金',withdrawal:'外部出金',internal_transfer:'内部划转',bonus_grant:'Credit 增加',bonus_remove:'Credit 扣减',negative_balance_clear:'负余额清零',compensation:'补偿入账',cash_reversal:'资金冲正',other_balance:'余额调整',adjustment:'账务调整'})[row.kind] || row.kind || '其他';
  const valid = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const focusTimestamp = timestamp => { const ms = toMs(timestamp); if (Number.isFinite(ms)) focusTimeMs(ms); };
  const renderTimeline = (force = false) => {
    const events = timeline.events || [], viewport = document.getElementById('timelineTableViewport');
    const visibleStart = Math.max(0, Math.floor(viewport.scrollTop / ROW_HEIGHT) - VIRTUAL_BUFFER);
    const visibleEnd = Math.min(events.length, Math.ceil((viewport.scrollTop + viewport.clientHeight) / ROW_HEIGHT) + VIRTUAL_BUFFER);
    if (!force && visibleStart === virtualStart && visibleEnd === virtualEnd) return;
    virtualStart = visibleStart; virtualEnd = visibleEnd;
    const rows = events.slice(visibleStart, visibleEnd);
    document.getElementById('timelineTable').innerHTML = '<thead><tr><th>时间</th><th>事件</th><th>订单 / Deal</th><th>品种</th><th>备注</th><th>余额变化</th><th>Credit变化</th><th>实现盈亏</th><th>事件后余额</th><th>事件后Credit</th><th>权益状态</th><th></th></tr></thead><tbody>' + rows.map((row, index) => {
      const cls = row.liquidation ? 'event-liquidation' : '';
      const id = visibleStart + index;
      const liquidationButton = row.liquidation ? `<button type="button" data-timeline-liquidation="${id}">爆仓点位</button>` : '';
      return `<tr class="${cls}"><td>${escTimeline(row.timestamp)}</td><td class="event-${escTimeline(row.category)}"><span class="timelineKind ${escTimeline(row.kind)}">${escTimeline(kindLabel(row))}</span>${row.liquidation ? '<span class="timelineSub timelineLiquidationLabel">爆仓标记</span>' : ''}</td><td><b>${escTimeline(row.orderId || row.id || '-')}</b>${row.positionId ? `<span class="timelineSub">Position ${escTimeline(row.positionId)}</span>` : ''}</td><td>${escTimeline(row.symbol || '-')}</td><td>${escTimeline(row.comment || '-')}</td><td class="${moneyClass(row.deltaBalance)}">${money(row.deltaBalance)}</td><td class="${moneyClass(row.deltaCredit)}">${money(row.deltaCredit)}</td><td class="${moneyClass(row.realizedPnl)}">${money(row.realizedPnl)}</td><td>${money(row.balance)}</td><td>${money(row.credit)}</td><td>${escTimeline(row.equityStatus === 'authoritative_daily' ? '日快照' : row.equityStatus === 'authoritative_current' ? '当前快照' : row.equityStatus ? '无盘中快照' : '—')}</td><td>${liquidationButton}<button type="button" data-timeline-event="${id}">定位</button></td></tr>`;
    }).join('') + `<tr class="timelineSpacer"><td colspan="12" style="height:${Math.max(0, (events.length - visibleEnd) * ROW_HEIGHT)}px"></td></tr></tbody>`;
    const firstSpacer = `<tr class="timelineSpacer"><td colspan="12" style="height:${visibleStart * ROW_HEIGHT}px"></td></tr>`;
    document.querySelector('#timelineTable tbody').insertAdjacentHTML('afterbegin', firstSpacer);
  };
  const summary = timeline.summary || {};
  const coverage = timeline.coverage || {}, sourceLabel = [timeline.platform, timeline.server].filter(Boolean).join(' / ') || '当前选定路由';
  document.getElementById('timelineCoverage').textContent = `已回放 ${summary.eventCount || 0}/${summary.allEventCount || 0} 条资金与订单事件（开仓、平仓均按真实时间保留）`;
  document.getElementById('timelineSource').textContent = `来源：${sourceLabel}。完整读取 ${coverage.eventRows ?? summary.allEventCount ?? 0} 条订单与资金事件、${coverage.dailyAnchors ?? 0} 条日快照；余额和 Credit 按事件回放，权益不补造。`;
  const summaryItems = [['外部入金', summary.externalDeposit], ['外部出金', summary.externalWithdrawal], ['外部净入金', summary.externalNetDeposit], ['内部划转', summary.internalTransfer], ['Credit 增加', summary.bonusGranted], ['Credit 扣减', summary.bonusRemoved], ['负余额清零', summary.negativeBalanceCleared], ['爆仓标记', summary.liquidationCount]];
  document.getElementById('timelineSummary').innerHTML = summaryItems.map(([label, value], index) => `<div><span>${escTimeline(label)}${index === 7 ? '' : ` (${summary.currency || 'USD'})`}</span><b class="${index === 7 ? '' : moneyClass(index === 1 || index === 5 ? -Number(value || 0) : value)}">${index === 7 ? Number(value || 0) : money(value)}</b></div>`).join('');
  document.getElementById('timelineEventNote').textContent = '资金、开仓与平仓均按真实发生顺序逐笔展示；每行对应事件后的 Balance/Credit。';
  document.getElementById('timelineTableStatus').textContent = `共 ${summary.eventCount || 0} 条事件，滚动查看全部事件；表格按需渲染以保持流畅。`;
  const liquidationBox = document.getElementById('timelineLiquidations'), liquidations = timeline.liquidationPoints || [];
  liquidationBox.hidden = !liquidations.length;
  liquidationBox.innerHTML = liquidations.length ? `<b>爆仓点位 ${liquidations.length} 个</b>${liquidations.map(point => `<button type="button" data-timeline-liquidation-time="${escTimeline(point.timestamp || '')}">${escTimeline(`${point.label || '爆仓标记'} · ${point.timestamp || '-'} · ${point.orderId || point.positionId || '-'}`)}</button>`).join('')}` : '';
  liquidationBox.querySelectorAll('[data-timeline-liquidation-time]').forEach(node => node.addEventListener('click', () => focusTimestamp(node.dataset.timelineLiquidationTime)));
  document.getElementById('timelineTableViewport').addEventListener('scroll', () => {
    if (renderScheduled) return;
    renderScheduled = true;
    requestAnimationFrame(() => { renderScheduled = false; renderTimeline(); });
  });
  document.getElementById('timelineTable').addEventListener('click', event => {
    const button = event.target.closest('[data-timeline-event],[data-timeline-liquidation]');
    if (!button) return;
    const index = Number(button.dataset.timelineEvent ?? button.dataset.timelineLiquidation);
    const row = (timeline.events || [])[index];
    const ms = row ? toMs(row.timestamp) : NaN;
    if (Number.isFinite(ms)) focusTimeMs(ms);
  });
  renderTimeline(true);

  const originalBottomPanel = drawKdeskBottomPanel;
  drawKdeskBottomPanel = function(rows, pad, plotW, top, height, xScale) {
    if (panelMode !== 'funds') return originalBottomPanel(rows, pad, plotW, top, height, xScale);
    ctx.save();
    ctx.fillStyle = 'rgba(248,250,252,0.96)'; ctx.fillRect(pad.l, top, plotW, height);
    ctx.strokeStyle = '#dbe4ee'; ctx.strokeRect(pad.l, top, plotW, height);
    if (!curve.length) { ctx.fillStyle='#64748b'; ctx.font='12px Arial'; ctx.fillText('资金回放：当前时间范围没有可确认的 Balance / Credit 数据', pad.l + 10, top + 22); ctx.restore(); return; }
    const first = lowerBoundTimelineIndex(viewStart - 1), afterLast = lowerBoundTimelineIndex(viewEnd + 1);
    const start = Math.max(0, Math.min(first, curve.length - 1)), end = Math.max(start + 1, Math.min(curve.length, afterLast));
    const maxPoints = Math.max(48, Math.floor(plotW));
    const step = Math.max(1, Math.ceil((end - start) / maxPoints));
    const shown = [];
    for (let index = start; index < end; index += step) shown.push({...curve[index], idx:curveBarIndexes[index]});
    if (shown[shown.length - 1]?.idx !== curveBarIndexes[end - 1]) shown.push({...curve[end - 1], idx:curveBarIndexes[end - 1]});
    const values = shown.flatMap(row => [Number(row.balance), Number(row.credit)]);
    const lo = Math.min(...values), hi = Math.max(...values), span = Math.max(1, hi - lo);
    const chartTop = top + 28, chartBottom = top + height - 22;
    const y = value => chartBottom - (Number(value) - lo) / span * (chartBottom - chartTop);
    ctx.font='11px Arial'; ctx.fillStyle='#2563eb'; ctx.fillText('Balance', pad.l + 8, top + 15); ctx.fillStyle='#d97706'; ctx.fillText('Credit', pad.l + 72, top + 15);
    ctx.fillStyle='#64748b'; ctx.fillText(`${lo.toFixed(2)} ~ ${hi.toFixed(2)}`, pad.l + 136, top + 15);
    const line = (field, color) => { ctx.strokeStyle=color; ctx.lineWidth=2; ctx.beginPath(); shown.forEach((row, i) => { const xx=xScale(row.idx), yy=y(row[field]); if (i) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy); }); ctx.stroke(); };
    line('balance', '#2563eb'); line('credit', '#d97706');
    (timeline.liquidationPoints || []).forEach(point => { const idx=findIndexByMs(toMs(point.timestamp)); if (idx < viewStart || idx > viewEnd) return; const xx=xScale(idx); ctx.fillStyle='#dc2626'; ctx.beginPath(); ctx.arc(xx, chartTop + 8, 4, 0, Math.PI * 2); ctx.fill(); });
    ctx.restore();
  };

  canvas.addEventListener('click', event => {
    if (panelMode !== 'funds' || drag) return;
    const rect = canvas.getBoundingClientRect(), pad = {l:72, r:24, t:20, b:74};
    const plotW = rect.width - pad.l - pad.r, profitH = 118, profitGap = 30;
    const plotH = Math.max(280, rect.height - pad.t - pad.b - profitH - profitGap);
    const markerY = pad.t + plotH + profitGap + 36;
    const x = event.clientX - rect.left, y = event.clientY - rect.top;
    if (Math.abs(y - markerY) > 12) return;
    const marker = (timeline.liquidationPoints || []).map(point => {
      const idx = findIndexByMs(toMs(point.timestamp));
      return {point, x:pad.l + (idx - viewStart) / Math.max(1, viewEnd - viewStart) * plotW};
    }).find(item => Math.abs(item.x - x) <= 12);
    const at = marker ? toMs(marker.point.timestamp) : NaN;
    if (Number.isFinite(at)) focusTimeMs(at);
  });

  const originalPositionPanel = drawPositionPanel;
  drawPositionPanel = function(pad, plotW, top, height, xScale) {
    const vb = visibleBars();
    ctx.save(); ctx.fillStyle='rgba(248,250,252,0.96)'; ctx.fillRect(pad.l, top, plotW, height); ctx.strokeStyle='#dbe4ee'; ctx.strokeRect(pad.l, top, plotW, height);
    if (!vb.length) { ctx.restore(); return; }
    const step = Math.max(1, Math.ceil(vb.length / Math.max(24, Math.min(180, Math.floor(plotW / 8)))));
    const points = [];
    for (let i=0; i<vb.length; i+=step) { const idx=vb[i][1], snap=cachedSnapshotAtIndex(idx); points.push({idx,count:snap.count,volume:snap.volume}); }
    const last = vb[vb.length - 1][1]; if (!points.length || points[points.length - 1].idx !== last) { const snap=cachedSnapshotAtIndex(last); points.push({idx:last,count:snap.count,volume:snap.volume}); }
    const maxCount=Math.max(1,...points.map(item => item.count)), maxVolume=Math.max(0.01,...points.map(item => item.volume));
    const chartTop=top+30, chartBottom=top+height-22, yCount=value => chartBottom-(value/maxCount)*(chartBottom-chartTop), yVolume=value => chartBottom-(value/maxVolume)*(chartBottom-chartTop);
    ctx.font='11px Arial'; ctx.fillStyle='#2563eb'; ctx.fillText('持仓笔数（当前图表订单）', pad.l+8, top+15); ctx.textAlign='right'; ctx.fillStyle='#d97706'; ctx.fillText('开放手数', pad.l+plotW-8, top+15); ctx.textAlign='left';
    const line=(field, color, mapper) => { ctx.strokeStyle=color; ctx.lineWidth=2; ctx.beginPath(); points.forEach((item, i) => { const xx=xScale(item.idx), yy=mapper(item[field]); if(i)ctx.lineTo(xx,yy);else ctx.moveTo(xx,yy); }); ctx.stroke(); };
    line('count','#2563eb',yCount); line('volume','#d97706',yVolume);
    ctx.fillStyle='#64748b'; ctx.fillText('历史保证金率没有平台盘中快照，未展示估算比例', pad.l+8, top+height-7); ctx.restore();
  };
  const originalPositionSnapshot = updatePositionSnapshot;
  updatePositionSnapshot = function(ms) {
    originalPositionSnapshot(ms);
    const state = stateAt(ms), fact = document.getElementById('posFundingFact'), head = document.getElementById('positionPanelStatus');
    if (fact) fact.textContent = state.known ? `Balance ${money(state.balance)} / Credit ${money(state.credit)}` : 'Balance / Credit：数据不足';
    const margin = document.getElementById('posMargin'), used = document.getElementById('posUsed'), level = document.getElementById('posLevel');
    if (margin) margin.textContent = '未回放'; if (used) used.textContent = '数据不足'; if (level) level.textContent = '数据不足';
    if (head) head.textContent = state.known ? `账面 Balance ${money(state.balance)}，Credit ${money(state.credit)}；持仓笔数和手数来自当前图表订单，盘中保证金率无平台快照，未作推算。` : '当前时刻没有可确认的 Balance / Credit；持仓笔数和手数仍来自当前图表订单。';
  };
  const fundingFact = document.getElementById('posFundingFact');
  if (fundingFact) fundingFact.textContent = timeline.openingState?.known ? `Balance ${money(timeline.openingState.balance)} / Credit ${money(timeline.openingState.credit)}` : 'Balance / Credit：数据不足';
  const fundsButton = document.getElementById('panelFunds');
  if (fundsButton) fundsButton.addEventListener('click', () => { panelMode='funds'; fundsButton.classList.add('active'); document.getElementById('panelProfit').classList.remove('active'); document.getElementById('panelVolume').classList.remove('active'); document.getElementById('panelPosition').classList.remove('active'); scheduleDraw(false); });
  };
  if (typeof window.requestIdleCallback === 'function') window.requestIdleCallback(startTimeline, {timeout:250});
  else window.setTimeout(startTimeline, 0);
})();
"""


def inject_account_timeline(html: str, timeline: dict[str, Any]) -> str:
    """Attach a self-contained read-only funds replay to an already enhanced chart."""

    marker = "const DATA = "
    start = html.find(marker)
    if start < 0:
        return html
    data_start = start + len(marker)
    data_end = html.find(";\nconst canvas", data_start)
    if data_end < 0:
        return html
    payload = json.loads(html[data_start:data_end])
    html = html[:data_start] + json.dumps(payload, ensure_ascii=False, allow_nan=True) + html[data_end:]
    html = html.replace("</style>", _CSS + "\n</style>", 1)
    html = html.replace('<button id="panelPosition">仓位</button>', '<button id="panelPosition">仓位</button><button id="panelFunds">资金</button>', 1)
    html = html.replace(
        '<div class="metric"><div class="k">占用保证金</div><div class="v" id="posMargin">-</div></div>',
        '<div class="metric"><div class="k">账面余额 / Credit</div><div class="v" id="posFundingFact">读取中</div><div class="metricSub">来自账户资金流水回放</div></div><div class="metric"><div class="k">占用保证金</div><div class="v" id="posMargin">-</div></div>',
        1,
    )
    table_marker = '<div class="tableWrap" data-role="trades"><table id="tradeTable"></table></div>'
    html = html.replace(table_marker, table_marker + _HTML, 1)
    compact_timeline = json.dumps(_compact_timeline(timeline), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    safe_timeline = compact_timeline.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    timeline_data = '<script id="accountTimelineData" type="application/json">' + safe_timeline + "</script>"
    return html.replace("</body>", timeline_data + "<script>" + _JS + "</script></body>", 1)
