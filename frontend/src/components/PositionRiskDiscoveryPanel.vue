<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '../api'
import { filterPositionRiskResults, positionClassificationLabel, positionRiskAccountHref, sortPositionRiskResults } from '../positionRiskDiscovery'
import { pushPollRetryDelay, recoverPushPollingState } from '../pushDiscovery'

const environmentOptions = [
  { value: 'ac_gb', label: 'AC GB' },
  { value: 'ac_cn', label: 'AC CN' },
  { value: 'dbg_cn', label: 'DBG CN' },
  { value: 'dbg_vn', label: 'DBG VN' },
]
const storageKey = 'kdesk.positionRiskScanJobId'
const form = reactive({
  start: localDate(-30),
  end: localDate(0),
  environments: environmentOptions.map(item => item.value),
  deepLimit: 100,
  minPositionPercent: '' as number | '',
  minLots: '' as number | '',
  minProfit: '' as number | '',
  excludeHandled: true,
  level: 'warning',
  sortBy: 'score',
})
const job = ref<any>(null)
const selectedRow = ref<any>(null)
let timer = 0
let pollFailures = 0

function localDate(offset: number): string {
  const date = new Date(Date.now() + offset * 86400000)
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}
function formatNumber(value: unknown, digits = 1): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '-'
}
function percent(value: unknown): string { return `${formatNumber(Number(value || 0) * 100, 1)}%` }
function directionLabel(value: unknown): string { return String(value || '').toLowerCase() === 'buy' ? '买入' : '卖出' }
function peerEvidenceReady(row: any): boolean { return Boolean(row?.peerSearchCoverage?.status) }
function verifiedSameAccounts(row: any): any[] { return peerEvidenceReady(row) ? (row.sameDirectionAccounts || row.peerAccounts || []) : [] }
function verifiedOppositeAccounts(row: any): any[] { return peerEvidenceReady(row) ? (row.oppositeDirectionAccounts || []) : [] }
function estimatedMarginValue(row: any): number | null {
  const direct = Number(row?.estimatedMargin)
  if (Number.isFinite(direct)) return direct
  const exposure = Number(row?.peakGrossExposure)
  const leverage = Number(row?.leverage)
  return Number.isFinite(exposure) && leverage > 0 ? exposure / leverage : null
}
function estimatedMarginLevelValue(row: any): number | null {
  const direct = Number(row?.estimatedMarginLevel)
  if (Number.isFinite(direct)) return direct
  const ratio = Number(row?.marginRatio)
  return ratio > 0 ? 100 / ratio : null
}
function openAnalysis(row: any): void { selectedRow.value = row }
function closeAnalysis(): void { selectedRow.value = null }
function handleKeydown(event: KeyboardEvent): void { if (event.key === 'Escape') closeAnalysis() }
function optionalNumber(value: number | ''): number | null { return value === '' ? null : Number(value) }
const rows = computed(() => sortPositionRiskResults(
  filterPositionRiskResults(job.value?.result?.allResults || job.value?.result?.results, form.level),
  form.sortBy,
))
function jobMessage(): string {
  if (!job.value) return '尚未运行'
  if (job.value.connectionError) return job.value.connectionError
  const events = job.value.events || []
  return events.length ? events[events.length - 1].message : job.value.error || ({ queued: '已提交，等待扫描', running: '正在扫描', done: '扫描完成', failed: '扫描失败', cancelled: '已取消' } as any)[job.value.status] || ''
}
async function poll(id: string): Promise<void> {
  try {
    job.value = await api<any>(`/api/position-risk/scans/${encodeURIComponent(id)}`)
    pollFailures = 0
    localStorage.setItem(storageKey, id)
    if (!['done', 'failed', 'cancelled'].includes(job.value.status)) timer = window.setTimeout(() => poll(id), 1400)
  } catch (error: any) {
    if (error instanceof ApiError && error.status === 404) {
      localStorage.removeItem(storageKey)
      job.value = { status: 'failed', error: '之前的重仓时点任务记录已不存在' }
      return
    }
    pollFailures += 1
    job.value = recoverPushPollingState(job.value, error, pollFailures)
    timer = window.setTimeout(() => poll(id), pushPollRetryDelay(pollFailures))
  }
}
async function start(): Promise<void> {
  if (!form.start || !form.end) { job.value = { status: 'failed', error: '请选择开始和结束时间' }; return }
  if (!form.environments.length) { job.value = { status: 'failed', error: '请至少选择一个环境' }; return }
  pollFailures = 0
  job.value = { status: 'queued', progress: 0 }
  try {
    const response = await api<any>('/api/position-risk/scans', {
      method: 'POST',
      body: JSON.stringify({
        start: form.start, end: form.end, environments: form.environments,
        deepLimit: form.deepLimit, excludeHandled: form.excludeHandled,
        minPositionPercent: optionalNumber(form.minPositionPercent),
        minLots: optionalNumber(form.minLots), minProfit: optionalNumber(form.minProfit),
      }),
    })
    job.value = response.job
    localStorage.setItem(storageKey, response.job.id)
    await poll(response.job.id)
  } catch (error: any) {
    job.value = { status: 'failed', error: error.message || '提交重仓时点扫描失败' }
  }
}
async function cancel(): Promise<void> {
  if (!job.value?.id) return
  try { job.value = await api<any>(`/api/jobs/${encodeURIComponent(job.value.id)}/cancel`, { method: 'POST' }) }
  catch (error: any) { job.value = { ...job.value, error: error.message || '取消任务失败' } }
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)
  const saved = localStorage.getItem(storageKey)
  if (saved) { void poll(saved); return }
  try {
    const response = await api<any>('/api/position-risk/scans/active')
    if (response.job?.id) void poll(response.job.id)
  } catch {
    // Passive task recovery must not block the workbench.
  }
})
onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer)
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="position-risk-discovery">
    <div class="bonus-scan-controls">
      <label>开始时间<input v-model="form.start" type="datetime-local"></label>
      <label>结束时间<input v-model="form.end" type="datetime-local"></label>
      <fieldset><legend>环境</legend><label v-for="item in environmentOptions" :key="item.value"><input v-model="form.environments" type="checkbox" :value="item.value">{{ item.label }}</label></fieldset>
      <label>深检账号上限<input v-model.number="form.deepLimit" type="number" min="1" max="300"></label>
      <label>最低仓位（%）<input v-model.number="form.minPositionPercent" type="number" min="0" step="1" placeholder="不限"></label>
      <label>最低手数（峰值）<input v-model.number="form.minLots" type="number" min="0" step="0.01" placeholder="不限"></label>
      <label>最小盈利金额<input v-model.number="form.minProfit" type="number" min="0" step="1" placeholder="不限"></label>
      <label>榜单等级<select v-model="form.level"><option value="warning">预警及以上</option><option value="high">高危及以上</option><option value="severe">仅严重</option><option value="concern">关注及以上</option><option value="all">全部</option></select></label>
      <label>结果排序<select v-model="form.sortBy"><option value="score">按评分</option><option value="profit">按盈利金额</option><option value="position">按仓位</option></select></label>
      <label class="bonus-handled-toggle"><input v-model="form.excludeHandled" type="checkbox">排除已处置账户</label>
      <button class="primary" :disabled="job && ['queued','running'].includes(job.status)" @click="start">{{ job && ['queued','running'].includes(job.status) ? '扫描中…' : '开始重仓时点检测' }}</button>
      <button v-if="job && ['queued','running'].includes(job.status)" :disabled="job.cancel_requested" @click="cancel">{{ job.cancel_requested ? '正在停止…' : '取消' }}</button>
    </div>
    <small class="tool-note">数据库时间 +08:00 · 开盘窗口 21:45–22:30 · 仓位指预计保证金 / 事件前权益，越高越满 · 可选条件留空表示不限</small>
    <div v-if="job" class="job-card"><div class="job-head"><b>{{ jobMessage() }}</b><span>{{ job.progress || 0 }}%</span></div><div class="progress"><i :style="{ width: `${job.progress || 0}%` }" /></div><div v-if="job.connectionError" class="inline-warning">{{ job.connectionDetail }}</div><div v-if="job.error" class="inline-error">{{ job.error }}</div></div>
    <div v-if="job?.result?.summary" class="bonus-scan-summary">
      <div><span>特殊时点候选</span><b>{{ job.result.summary.candidateAccounts }}</b></div><div><span>保留候选</span><b>{{ job.result.summary.retainedCandidates }}</b></div><div><span>实际深检</span><b>{{ job.result.summary.analyzedAccounts }}</b></div><div><span>符合条件</span><b>{{ job.result.summary.matchedFilters ?? job.result.summary.analyzedAccounts }}</b></div><div><span>预警</span><b>{{ job.result.summary.warnings }}</b></div><div><span>高危</span><b>{{ job.result.summary.highRisk }}</b></div><div><span>严重</span><b>{{ job.result.summary.severe }}</b></div><div><span>未深检</span><b>{{ job.result.summary.notDeepChecked }}</b></div><div><span>失败</span><b>{{ job.result.summary.failures }}</b></div><div><span>耗时</span><b>{{ formatNumber(job.result.summary.elapsedSeconds, 1) }}秒</b></div>
    </div>
    <div v-if="rows.length" class="table-wrap bonus-ranking position-risk-ranking">
      <table>
        <thead><tr><th>评分</th><th>账号</th><th>分类 / 时段</th><th>峰值仓位</th><th>事件前权益 / 杠杆</th><th>敞口 / 保证金</th><th>穿仓</th><th>同步同向</th><th>同步反向疑似对锁</th><th>事件盈亏</th><th>结论</th><th></th></tr></thead>
        <tbody><tr v-for="row in rows" :key="`${row.environment}-${row.server}-${row.account}`">
          <td><b :class="Number(row.score)>=60 ? 'negative' : ''">{{ formatNumber(row.score, 1) }}</b><small class="cell-sub">{{ row.level }}</small></td>
          <td><a :href="positionRiskAccountHref(row)">{{ row.account }}</a><small class="cell-sub">{{ row.platform }} / {{ row.server }}</small></td>
          <td>{{ positionClassificationLabel(row.classification) }}<small class="cell-sub">{{ row.eventStart || '-' }}<br>{{ row.eventEnd || '-' }}</small></td>
          <td><b>{{ formatNumber(row.peakLots, 2) }} 手 / {{ row.peakOrderCount || row.eventOrders || 0 }} 单</b><small class="cell-sub">名义敞口 {{ formatNumber(row.peakGrossExposure, 2) }} {{ row.currency }}</small></td>
          <td>{{ formatNumber(row.equityBefore, 2) }} {{ row.currency }}<small class="cell-sub">杠杆 1:{{ formatNumber(row.leverage, 0) }}</small></td>
          <td>{{ formatNumber(row.grossLeverage, 2) }} 倍<small class="cell-sub">预计保证金 {{ formatNumber(estimatedMarginValue(row), 2) }} {{ row.currency }}<br>保证金占权益 {{ percent(row.marginRatio) }}（越高越满）<br>保证金水平 {{ formatNumber(estimatedMarginLevelValue(row), 1) }}%（越低越满）</small></td>
          <td><b :class="row.penetrationStatus === '是' ? 'negative' : ''">{{ row.penetrationStatus || '数据不足' }}</b><small class="cell-sub position-risk-peer-preview">{{ row.penetrationReason || '-' }}</small></td>
          <td>{{ peerEvidenceReady(row) ? verifiedSameAccounts(row).length : '需重跑' }}<small class="cell-sub position-risk-peer-preview">{{ peerEvidenceReady(row) ? (verifiedSameAccounts(row).slice(0, 5).join('、') || '-') : '旧任务未验证同步平仓' }}</small></td>
          <td>{{ peerEvidenceReady(row) ? verifiedOppositeAccounts(row).length : '需重跑' }}<small class="cell-sub position-risk-peer-preview">{{ peerEvidenceReady(row) ? (verifiedOppositeAccounts(row).slice(0, 5).join('、') || '-') : '旧任务未验证同步平仓' }}</small></td>
          <td :class="Number(row.netProfit) < 0 ? 'negative' : 'positive'">{{ formatNumber(row.netProfit, 2) }} {{ row.currency }}</td>
          <td class="position-risk-conclusion">{{ row.summary || '-' }}</td>
          <td><button class="position-analysis-button" @click="openAnalysis(row)">查看分析</button></td>
        </tr></tbody>
      </table>
    </div>
    <div v-if="job?.status === 'done' && !rows.length" class="panel-state">当前榜单等级下没有命中账户，可切换为“关注及以上”或“全部”查看深检结果。</div>
    <div v-if="job?.result?.failures?.length" class="push-failure-section"><div class="push-result-subhead"><h3>部分失败（{{ job.result.failureTotal }}）</h3><span>成功服务器和账户结果已保留</span></div><div class="table-wrap"><table><thead><tr><th>阶段</th><th>账号</th><th>平台 / 服务器</th><th>数据源</th><th>原因</th></tr></thead><tbody><tr v-for="(failure,index) in job.result.failures" :key="index"><td>{{ failure.stage === 'candidate' ? '候选扫描' : failure.stage === 'candidate_route' ? '路由确认' : '账户深检' }}</td><td><a v-if="failure.account" :href="positionRiskAccountHref(failure)">{{ failure.account }}</a><span v-else>-</span></td><td>{{ failure.platform && failure.server ? `${failure.platform} / ${failure.server}` : '-' }}</td><td>{{ failure.source || '-' }}</td><td>{{ failure.reason }}</td></tr></tbody></table></div></div>

    <div v-if="selectedRow" class="position-analysis-backdrop" role="presentation" @click.self="closeAnalysis">
      <section class="position-analysis-modal" role="dialog" aria-modal="true" :aria-label="`账号 ${selectedRow.account} 重仓分析`">
        <header class="position-analysis-head">
          <div><h3>账号 {{ selectedRow.account }} · {{ positionClassificationLabel(selectedRow.classification) }}</h3><small>{{ selectedRow.platform }} / {{ selectedRow.server }} · {{ selectedRow.eventStart }} 至 {{ selectedRow.eventEnd }}</small></div>
          <button aria-label="关闭分析窗口" @click="closeAnalysis">关闭</button>
        </header>
        <div class="position-analysis-kpis">
          <div><span>峰值仓位</span><b>{{ formatNumber(selectedRow.peakLots, 2) }} 手 / {{ selectedRow.peakOrderCount || selectedRow.eventOrders || 0 }} 单</b></div>
          <div><span>峰值名义敞口</span><b>{{ formatNumber(selectedRow.peakGrossExposure, 2) }} {{ selectedRow.currency }}</b></div>
          <div><span>事件前权益</span><b>{{ formatNumber(selectedRow.equityBefore, 2) }} {{ selectedRow.currency }}</b></div>
          <div><span>账户杠杆</span><b>1:{{ formatNumber(selectedRow.leverage, 0) }}</b></div>
          <div><span>预计占用保证金</span><b>{{ formatNumber(estimatedMarginValue(selectedRow), 2) }} {{ selectedRow.currency }}</b></div>
          <div><span>保证金占权益（越高越满）</span><b>{{ percent(selectedRow.marginRatio) }}</b></div>
          <div><span>估算保证金水平（越低越满）</span><b>{{ formatNumber(estimatedMarginLevelValue(selectedRow), 1) }}%</b></div>
          <div><span>压力损失 / 权益</span><b>{{ percent(selectedRow.stressRatio) }}</b></div>
          <div><span>实际事件亏损 / 权益</span><b>{{ percent(selectedRow.lossToEquity) }}</b></div>
          <div><span>穿仓判断</span><b :class="selectedRow.penetrationStatus === '是' ? 'negative' : ''">{{ selectedRow.penetrationStatus || '数据不足' }}</b></div>
        </div>
        <div class="position-analysis-section"><h4>结论</h4><p>{{ selectedRow.summary }}</p><p>{{ selectedRow.penetrationReason }}</p><p v-if="(selectedRow.penetrationDataGaps || []).length"><b>数据不足原因：</b>{{ selectedRow.penetrationDataGaps.join('；') }}</p></div>
        <div class="position-analysis-section">
          <h4>同步开平仓检索覆盖</h4>
          <p><b>{{ selectedRow.peerSearchCoverage?.status || '数据不足' }}</b> · {{ selectedRow.peerSearchCoverage?.scope || 'AC/DBG 全平台 MT4 + MT5' }} · 已查 {{ selectedRow.peerSearchCoverage?.scannedSourceCount || 0 }}/{{ selectedRow.peerSearchCoverage?.physicalSourceTotal || 0 }} 个物理交易源 · 容差 ±{{ selectedRow.peerSearchCoverage?.toleranceSeconds ?? 5 }} 秒</p>
          <p v-if="(selectedRow.peerSearchCoverage?.scannedSources || []).length"><b>已完成：</b>{{ selectedRow.peerSearchCoverage.scannedSources.map((item: any) => `${item.platform} / ${item.server} / ${item.database}`).join('；') }}</p>
          <p v-if="(selectedRow.peerSearchCoverage?.skippedTargetOrders || []).length"><b>未参与匹配：</b>{{ selectedRow.peerSearchCoverage.skippedTargetOrders.map((item: any) => `${item.orderId || '未知订单'}：${item.reason}`).join('；') }}</p>
          <p v-for="(failure, index) in selectedRow.peerSearchCoverage?.failures || []" :key="`peer-failure-${index}`" class="inline-warning">{{ failure.platform }} / {{ failure.server }} / {{ failure.database }}：{{ failure.reason }}</p>
        </div>
        <div class="position-peer-columns">
          <div><h4>同步同向账户（{{ verifiedSameAccounts(selectedRow).length }}）</h4><p>{{ peerEvidenceReady(selectedRow) ? (verifiedSameAccounts(selectedRow).join('、') || '未发现') : '旧任务没有验证同步平仓，请重新运行扫描' }}</p></div>
          <div><h4>同步反向疑似对锁账户（{{ verifiedOppositeAccounts(selectedRow).length }}）</h4><p>{{ peerEvidenceReady(selectedRow) ? (verifiedOppositeAccounts(selectedRow).join('、') || '未发现') : '旧任务没有验证同步平仓，请重新运行扫描' }}</p><small>只有同品种、开仓和平仓都相差不超过5秒，且较小手数不低于较大手数80%才列入；反向同步只是疑似对锁证据，不等于已经确认。</small></div>
        </div>
        <div class="position-analysis-section"><h4>同步同向订单（共 {{ selectedRow.sameDirectionMatchTotal ?? (selectedRow.sameDirectionMatches || []).length }} 组）</h4>
          <p v-if="selectedRow.peerMatchesTruncated" class="tool-note">订单对较多，明细最多保留 {{ selectedRow.peerMatchDetailLimit || 500 }} 组；账号总数和订单对总数仍按完整结果计算。</p>
          <div class="table-wrap position-order-table"><table><thead><tr><th>目标订单</th><th>同行账号 / 来源</th><th>同行订单 / 仓位</th><th>品种 / 方向 / 手数</th><th>同步开仓</th><th>同步平仓</th></tr></thead><tbody>
            <tr v-for="(match, index) in selectedRow.sameDirectionMatches || []" :key="`same-${match.account}-${match.orderId}-${index}`"><td>{{ match.targetOrderId }}<small class="cell-sub">仓位 {{ match.targetPositionId || '-' }}</small></td><td>{{ match.account }}<small class="cell-sub">{{ match.platform }} / {{ match.server }}<br>{{ match.database }}</small></td><td>{{ match.orderId }}<small class="cell-sub">仓位 {{ match.positionId || '-' }}<br>成交 {{ match.dealId || '-' }}</small></td><td>{{ match.symbol }} / {{ directionLabel(match.direction) }} / {{ formatNumber(match.volume, 2) }} 手</td><td>目标 {{ match.targetOpenTime }}<small class="cell-sub">同行 {{ match.openTime }} · 差 {{ formatNumber(match.openDeltaSeconds, 3) }} 秒</small></td><td>目标 {{ match.targetCloseTime }}<small class="cell-sub">同行 {{ match.closeTime }} · 差 {{ formatNumber(match.closeDeltaSeconds, 3) }} 秒</small></td></tr>
            <tr v-if="!(selectedRow.sameDirectionMatches || []).length"><td colspan="6" class="empty-cell">未找到同步同向开平仓订单。</td></tr>
          </tbody></table></div>
        </div>
        <div class="position-analysis-section"><h4>同步反向疑似对锁订单（共 {{ selectedRow.oppositeDirectionMatchTotal ?? (selectedRow.oppositeDirectionMatches || []).length }} 组）</h4>
          <div class="table-wrap position-order-table"><table><thead><tr><th>目标订单</th><th>反向账号 / 来源</th><th>反向订单 / 仓位</th><th>品种 / 方向 / 手数</th><th>同步开仓</th><th>同步平仓</th></tr></thead><tbody>
            <tr v-for="(match, index) in selectedRow.oppositeDirectionMatches || []" :key="`opposite-${match.account}-${match.orderId}-${index}`"><td>{{ match.targetOrderId }}<small class="cell-sub">仓位 {{ match.targetPositionId || '-' }}</small></td><td>{{ match.account }}<small class="cell-sub">{{ match.platform }} / {{ match.server }}<br>{{ match.database }}</small></td><td>{{ match.orderId }}<small class="cell-sub">仓位 {{ match.positionId || '-' }}<br>成交 {{ match.dealId || '-' }}</small></td><td>{{ match.symbol }}<small class="cell-sub">目标 {{ directionLabel(match.targetDirection) }} {{ formatNumber(match.targetVolume, 2) }} 手<br>反向 {{ directionLabel(match.direction) }} {{ formatNumber(match.volume, 2) }} 手<br>手数相似度 {{ formatNumber(Number(match.lotSimilarity || 0) * 100, 1) }}%</small></td><td>目标 {{ match.targetOpenTime }}<small class="cell-sub">反向 {{ match.openTime }} · 差 {{ formatNumber(match.openDeltaSeconds, 3) }} 秒</small></td><td>目标 {{ match.targetCloseTime }}<small class="cell-sub">反向 {{ match.closeTime }} · 差 {{ formatNumber(match.closeDeltaSeconds, 3) }} 秒</small></td></tr>
            <tr v-if="!(selectedRow.oppositeDirectionMatches || []).length"><td colspan="6" class="empty-cell">未找到同步反向开平仓订单。</td></tr>
          </tbody></table></div>
        </div>
        <div class="position-analysis-section"><h4>重仓开赌订单（{{ (selectedRow.heavyOrders || []).length }}）</h4>
          <div class="table-wrap position-order-table"><table><thead><tr><th>订单号</th><th>仓位号</th><th>品种 / 方向</th><th>手数</th><th>开仓时间 / 价格</th><th>平仓时间 / 持仓</th><th>仓位净盈亏</th><th>判定原因</th></tr></thead><tbody>
            <tr v-for="(order, index) in selectedRow.heavyOrders || []" :key="`${order.orderId}-${index}`"><td>{{ order.orderId || '-' }}</td><td>{{ order.positionId || '-' }}</td><td>{{ order.symbol }} / {{ directionLabel(order.direction) }}</td><td>{{ formatNumber(order.volume, 2) }}</td><td>{{ order.openTime }}<small class="cell-sub">{{ formatNumber(order.openPrice, 5) }}</small></td><td>{{ order.closeTime || '未平仓' }}<small class="cell-sub">{{ order.holdingMinutes == null ? '-' : `${formatNumber(order.holdingMinutes, 1)} 分钟` }}</small></td><td :class="Number(order.positionNetProfit) < 0 ? 'negative' : 'positive'">{{ formatNumber(order.positionNetProfit, 2) }}</td><td class="position-order-reason">{{ order.reason }}</td></tr>
            <tr v-if="!(selectedRow.heavyOrders || []).length"><td colspan="8" class="empty-cell">该历史结果没有订单级明细，请重新运行扫描。</td></tr>
          </tbody></table></div>
        </div>
        <div class="position-analysis-section"><h4>命中依据</h4><p>{{ (selectedRow.triggeredRules || []).join('；') || '未命中重仓规则' }}</p></div>
        <div v-if="(selectedRow.negativeBalanceEvidence || []).length" class="position-analysis-section"><h4>负余额清零 / 补正流水</h4><p v-for="item in selectedRow.negativeBalanceEvidence" :key="`${item.time}-${item.amount}`">{{ item.time }} · {{ formatNumber(item.amount, 2) }} {{ selectedRow.currency }} · {{ item.comment }}</p></div>
        <div class="position-analysis-section"><h4>数据限制</h4><p>{{ (selectedRow.limitations || []).join('；') || '无额外限制说明' }}</p></div>
      </section>
    </div>
  </div>
</template>
