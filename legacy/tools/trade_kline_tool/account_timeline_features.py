"""Inject factual Balance/Credit replay controls into the standalone K-line HTML."""

from __future__ import annotations

import json
from typing import Any


_CSS = """
.timelinePanel { margin-top:12px; border:1px solid #cbd5e1; background:#fff; padding:10px 12px; }
.timelineHead { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; flex-wrap:wrap; }
.timelineHead h2 { margin:0; font-size:15px; }.timelineHead small { display:block; margin-top:3px; color:#64748b; }
.timelineSummary { display:flex; gap:8px; flex-wrap:wrap; margin:9px 0; }.timelineSummary span { background:#eff6ff; color:#1e3a5f; padding:4px 7px; border-radius:4px; font-size:12px; }
.timelineTable td.event-order { color:#1d4ed8; }.timelineTable td.event-funds { color:#92400e; }.timelineTable tr.event-liquidation { background:#fff1f2; }.timelineTable button { padding:3px 6px; font-size:12px; }
.timelinePagination { display:flex; align-items:center; gap:8px; margin-top:8px; color:#64748b; font-size:12px; }
"""


_HTML = """
<section class="timelinePanel" id="accountTimelinePanel">
  <div class="timelineHead"><div><h2>资金与订单事件</h2><small id="timelineCoverage">读取中</small></div><div class="timelineSummary" id="timelineSummary"></div></div>
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
  const stateAt = ms => {
    let state = timeline.openingState || {known:false, balance:null, credit:null};
    (timeline.curve || []).forEach(row => {
      const at = toMs(row.timestamp);
      if (Number.isFinite(at) && at <= ms && row.balance != null && row.credit != null) state = {...row, known:true};
    });
    return state;
  };
  const kindLabel = kind => ({trade_open:'订单开仓',trade_close:'订单平仓',deposit:'外部入金',withdrawal:'外部出金',internal_transfer:'内部划转',bonus_grant:'Credit 增加',bonus_remove:'Credit 扣减',negative_balance_clear:'负余额清零',compensation:'补偿',cash_reversal:'资金冲正',other_balance:'余额调整',adjustment:'调整'})[kind] || kind || '其他';
  const renderTimeline = () => {
    const events = timeline.events || [], pages = Math.max(1, Math.ceil(events.length / pageSize));
    eventPage = Math.max(0, Math.min(eventPage, pages - 1));
    const rows = events.slice(eventPage * pageSize, eventPage * pageSize + pageSize);
    document.getElementById('timelineTable').innerHTML = '<thead><tr><th>时间</th><th class="left">事件</th><th>订单/流水</th><th class="left">品种 / 备注</th><th>余额变化</th><th>Credit 变化</th><th>Balance 后</th><th>Credit 后</th><th></th></tr></thead><tbody>' + rows.map((row, index) => {
      const cls = row.liquidation ? 'event-liquidation' : '';
      const id = eventPage * pageSize + index;
      const source = [row.symbol, row.comment].filter(Boolean).join(' / ');
      return `<tr class="${cls}"><td>${escTimeline(row.timestamp)}</td><td class="left event-${escTimeline(row.category)}">${escTimeline(kindLabel(row.kind))}${row.liquidation ? ' · 爆仓标记' : ''}</td><td>${escTimeline(row.orderId || row.id || '-')}</td><td class="left">${escTimeline(source || '-')}</td><td>${money(row.deltaBalance)}</td><td>${money(row.deltaCredit)}</td><td>${money(row.balance)}</td><td>${money(row.credit)}</td><td><button type="button" data-timeline-event="${id}">定位</button></td></tr>`;
    }).join('') + '</tbody>';
    document.getElementById('timelinePage').textContent = `第 ${eventPage + 1} / ${pages} 页，共 ${events.length} 条`;
    document.getElementById('timelinePrev').disabled = eventPage === 0;
    document.getElementById('timelineNext').disabled = eventPage >= pages - 1;
  };
  const summary = timeline.summary || {};
  document.getElementById('timelineCoverage').textContent = `账户资金时间线 · ${summary.eventCount || 0}/${summary.allEventCount || 0} 条事件 · ${summary.currency || 'USD'} · ${timeline.openingState?.known ? '已带入期初 Balance/Credit' : '期初 Balance/Credit 数据不足'}`;
  document.getElementById('timelineSummary').innerHTML = [`外部净入金 ${money(summary.externalNetDeposit)}`, `Credit 增加 ${money(summary.bonusGranted)}`, `Credit 扣减 ${money(summary.bonusRemoved)}`, `爆仓点位 ${summary.liquidationCount || 0}`].map(text => `<span>${escTimeline(text)}</span>`).join('');
  document.getElementById('timelinePrev').addEventListener('click', () => { eventPage--; renderTimeline(); });
  document.getElementById('timelineNext').addEventListener('click', () => { eventPage++; renderTimeline(); });
  document.getElementById('timelineTable').addEventListener('click', event => {
    const button = event.target.closest('[data-timeline-event]');
    if (!button) return;
    const row = (timeline.events || [])[Number(button.dataset.timelineEvent)];
    const ms = row ? toMs(row.timestamp) : NaN;
    if (Number.isFinite(ms)) focusTimeMs(ms);
  });
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
