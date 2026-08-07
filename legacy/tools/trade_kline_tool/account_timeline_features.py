"""Inject factual Balance/Credit replay controls into the standalone K-line HTML."""

from __future__ import annotations

import json
from typing import Any

_CSS = """
.timelinePanel { margin-top:18px; border:1px solid #1e5b8b; border-radius:8px; background:#061a33; color:#dcecff; padding:16px; }
.timelineHead { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; }.timelineHead h2 { margin:0; color:#f3f8ff; font-size:20px; }.timelineHead small { display:block; margin-top:5px; color:#82a5c9; }
.timelineSummary { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin:14px 0; border:1px solid #214f78; border-radius:7px; overflow:hidden; }.timelineSummary div { min-height:70px; padding:11px 13px; border-left:1px solid #214f78; background:#071a31; }.timelineSummary div:nth-child(4n+1) { border-left:0; }.timelineSummary span,.timelineSummary b { display:block; }.timelineSummary span { color:#88a8ca; font-size:12px; }.timelineSummary b { margin-top:7px; color:#eaf6ff; font-size:18px; }.timelineSummary b.positive { color:#38d7a0; }.timelineSummary b.negative { color:#ff6373; }
.timelineChart { min-height:278px; padding:12px; border:1px solid #214f78; border-radius:7px; background:#06162b; }.timelineChartHead { display:flex; align-items:end; justify-content:space-between; gap:12px; margin-bottom:8px; }.timelineChartHead b { color:#eaf6ff; font-size:16px; }.timelineChartHead span,.timelineNote { color:#82a5c9; font-size:12px; line-height:1.6; }.timelineChart svg { display:block; width:100%; height:220px; overflow:visible; }.timelineGrid { stroke:#16436c; stroke-width:1; }.timelineBalance { fill:none; stroke:#20b9ff; stroke-width:2.5; vector-effect:non-scaling-stroke; }.timelineCredit { fill:none; stroke:#e5af48; stroke-width:2; vector-effect:non-scaling-stroke; }.timelineLiquidation { fill:#ff5d66; stroke:#ffd4d7; stroke-width:1.5; vector-effect:non-scaling-stroke; cursor:pointer; }.timelineLiquidation:hover,.timelineLiquidation:focus { fill:#ff8790; stroke:#fff; outline:none; }
.timelineLiquidations { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:12px 0; padding:10px 12px; border:1px solid #7c3945; border-radius:6px; background:#28131b; }.timelineLiquidations[hidden] { display:none; }.timelineLiquidations b { color:#ffd9dc; font-size:12px; }.timelineLiquidations button { min-height:28px; padding:4px 8px; color:#ffd9dc; border-color:#a94958; background:#4a1c27; font-size:12px; }.timelineLiquidations button:hover,.timelineLiquidations button:focus-visible { color:#fff; border-color:#ff7a85; background:#682430; }
.timelineEventsHead { display:flex; align-items:end; justify-content:space-between; gap:12px; margin:16px 0 8px; }.timelineEventsHead b { color:#eaf6ff; font-size:16px; }.timelineTable { min-width:1280px; color:#dcecff; }.timelineTable th { color:#91b4d7; background:#08213f; }.timelineTable td { border-color:#1b4268; vertical-align:top; }.timelineTable td.event-position { color:#8dbdff; }.timelineTable td.event-funds { color:#f5c77b; }.timelineTable tr.event-liquidation { background:#2b151d; }.timelineTable .timelineKind { display:inline-flex; padding:3px 6px; border:1px solid #376486; border-radius:4px; color:#bcd7ef; font-size:11px; white-space:nowrap; }.timelineTable .timelineKind.deposit,.timelineTable .timelineKind.bonus_grant,.timelineTable .timelineKind.negative_balance_clear { color:#70dfb1; border-color:#21835e; background:#0b322b; }.timelineTable .timelineKind.withdrawal,.timelineTable .timelineKind.bonus_remove { color:#ffc08a; border-color:#92572e; background:#38240f; }.timelineTable .timelineKind.internal_transfer { color:#d1c4ff; border-color:#6955a0; background:#282044; }.timelineTable .timelineSub { display:block; margin-top:4px; color:#89a9c9; font-size:11px; white-space:nowrap; }.timelineTable .timelineLiquidationLabel { color:#ffafb5; }.timelineTable button { padding:3px 6px; font-size:12px; }.timelineTable .timelineJump { margin-right:4px; color:#ffd9dc; border-color:#a94958; background:#4a1c27; }.timelinePagination { display:flex; align-items:center; justify-content:flex-end; gap:8px; margin-top:10px; color:#82a5c9; font-size:12px; }
@media (max-width:900px) { .timelineSummary { grid-template-columns:repeat(2,minmax(0,1fr)); }.timelineSummary div:nth-child(odd) { border-left:0; } } @media (max-width:620px) { .timelineSummary { grid-template-columns:1fr; }.timelineSummary div { border-left:0; border-top:1px solid #214f78; }.timelineSummary div:first-child { border-top:0; } }
"""


_HTML = """
<section class="timelinePanel" id="accountTimelinePanel">
  <div class="timelineHead"><div><h2>历史资金回溯</h2><small id="timelineCoverage">读取中</small></div><div class="timelineNote" id="timelineSource"></div></div>
  <div class="timelineSummary" id="timelineSummary"></div>
  <div class="timelineChart" id="timelineChart"><div class="timelineNote">等待资金曲线...</div></div>
  <div class="timelineLiquidations" id="timelineLiquidations" hidden></div>
  <div class="timelineEventsHead"><b>资金与订单事件</b><span class="timelineNote" id="timelineEventNote"></span></div>
  <div class="tableWrap"><table class="timelineTable" id="timelineTable"></table></div>
  <div class="timelinePagination"><button id="timelinePrev" type="button">上一页</button><span id="timelinePage"></span><button id="timelineNext" type="button">下一页</button></div>
</section>
"""


_JS = r"""
(() => {
  const timeline = DATA.accountTimeline;
  if (!timeline || !Array.isArray(timeline.events)) return;
  const pageSize = 200;
  let eventPage = 0;
  const escTimeline = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => value == null || value === '' || !Number.isFinite(Number(value)) ? '数据不足' : Number(value).toFixed(2);
  const moneyClass = value => Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : '';
  const stateAt = ms => {
    let state = timeline.openingState || {known:false, balance:null, credit:null};
    (timeline.curve || []).forEach(row => {
      const at = toMs(row.timestamp);
      if (Number.isFinite(at) && at <= ms && row.balance != null && row.credit != null) state = {...row, known:true};
    });
    return state;
  };
  const kindLabel = row => row.kind === 'trade_position' ? (row.positionState === 'open' ? '未平仓仓位' : '仓位平仓') : ({deposit:'外部入金',withdrawal:'外部出金',internal_transfer:'内部划转',bonus_grant:'Credit 增加',bonus_remove:'Credit 扣减',negative_balance_clear:'负余额清零',compensation:'补偿入账',cash_reversal:'资金冲正',other_balance:'余额调整',adjustment:'账务调整'})[row.kind] || row.kind || '其他';
  const valid = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const chartPoints = (rows, field, min, max, width, height) => rows.filter(row => valid(row[field])).map((row, index, values) => `${(values.length === 1 ? 0 : index / (values.length - 1)) * width},${height - ((Number(row[field]) - min) / (max - min || 1)) * height}`).join(' ');
  const focusTimestamp = timestamp => { const ms = toMs(timestamp); if (Number.isFinite(ms)) focusTimeMs(ms); };
  const renderTimelineChart = () => {
    const curve = (timeline.curve || []).filter(row => valid(row.balance) || valid(row.credit));
    const chart = document.getElementById('timelineChart');
    if (!curve.length) { chart.innerHTML = '<div class="timelineNote">没有可绘制的余额或 Credit 快照</div>'; return; }
    const values = curve.flatMap(row => [row.balance, row.credit]).filter(valid).map(Number), min = Math.min(...values), max = Math.max(...values), pad = Math.max((max - min) * .08, 1), low = min - pad, high = max + pad, width = 1000, height = 190;
    const markers = (timeline.liquidationPoints || []).map(point => { const index = curve.findIndex(row => row.timestamp === point.timestamp); if (index < 0) return ''; const row = curve[index], value = valid(row.balance) ? Number(row.balance) : Number(row.credit), x = (curve.length === 1 ? 0 : index / (curve.length - 1)) * width, y = height - ((value - low) / (high - low || 1)) * height, label = `${point.label || '爆仓标记'} · ${point.timestamp || '-'} · ${point.orderId || point.positionId || '无订单号'}`; return `<circle class="timelineLiquidation" data-timeline-marker="${escTimeline(point.timestamp || '')}" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="5" tabindex="0" role="button" aria-label="${escTimeline(label)}，跳转到 K 线"><title>${escTimeline(label)}</title></circle>`; }).join('');
    chart.innerHTML = `<div class="timelineChartHead"><b>余额与 Credit 回放</b><span>蓝色：余额 · 金色：Credit · 红点：爆仓标记，可点击跳转</span></div><svg viewBox="0 0 ${width} 220" role="img" aria-label="历史余额与 Credit 曲线"><line class="timelineGrid" x1="0" y1="0" x2="${width}" y2="0"/><line class="timelineGrid" x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}"/><line class="timelineGrid" x1="0" y1="${height}" x2="${width}" y2="${height}"/><polyline class="timelineBalance" points="${chartPoints(curve, 'balance', low, high, width, height)}"/><polyline class="timelineCredit" points="${chartPoints(curve, 'credit', low, high, width, height)}"/>${markers}<text x="0" y="12" fill="#7895b8" font-size="11">最高 ${escTimeline(money(high))}</text><text x="0" y="214" fill="#7895b8" font-size="11">最低 ${escTimeline(money(low))}</text></svg>`;
    chart.querySelectorAll('[data-timeline-marker]').forEach(node => { const jump = () => focusTimestamp(node.dataset.timelineMarker); node.addEventListener('click', jump); node.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); jump(); } }); });
  };
  const renderTimeline = () => {
    const events = timeline.events || [], pages = Math.max(1, Math.ceil(events.length / pageSize));
    eventPage = Math.max(0, Math.min(eventPage, pages - 1));
    const rows = events.slice(eventPage * pageSize, eventPage * pageSize + pageSize);
    document.getElementById('timelineTable').innerHTML = '<thead><tr><th>时间</th><th>事件</th><th>Position / Deal</th><th>品种</th><th>备注</th><th>余额变化</th><th>Credit变化</th><th>实现盈亏</th><th>事件后余额</th><th>事件后Credit</th><th>权益状态</th><th></th></tr></thead><tbody>' + rows.map((row, index) => {
      const cls = row.liquidation ? 'event-liquidation' : '';
      const id = eventPage * pageSize + index;
      const source = [row.symbol, row.comment].filter(Boolean).join(' / ');
      const positionDetail = row.kind === 'trade_position' ? `开 ${row.positionOpenTime || '—'}${row.positionCloseTime ? ` · 平 ${row.positionCloseTime}` : ''} · ${row.sourceOrderEventCount || 1} 条成交` : '';
      const liquidationButton = row.liquidation ? `<button type="button" data-timeline-liquidation="${id}">爆仓点位</button>` : '';
      return `<tr class="${cls}"><td>${escTimeline(row.timestamp)}</td><td class="event-${escTimeline(row.category)}"><span class="timelineKind ${escTimeline(row.kind)}">${escTimeline(kindLabel(row))}</span>${row.liquidation ? '<span class="timelineSub timelineLiquidationLabel">爆仓标记</span>' : ''}</td><td><b>${escTimeline(row.positionId || row.orderId || row.id || '-')}</b>${row.kind === 'trade_position' ? `<span class="timelineSub">${escTimeline((row.sourceOrderIds || []).join(' / ') || 'Position')}</span>` : ''}</td><td>${escTimeline(row.symbol || '-')}</td><td>${escTimeline(source || '-')} ${positionDetail ? `<span class="timelineSub">${escTimeline(positionDetail)}</span>` : ''}</td><td class="${moneyClass(row.deltaBalance)}">${money(row.deltaBalance)}</td><td class="${moneyClass(row.deltaCredit)}">${money(row.deltaCredit)}</td><td class="${moneyClass(row.realizedPnl)}">${money(row.realizedPnl)}</td><td>${money(row.balance)}</td><td>${money(row.credit)}</td><td>${escTimeline(row.equityStatus === 'authoritative_daily' ? '日快照' : row.equityStatus === 'authoritative_current' ? '当前快照' : row.equityStatus ? '无盘中快照' : '—')}</td><td>${liquidationButton}<button type="button" data-timeline-event="${id}">定位</button></td></tr>`;
    }).join('') + '</tbody>';
    document.getElementById('timelinePage').textContent = `第 ${eventPage + 1} / ${pages} 页，共 ${events.length} 条展示事件`;
    document.getElementById('timelinePrev').disabled = eventPage === 0;
    document.getElementById('timelineNext').disabled = eventPage >= pages - 1;
  };
  const summary = timeline.summary || {};
  const coverage = timeline.coverage || {}, sourceLabel = [timeline.platform, timeline.server].filter(Boolean).join(' / ') || '当前选定路由';
  document.getElementById('timelineCoverage').textContent = `已回放 ${summary.eventCount || 0} 条展示事件（${summary.positionEventCount || 0} 个 Position，源流水 ${summary.allEventCount || 0} 条）`;
  document.getElementById('timelineSource').textContent = `来源：${sourceLabel}。完整读取 ${coverage.eventRows ?? summary.allEventCount ?? 0} 条订单与资金事件、${coverage.dailyAnchors ?? 0} 条日快照；余额和 Credit 按事件回放，权益不补造。`;
  const summaryItems = [['外部入金', summary.externalDeposit], ['外部出金', summary.externalWithdrawal], ['外部净入金', summary.externalNetDeposit], ['内部划转', summary.internalTransfer], ['Credit 增加', summary.bonusGranted], ['Credit 扣减', summary.bonusRemoved], ['负余额清零', summary.negativeBalanceCleared], ['爆仓标记', summary.liquidationCount]];
  document.getElementById('timelineSummary').innerHTML = summaryItems.map(([label, value], index) => `<div><span>${escTimeline(label)}${index === 7 ? '' : ` (${summary.currency || 'USD'})`}</span><b class="${index === 7 ? '' : moneyClass(index === 1 || index === 5 ? -Number(value || 0) : value)}">${index === 7 ? Number(value || 0) : money(value)}</b></div>`).join('');
  document.getElementById('timelineEventNote').textContent = '资金流水逐笔展示；订单按 Position 合并，开仓和平仓不重复列示。';
  const liquidationBox = document.getElementById('timelineLiquidations'), liquidations = timeline.liquidationPoints || [];
  liquidationBox.hidden = !liquidations.length;
  liquidationBox.innerHTML = liquidations.length ? `<b>爆仓点位 ${liquidations.length} 个</b>${liquidations.map(point => `<button type="button" data-timeline-liquidation-time="${escTimeline(point.timestamp || '')}">${escTimeline(`${point.label || '爆仓标记'} · ${point.timestamp || '-'} · ${point.orderId || point.positionId || '-'}`)}</button>`).join('')}` : '';
  liquidationBox.querySelectorAll('[data-timeline-liquidation-time]').forEach(node => node.addEventListener('click', () => focusTimestamp(node.dataset.timelineLiquidationTime)));
  document.getElementById('timelinePrev').addEventListener('click', () => { eventPage--; renderTimeline(); });
  document.getElementById('timelineNext').addEventListener('click', () => { eventPage++; renderTimeline(); });
  document.getElementById('timelineTable').addEventListener('click', event => {
    const button = event.target.closest('[data-timeline-event],[data-timeline-liquidation]');
    if (!button) return;
    const index = Number(button.dataset.timelineEvent ?? button.dataset.timelineLiquidation);
    const row = (timeline.events || [])[index];
    const ms = row ? toMs(row.timestamp) : NaN;
    if (Number.isFinite(ms)) focusTimeMs(ms);
  });
  renderTimelineChart();
  renderTimeline();

  const originalBottomPanel = drawBottomPanel;
  drawBottomPanel = function(rows, pad, plotW, top, height, xScale) {
    if (panelMode !== 'funds') return originalBottomPanel(rows, pad, plotW, top, height, xScale);
    ctx.save();
    ctx.fillStyle = 'rgba(248,250,252,0.96)'; ctx.fillRect(pad.l, top, plotW, height);
    ctx.strokeStyle = '#dbe4ee'; ctx.strokeRect(pad.l, top, plotW, height);
    const all = (timeline.curve || []).filter(row => row.balance != null && row.credit != null && Number.isFinite(toMs(row.timestamp)));
    if (!all.length) { ctx.fillStyle='#64748b'; ctx.font='12px Arial'; ctx.fillText('资金回放：当前时间范围没有可确认的 Balance / Credit 数据', pad.l + 10, top + 22); ctx.restore(); return; }
    const points = all.map(row => ({...row, idx: findIndexByMs(toMs(row.timestamp))})).filter(row => row.idx >= viewStart - 1 && row.idx <= viewEnd + 1);
    const shown = points.length ? points : all.map(row => ({...row, idx: findIndexByMs(toMs(row.timestamp))}));
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
  if (fundsButton) fundsButton.addEventListener('click', () => { panelMode='funds'; fundsButton.classList.add('active'); document.getElementById('panelProfit').classList.remove('active'); document.getElementById('panelVolume').classList.remove('active'); document.getElementById('panelPosition').classList.remove('active'); draw(false); });
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
    payload["accountTimeline"] = timeline
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
    return html.replace("</body>", "<script>" + _JS + "</script></body>", 1)
