"""Lightweight Charts renderer for the cached trade/K-line contract.

This module deliberately has no MT4/MT5 imports.  Quote acquisition belongs to
the upstream cache/terminal adapter; this module only renders the supplied bars.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

try:
    from .build_enhanced_trade_kline_from_cache import account_meta_from_trades, bars_for_html, quote_gaps
except ImportError:  # script execution from the legacy tool directory
    from build_enhanced_trade_kline_from_cache import account_meta_from_trades, bars_for_html, quote_gaps


def _json_default(value: Any):
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "item"):
        return value.item()
    return None


def _payload(account: str, stem: str, trades: pd.DataFrame, bars_by_symbol: dict, mapping_by_symbol: dict, *, position_meta=None, timeline=None) -> dict:
    chart_trades = trades.copy()
    if "Open Plot Price" not in chart_trades:
        chart_trades["Open Plot Price"] = chart_trades.get("Open Price")
    if "Close Plot Price" not in chart_trades:
        chart_trades["Close Plot Price"] = chart_trades.get("Close Price")
    bars_json: dict[str, list[dict[str, Any]]] = {}
    gaps_json: dict[str, list[dict[str, Any]]] = {}
    for symbol, bars in bars_by_symbol.items():
        symbol_trades = chart_trades[chart_trades["Item"] == symbol] if "Item" in chart_trades else chart_trades.iloc[0:0]
        compact = bars_for_html(bars, symbol_trades).copy()
        compact["time"] = pd.to_datetime(compact["time"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        gaps_json[symbol] = quote_gaps(pd.DataFrame({"time": pd.to_datetime(compact["time"])}))
        bars_json[symbol] = compact[["time", "open", "high", "low", "close", "tick_volume"]].to_dict("records")
    for column in chart_trades.columns:
        if pd.api.types.is_datetime64_any_dtype(chart_trades[column]):
            chart_trades[column] = chart_trades[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "account": str(account),
        "stem": str(stem),
        "accountMeta": account_meta_from_trades(chart_trades),
        "barsBySymbol": bars_json,
        "gapsBySymbol": gaps_json,
        "trades": chart_trades.where(pd.notna(chart_trades), None).to_dict("records"),
        "mappingBySymbol": mapping_by_symbol,
        "positionMeta": position_meta or {},
        "timeline": timeline or {},
    }


def build_lightweight_html(account: str, stem: str, trades: pd.DataFrame, bars_by_symbol: dict, mapping_by_symbol: dict, *, position_meta=None, timeline=None) -> str:
    """Build a self-contained HTML artifact using Lightweight Charts.

    The payload is intentionally the same as the legacy renderer.  The browser
    creates candlestick, marker, holding, profit, volume and position series
    from that payload, so the rendering path never opens an MT terminal.
    """

    payload = json.dumps(_payload(account, stem, trades, bars_by_symbol, mapping_by_symbol, position_meta=position_meta, timeline=timeline), ensure_ascii=False, default=_json_default, separators=(",", ":"))
    timeline_json = json.dumps(timeline or {}, ensure_ascii=False, default=_json_default, separators=(",", ":"))
    return _HTML.replace("__PAYLOAD__", payload).replace("__TIMELINE__", timeline_json).replace("__TITLE__", f"{stem} 买卖点K线图")


_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script src="https://unpkg.com/lightweight-charts@5.0.8/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f5f6f8;color:#1f2937}header{padding:14px 20px;background:#111827;color:#fff}h1{margin:0 0 8px;font-size:20px}.meta{display:flex;gap:10px 22px;flex-wrap:wrap;font-size:13px;color:#d1d5db}.toolbar,.filters{display:flex;align-items:center;gap:8px;padding:12px 18px 6px;flex-wrap:wrap}.filters{padding-top:6px;padding-bottom:10px;border-bottom:1px solid #e5e7eb}.filters input{width:82px}.filterTitle{font-weight:700;color:#334155}select,button,input{border:1px solid #cbd5e1;background:#fff;color:#111827;padding:7px 10px;border-radius:4px}button{cursor:pointer}button:hover{background:#f1f5f9}.status{margin-left:auto;color:#4b5563;font-size:13px}.wrap{padding:0 18px 22px}.chartShell{background:#fff;border:1px solid #cbd5e1}.chart{width:100%;height:720px}.panelToggle{display:flex;gap:4px;padding:8px;border-bottom:1px solid #e5e7eb}.panelToggle button.active{background:#111827;color:#fff}.chartHelp{padding:8px;border-top:1px solid #e5e7eb}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:13px}.sw{width:12px;height:12px;display:inline-block;margin-right:5px;vertical-align:-1px}.summary{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:8px;margin-top:12px}.metric{background:#fff;border:1px solid #e5e7eb;padding:10px 12px}.metric .k{color:#64748b;font-size:12px}.metric .v{margin-top:5px;font-size:18px;font-weight:700}.windowControls{display:grid;grid-template-columns:1fr 1fr auto;gap:6px;margin-top:6px}.windowControls input{width:100%;min-width:0;padding:6px 7px;font-size:12px}.tableWrap{overflow:auto;max-height:420px;border:1px solid #e5e7eb;background:#fff;margin-top:12px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{border:1px solid #e5e7eb;padding:5px 7px;text-align:right;white-space:nowrap}th{background:#eef2f7;position:sticky;top:0;z-index:1}td.left,th.left{text-align:left}.timelinePanel{margin-top:14px;border:1px solid #d1d5db;border-radius:6px;background:#fff;padding:12px}.timelineSummary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:10px 0}.timelineSummary>div{border:1px solid #e5e7eb;padding:8px}.timelineSummary span{display:block;color:#64748b;font-size:12px}.timelineSummary b{display:block;margin-top:5px;font-size:16px}.timelineTableViewport{max-height:320px;overflow:auto}@media(max-width:900px){.summary,.timelineSummary{grid-template-columns:1fr 1fr}}@media(max-width:600px){.wrap{padding:0 8px 18px}.toolbar,.filters{padding-left:8px;padding-right:8px}.chart{height:620px}}
</style></head>
<body><header><h1>__TITLE__</h1><div class="meta" id="meta"></div></header>
<div class="toolbar"><select id="symbolSelect"></select><button id="zoomIn">放大</button><button id="zoomOut">缩小</button><button id="reset">重置</button><button id="fitTrades">只看交易区间</button><span class="status" id="status"></span></div>
<div class="filters"><span class="filterTitle">过滤</span><label>方向 <select id="filterType"><option value="">全部</option><option value="buy">buy</option><option value="sell">sell</option></select></label><label>手数 <input id="filterVolumeMin" type="number" step="0.01" placeholder="min"> - <input id="filterVolumeMax" type="number" step="0.01" placeholder="max"></label><label>Profit <input id="filterProfitMin" type="number" step="1" placeholder="min"> - <input id="filterProfitMax" type="number" step="1" placeholder="max"></label><label>持仓分钟 <input id="filterHoldMin" type="number" step="1" placeholder="min"> - <input id="filterHoldMax" type="number" step="1" placeholder="max"></label><button id="clearFilters">清空</button><label><input id="showGaps" type="checkbox">显示真实停盘间隔</label><label>显示订单 <input id="displayLimit" type="number" min="1" step="50" value="300" style="width:86px"></label></div>
<div class="wrap"><div class="chartShell"><div id="chart" class="chart"></div><div class="panelToggle"><button id="panelProfit" class="active">Profit</button><button id="panelVolume">手数</button><button id="panelPosition">仓位</button><button id="barStackToggle">Profit柱：单独</button></div><div class="chartHelp"><div class="legend"><span><i class="sw" style="background:#16a34a"></i>买入开仓</span><span><i class="sw" style="background:#dc2626"></i>卖出开仓</span><span><i class="sw" style="background:#2563eb"></i>平仓</span><span><i class="sw" style="background:#7c3aed"></i>持仓连线</span><span>滚轮缩放、拖动平移、十字光标由 Lightweight Charts 原生处理</span></div></div></div>
<div class="summary"><div class="metric"><div class="k">当前显示订单</div><div class="v" id="shownCount">0</div></div><div class="metric"><div class="k">当前显示 Profit / Net</div><div class="v" id="shownProfit">0.00</div></div><div class="metric"><div class="k">全量 Closed P/L</div><div class="v" id="totalClosedPL">0.00</div></div><div class="metric"><div class="k">时间窗口</div><div class="windowControls"><input id="windowStart" type="text" placeholder="YYYY-MM-DD HH:MM"><input id="windowEnd" type="text" placeholder="YYYY-MM-DD HH:MM"><button id="applyWindow">应用</button></div><small id="windowLabel"></small></div></div>
<div class="tableWrap"><table id="tradeTable"></table></div>
<section class="timelinePanel" id="accountTimelinePanel"><h3>历史资金回溯</h3><div id="timelineCoverage">未提供资金事件</div><div class="timelineSummary" id="timelineSummary"></div><div class="timelineTableViewport"><table id="timelineTable"></table></div></section></div>
<script id="accountTimelineData" type="application/json">__TIMELINE__</script>
<script>
const DATA=__PAYLOAD__, LC=window.LightweightCharts; const host=document.getElementById('chart');
const chart=LC.createChart(host,{autoSize:true,layout:{background:{type:'solid',color:'#fff'},textColor:'#334155'},grid:{vertLines:{color:'#eef2f7'},horzLines:{color:'#eef2f7'}},crosshair:{mode:LC.CrosshairMode.Normal},rightPriceScale:{borderColor:'#cbd5e1'},timeScale:{timeVisible:true,secondsVisible:true,borderColor:'#cbd5e1'} });
let symbol=Object.keys(DATA.barsBySymbol||{})[0]||'', bars=[], trades=[], actualTimes=[], compactTimes=[], showRealGaps=false, panel='profit', barStack=false, series=[];
const $=id=>document.getElementById(id), n=v=>Number.isFinite(Number(v))?Number(v):0, ms=s=>Date.parse(String(s).replace(' ','T'))||0, sec=s=>Math.floor(ms(s)/1000), fmt=v=>n(v).toFixed(2);
function removeSeries(){series.forEach(s=>{try{chart.removeSeries(s)}catch(_){}});series=[]}
function barIndex(t){const x=ms(t);let lo=0,hi=bars.length-1;while(lo<=hi){const m=(lo+hi)>>1;if(ms(bars[m].time)===x)return m;if(ms(bars[m].time)<x)lo=m+1;else hi=m-1}return Math.max(0,Math.min(bars.length-1,lo))}
function tAt(i){return showRealGaps?sec(bars[i].time):compactTimes[i]}
function filtered(){const type=$('filterType').value, vmin=$('filterVolumeMin').value, vmax=$('filterVolumeMax').value,pmin=$('filterProfitMin').value,pmax=$('filterProfitMax').value,hmin=$('filterHoldMin').value,hmax=$('filterHoldMax').value;return trades.filter(t=>{const v=n(t.Volume),p=n(t.Profit),h=n(t['Holding Seconds']||0)/60;return (!type||t.Type===type)&&(vmin===''||v>=n(vmin))&&(vmax===''||v<=n(vmax))&&(pmin===''||p>=n(pmin))&&(pmax===''||p<=n(pmax))&&(hmin===''||h>=n(hmin))&&(hmax===''||h<=n(hmax))})}
function positionData(){return bars.map((b,i)=>{const at=ms(b.time);const open=trades.filter(t=>ms(t['Open Time'])<=at&&ms(t['Close Time'])>at);return {time:tAt(i),value:open.length}})}
function rebuild(){removeSeries();actualTimes=bars.map(b=>sec(b.time));const base=Date.UTC(2000,0,1)/1000;compactTimes=bars.map((_,i)=>base+i*60);const candle=chart.addSeries(LC.CandlestickSeries,{upColor:'#16a34a',downColor:'#dc2626',borderVisible:false,wickUpColor:'#16a34a',wickDownColor:'#dc2626'},0);series.push(candle);candle.setData(bars.map((b,i)=>({time:tAt(i),open:n(b.open),high:n(b.high),low:n(b.low),close:n(b.close)})));
const rows=filtered().slice(0,Math.max(1,n($('displayLimit').value)||300));const markers=[];rows.forEach(t=>{const oi=barIndex(t['Open Time']),ci=barIndex(t['Close Time']);markers.push({time:tAt(oi),position:t.Type==='buy'?'belowBar':'aboveBar',color:t.Type==='buy'?'#16a34a':'#dc2626',shape:t.Type==='buy'?'arrowUp':'arrowDown',text:`开 ${t.Ticket||''}`});markers.push({time:tAt(ci),position:'aboveBar',color:'#2563eb',shape:'square',text:`平 ${t.Ticket||''}`});const line=chart.addSeries(LC.LineSeries,{color:'#7c3aed',lineWidth:1,lineStyle:LC.LineStyle.Dashed,pointMarkersVisible:false,lastValueVisible:false,priceLineVisible:false},0);line.setData([{time:tAt(oi),value:n(t['Open Plot Price']??t['Open Price'])},{time:tAt(ci),value:n(t['Close Plot Price']??t['Close Price'])}]);series.push(line)});if(LC.createSeriesMarkers)LC.createSeriesMarkers(candle,markers);else if(candle.setMarkers)candle.setMarkers(markers);
const profit=chart.addSeries(LC.HistogramSeries,{priceScaleId:'profit',priceFormat:{type:'price',precision:2,minMove:.01},priceScale:{scaleMargins:{top:.15,bottom:.15}}},1);profit.setData(rows.map(t=>({time:tAt(barIndex(t['Open Time'])),value:n(t.Profit),color:n(t.Profit)>=0?'#ef4444':'#22c55e'})));series.push(profit);const volume=chart.addSeries(LC.HistogramSeries,{priceScaleId:'volume',priceFormat:{type:'volume'},priceScale:{scaleMargins:{top:.15,bottom:.15}}},1);volume.setData(rows.map(t=>({time:tAt(barIndex(t['Open Time'])),value:Math.max(0,n(t.Volume)),color:'#3b82f6'})));series.push(volume);const pos=chart.addSeries(LC.LineSeries,{color:'#7c3aed',lineWidth:2,priceScaleId:'position',priceScale:{scaleMargins:{top:.2,bottom:.2}}},1);pos.setData(positionData());series.push(pos);profit.applyOptions({visible:panel==='profit'});volume.applyOptions({visible:panel==='volume'});pos.applyOptions({visible:panel==='position'});chart.timeScale().fitContent();updateMeta(rows);updateTable(rows);updatePositionSnapshot();}
function updateMeta(rows){const m=DATA.mappingBySymbol[symbol]||{},a=DATA.accountMeta||{};$('meta').innerHTML=`<span>账户：${DATA.account}</span><span>品种：${symbol} → ${m.mt5_symbol||''}</span><span>报价源：${m.provider||'cache'} / ${m.provider_server||'-'}</span><span>时间模式：${m.time_mode||''}</span><span>订单数：${trades.length}</span><span>报价根数：${bars.length}</span>`;const total=rows.reduce((s,t)=>s+n(t.Profit),0),net=rows.reduce((s,t)=>s+n(t.Profit)+n(t.Commission)+n(t.Swap)+n(t.Taxes),0),all=trades.reduce((s,t)=>s+n(t.Profit)+n(t.Commission)+n(t.Swap)+n(t.Taxes),0);$('shownCount').textContent=rows.length;$('shownProfit').textContent=`${fmt(total)} / ${fmt(net)}`;$('totalClosedPL').textContent=fmt(all);$('windowLabel').textContent=bars.length?`${bars[0].time} 至 ${bars[bars.length-1].time}`:'-';$('status').textContent=`${bars.length} 根 M1 · ${rows.length} 笔显示 · ${showRealGaps?'真实时间轴':'压缩停盘时间轴'}`}
function updateTable(rows){const cols=['Ticket','Type','Volume','Open Time','Open Price','Close Time','Close Price','Holding Seconds','Profit','Comment'];$('tradeTable').innerHTML='<thead><tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+rows.map(t=>'<tr>'+cols.map(c=>`<td>${c==='Holding Seconds'?Math.round(n(t[c]))+'秒':(t[c]??'')}</td>`).join('')+'</tr>').join('')+'</tbody>'}
function updatePositionSnapshot(){const idx=Math.max(0,Math.min(bars.length-1,Math.round((chart.timeScale().getVisibleRange()?.from||0)-0))), at=bars[idx]?.time||'';let open=trades.filter(t=>ms(t['Open Time'])<=ms(at)&&ms(t['Close Time'])>ms(at));$('timelineCoverage').textContent=`${open.length} 个未平仓订单（点击图表后可更新）`;}
function setSymbol(s){symbol=s;bars=(DATA.barsBySymbol[s]||[]).slice().sort((a,b)=>ms(a.time)-ms(b.time));trades=(DATA.trades||[]).filter(t=>t.Item===s).map(t=>({...t}));trades.forEach(t=>delete t._pos);$('symbolSelect').value=s;rebuild()}
function setPanel(p){panel=p;document.querySelectorAll('.panelToggle button').forEach(b=>b.classList.remove('active'));$(`panel${p[0].toUpperCase()+p.slice(1)}`).classList.add('active');rebuild()}
function applyWindow(){const a=$('windowStart').value,b=$('windowEnd').value;if(!a||!b||!bars.length)return;const lo=Math.min(sec(a),sec(b)),hi=Math.max(sec(a),sec(b));const idx=bars.findIndex(x=>sec(x.time)>=lo),end=bars.findLastIndex?bars.findLastIndex(x=>sec(x.time)<=hi):bars.map(x=>sec(x.time)<=hi).lastIndexOf(true);if(idx<0||end<idx){$('windowLabel').textContent='该区间无报价';return}chart.timeScale().setVisibleRange({from:tAt(idx),to:tAt(end)});$('windowLabel').textContent=`${bars[idx].time} 至 ${bars[end].time}`}
function fitTrades(){if(!trades.length){chart.timeScale().fitContent();return}const a=Math.min(...trades.map(t=>barIndex(t['Open Time']))),b=Math.max(...trades.map(t=>barIndex(t['Close Time'])));chart.timeScale().setVisibleRange({from:tAt(Math.max(0,a-20)),to:tAt(Math.min(bars.length-1,b+20))})}
function renderTimeline(){const raw=DATA.timeline||{};const events=raw.events||[];$('timelineCoverage').textContent=events.length?`共 ${events.length} 条资金/订单事件`:'未提供资金事件';$('timelineSummary').innerHTML=`<div><span>事件数</span><b>${events.length}</b></div><div><span>资金变化</span><b>${fmt(events.reduce((s,e)=>s+n(e.deltaBalance),0))}</b></div><div><span>数据源</span><b>${raw.source||'外部回放'}</b></div><div><span>说明</span><b>只读回放</b></div>`;if(!events.length){$('timelineTable').innerHTML='';return}const cols=['timestamp','kind','symbol','deltaBalance','balance','equity'];$('timelineTable').innerHTML='<thead><tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+events.slice(0,1000).map(e=>'<tr>'+cols.map(c=>`<td>${e[c]??''}</td>`).join('')+'</tr>').join('')+'</tbody>'}
$('symbolSelect').innerHTML=Object.keys(DATA.barsBySymbol||{}).map(s=>`<option>${s}</option>`).join('');$('symbolSelect').addEventListener('change',e=>setSymbol(e.target.value));$('zoomIn').onclick=()=>chart.timeScale().scrollToPosition(20,true);$('zoomOut').onclick=()=>chart.timeScale().scrollToPosition(-20,true);$('reset').onclick=()=>chart.timeScale().fitContent();$('fitTrades').onclick=fitTrades;$('showGaps').onchange=e=>{showRealGaps=e.target.checked;rebuild()};$('panelProfit').onclick=()=>setPanel('profit');$('panelVolume').onclick=()=>setPanel('volume');$('panelPosition').onclick=()=>setPanel('position');$('barStackToggle').onclick=()=>{barStack=!barStack;$('barStackToggle').textContent=barStack?'Profit柱：叠加':'Profit柱：单独';rebuild()};$('applyWindow').onclick=applyWindow;$('displayLimit').onchange=rebuild;['filterType','filterVolumeMin','filterVolumeMax','filterProfitMin','filterProfitMax','filterHoldMin','filterHoldMax'].forEach(id=>$(id).addEventListener('input',rebuild));$('clearFilters').onclick=()=>{['filterType','filterVolumeMin','filterVolumeMax','filterProfitMin','filterProfitMax','filterHoldMin','filterHoldMax'].forEach(id=>$(id).value='');rebuild()};setSymbol(symbol);renderTimeline();
</script></body></html>'''
