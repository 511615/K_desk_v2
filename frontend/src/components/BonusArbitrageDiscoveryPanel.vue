<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '../api'
import { bonusAccountHref, bonusHedgeFinding, bonusPeakOrders, filterBonusResults } from '../bonusDiscovery'
import { pushPollRetryDelay, recoverPushPollingState } from '../pushDiscovery'

const environmentOptions = [
  { value: 'ac_gb', label: 'AC GB' },
  { value: 'ac_cn', label: 'AC CN' },
  { value: 'dbg_cn', label: 'DBG CN' },
  { value: 'dbg_vn', label: 'DBG VN' },
]
const storageKey = 'kdesk.bonusArbitrageScanJobId'
const form = reactive({
  start: localDate(-30),
  end: localDate(0),
  environments: environmentOptions.map(item => item.value),
  deepLimit: 100,
  minGrant: 0,
  excludeHandled: true,
  level: 'warning',
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
function marginLevel(cycle: any): number | null {
  const value = cycle?.minimumMarginLevel
  return value === null || value === undefined || value === '' ? null : Number(value)
}
function marginLots(cycle: any): unknown { return cycle?.minimumConcurrentLots ?? cycle?.earlyPeakConcurrentLots }
function marginOrderCount(cycle: any): unknown { return cycle?.minimumOrderCount ?? cycle?.earlyPeakOrderCount }
function marginAt(cycle: any): unknown { return cycle?.minimumMarginAt || cycle?.earlyPeakAt }
function directionLabel(value: unknown): string { return String(value || '').toLowerCase() === 'buy' ? '买入' : '卖出' }
function openAnalysis(row: any): void { selectedRow.value = row }
function closeAnalysis(): void { selectedRow.value = null }
function handleKeydown(event: KeyboardEvent): void { if (event.key === 'Escape') closeAnalysis() }
const rows = computed(() => filterBonusResults(job.value?.result?.allResults || job.value?.result?.results, form.level))
function jobMessage(): string {
  if (!job.value) return '尚未运行'
  if (job.value.connectionError) return job.value.connectionError
  const events = job.value.events || []
  return events.length ? events[events.length - 1].message : job.value.error || ({ queued: '已提交，等待扫描', running: '正在扫描', done: '扫描完成', failed: '扫描失败', cancelled: '已取消' } as any)[job.value.status] || ''
}
async function poll(id: string): Promise<void> {
  try {
    job.value = await api<any>(`/api/bonus-arbitrage/scans/${encodeURIComponent(id)}`)
    pollFailures = 0
    localStorage.setItem(storageKey, id)
    if (!['done', 'failed', 'cancelled'].includes(job.value.status)) timer = window.setTimeout(() => poll(id), 1400)
  } catch (error: any) {
    if (error instanceof ApiError && error.status === 404) {
      localStorage.removeItem(storageKey)
      job.value = { status: 'failed', error: '之前的赠金套利任务记录已不存在' }
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
    const response = await api<any>('/api/bonus-arbitrage/scans', {
      method: 'POST',
      body: JSON.stringify({
        start: form.start,
        end: form.end,
        environments: form.environments,
        deepLimit: form.deepLimit,
        minGrant: form.minGrant,
        excludeHandled: form.excludeHandled,
      }),
    })
    job.value = response.job
    localStorage.setItem(storageKey, response.job.id)
    await poll(response.job.id)
  } catch (error: any) {
    job.value = { status: 'failed', error: error.message || '提交赠金套利扫描失败' }
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
    const response = await api<any>('/api/bonus-arbitrage/scans/active')
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
  <div class="bonus-discovery">
    <div class="bonus-scan-controls">
      <label>开始时间<input v-model="form.start" type="datetime-local"></label>
      <label>结束时间<input v-model="form.end" type="datetime-local"></label>
      <fieldset><legend>环境</legend><label v-for="item in environmentOptions" :key="item.value"><input v-model="form.environments" type="checkbox" :value="item.value">{{ item.label }}</label></fieldset>
      <label>深检账号上限<input v-model.number="form.deepLimit" type="number" min="1" max="300"></label>
      <label class="bonus-handled-toggle"><input v-model="form.excludeHandled" type="checkbox">排除已处置账户</label>
      <label>最低赠金额<input v-model.number="form.minGrant" type="number" min="0" max="10000000" step="10"></label>
      <label>榜单等级<select v-model="form.level"><option value="warning">预警及以上</option><option value="high">高危及以上</option><option value="severe">仅严重</option><option value="concern">关注及以上</option><option value="all">全部</option></select></label>
      <button class="primary" :disabled="job && ['queued','running'].includes(job.status)" @click="start">{{ job && ['queued','running'].includes(job.status) ? '扫描中…' : '开始赠金套利检测' }}</button>
      <button v-if="job && ['queued','running'].includes(job.status)" :disabled="job.cancel_requested" @click="cancel">{{ job.cancel_requested ? '正在停止…' : '取消' }}</button>
    </div>
    <small class="tool-note">扫描窗口只用于发现发生过正向 Credit / Bonus 的账户；候选默认按当前占用保证金 / 累计入金从高到低进入深检，比例只影响顺序、不参与评分。默认最近30天，最长180天。</small>
    <div v-if="job" class="job-card"><div class="job-head"><b>{{ jobMessage() }}</b><span>{{ job.progress || 0 }}%</span></div><div class="progress"><i :style="{ width: `${job.progress || 0}%` }" /></div><div v-if="job.connectionError" class="inline-warning">{{ job.connectionDetail }}</div><div v-if="job.error" class="inline-error">{{ job.error }}</div></div>
    <div v-if="job?.result?.summary" class="bonus-scan-summary">
      <div><span>赠金候选</span><b>{{ job.result.summary.candidateAccounts }}</b></div><div><span>保留候选</span><b>{{ job.result.summary.retainedCandidates }}</b></div><div><span>实际深检</span><b>{{ job.result.summary.analyzedAccounts }}</b></div><div><span>预警</span><b>{{ job.result.summary.warnings }}</b></div><div><span>高危</span><b>{{ job.result.summary.highRisk }}</b></div><div><span>严重</span><b>{{ job.result.summary.severe }}</b></div><div><span>未深检</span><b>{{ job.result.summary.notDeepChecked }}</b></div><div><span>失败</span><b>{{ job.result.summary.failures }}</b></div><div><span>耗时</span><b>{{ formatNumber(job.result.summary.elapsedSeconds, 1) }}秒</b></div>
    </div>
    <div v-if="rows.length" class="table-wrap bonus-ranking bonus-risk-ranking">
      <table>
        <thead><tr><th>评分</th><th>账号</th><th>平台 / 服务器</th><th>保证金 / 累计入金</th><th>窗口赠金</th><th>历史周期</th><th>最强周期入金 / 赠金</th><th>最低保证金水平 / 手数</th><th>交易净利</th><th>提取金额</th><th>闭环匹配</th><th>疑似对锁</th><th>结论</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="`${row.environment}-${row.server}-${row.account}`">
          <td><b :class="Number(row.score)>=60 ? 'negative' : ''">{{ formatNumber(row.score, 1) }}</b><small class="cell-sub">{{ row.level }} · 置信度{{ row.confidence }}</small></td>
          <td><a :href="bonusAccountHref(row)">{{ row.account }}</a><small class="cell-sub">{{ row.environment }}</small></td>
          <td>{{ row.platform }} / {{ row.server }}</td>
          <td>{{ formatNumber(row.currentMargin, 2) }} / {{ formatNumber(row.depositTotal, 2) }}<small class="cell-sub">{{ Number(row.depositTotal) > 0 ? percent(row.marginToDeposit) : '入金不可用' }}</small></td>
          <td>{{ formatNumber(row.candidateGrantAmount, 2) }} {{ row.currency }}<small class="cell-sub">{{ row.candidateGrantCount }}次 · 最近{{ row.latestGrant }}</small></td>
          <td>{{ row.cycleCount }}</td>
          <td>{{ formatNumber(row.bestCycle?.cashDeposit, 2) }} / {{ formatNumber(row.bestCycle?.grantAmount, 2) }}</td>
          <td><b :class="marginLevel(row.bestCycle) !== null && Number(marginLevel(row.bestCycle)) <= 200 ? 'negative' : ''">{{ marginLevel(row.bestCycle) === null ? '历史结果待重扫' : `${formatNumber(marginLevel(row.bestCycle), 1)}%` }}</b><small class="cell-sub">{{ formatNumber(marginLots(row.bestCycle), 2) }} 手 · {{ marginOrderCount(row.bestCycle) ?? '-' }} 单</small></td>
          <td :class="Number(row.bestCycle?.netProfit) < 0 ? 'negative' : 'positive'">{{ formatNumber(row.bestCycle?.netProfit, 2) }}</td>
          <td>{{ formatNumber(row.bestCycle?.matchedExtraction, 2) }}<small class="cell-sub">{{ row.bestCycle?.extractionBasis === 'attempted' ? '申请提取' : '实际提取' }}</small></td>
          <td>{{ percent(row.bestCycle?.extractionMatch) }}</td>
          <td><b :class="bonusHedgeFinding(row).found ? 'negative' : ''">{{ bonusHedgeFinding(row).found ? `发现 ${bonusHedgeFinding(row).matches} 组` : '未发现' }}</b><small class="cell-sub">可见反向同步覆盖 {{ percent(bonusHedgeFinding(row).coverage) }}</small></td>
          <td><button class="bonus-analysis-button" @click="openAnalysis(row)">查看详细结论</button></td>
        </tr></tbody>
      </table>
    </div>
    <div v-if="job?.status === 'done' && !rows.length" class="panel-state">当前榜单等级下没有命中账户，可切换为“关注及以上”或“全部”查看深检结果。</div>
    <div v-if="job?.result?.failures?.length" class="push-failure-section"><div class="push-result-subhead"><h3>部分失败（{{ job.result.failureTotal }}）</h3><span>成功服务器和账户结果已保留</span></div><div class="table-wrap"><table><thead><tr><th>阶段</th><th>账号</th><th>平台 / 服务器</th><th>数据源</th><th>时间段</th><th>原因</th></tr></thead><tbody><tr v-for="(failure,index) in job.result.failures" :key="index"><td>{{ failure.stage === 'candidate' ? '候选扫描' : failure.stage === 'candidate_rank' ? '候选排序' : '账户深检' }}</td><td><a v-if="failure.account" :href="bonusAccountHref(failure)">{{ failure.account }}</a><span v-else>-</span></td><td>{{ failure.platform && failure.server ? `${failure.platform} / ${failure.server}` : failure.environment || '-' }}</td><td>{{ failure.source || '-' }}</td><td>{{ failure.start ? `${failure.start} 至 ${failure.end}` : '-' }}</td><td>{{ failure.reason }}</td></tr></tbody></table></div></div>

    <div v-if="selectedRow" class="bonus-analysis-backdrop" role="presentation" @click.self="closeAnalysis">
      <section class="bonus-analysis-card" role="dialog" aria-modal="true" :aria-label="`账号 ${selectedRow.account} 赠金套利详细结论`">
        <header class="bonus-analysis-head">
          <div><h3>账号 {{ selectedRow.account }} · {{ selectedRow.level }}</h3><small>{{ selectedRow.platform }} / {{ selectedRow.server }} · 最强周期 {{ selectedRow.bestCycle?.started || '-' }} 至 {{ selectedRow.bestCycle?.ended || '-' }}</small></div>
          <button aria-label="关闭详细结论" @click="closeAnalysis">关闭</button>
        </header>
        <div class="bonus-analysis-kpis">
          <div><span>评分 / 置信度</span><b>{{ formatNumber(selectedRow.score, 1) }} / {{ selectedRow.confidence }}</b></div>
          <div><span>周期最低保证金水平</span><b>{{ marginLevel(selectedRow.bestCycle) === null ? '历史结果待重扫' : `${formatNumber(marginLevel(selectedRow.bestCycle), 1)}%` }}</b></div>
          <div><span>最低点持仓</span><b>{{ formatNumber(marginLots(selectedRow.bestCycle), 2) }} 手 / {{ marginOrderCount(selectedRow.bestCycle) ?? '-' }} 单</b></div>
          <div><span>最低点发生时间</span><b>{{ marginAt(selectedRow.bestCycle) || '历史结果无明细' }}</b></div>
          <div><span>赠金 / 入金</span><b>{{ percent(selectedRow.bestCycle?.bonusToCash) }}</b></div>
        </div>

        <div class="bonus-analysis-section"><h4>重仓定义</h4><p>保证金水平 = 净值 ÷ 已用保证金 × 100%。比例越低，仓位越满、爆仓风险越高；赠金有效周期内最低值不高于 200% 即按重仓处理。</p><p v-if="marginLevel(selectedRow.bestCycle) !== null">最低点净值 {{ formatNumber(selectedRow.bestCycle?.minimumEquity, 2) }}，已用保证金 {{ formatNumber(selectedRow.bestCycle?.minimumUsedMargin, 2) }}，保证金水平 {{ formatNumber(marginLevel(selectedRow.bestCycle), 1) }}%。</p><small v-if="selectedRow.bestCycle?.minimumMarginBasis">{{ selectedRow.bestCycle.minimumMarginBasis }}{{ selectedRow.bestCycle.minimumMarginReliable ? '' : '；历史结果为估算值，请结合订单复核。' }}</small></div>

        <div class="bonus-analysis-section bonus-conclusion-block"><h4>结论</h4><p>{{ selectedRow.summary || '暂无结论' }}</p></div>

        <div class="bonus-analysis-section">
          <h4>是否发现对锁单</h4>
          <p><b :class="bonusHedgeFinding(selectedRow).found ? 'negative' : ''">{{ bonusHedgeFinding(selectedRow).found ? `发现 ${bonusHedgeFinding(selectedRow).matches} 组同品种反向同步订单` : '未发现平台内可见的反向同步订单' }}</b>，覆盖本账户同期手数 {{ percent(bonusHedgeFinding(selectedRow).coverage) }}。</p>
          <p v-if="bonusHedgeFinding(selectedRow).accounts.length">疑似关联账户：{{ bonusHedgeFinding(selectedRow).accounts.join('、') }}</p>
          <small>这里只能确认平台内可见的同品种、5秒内反向开仓证据；发现代表疑似对锁，未发现也不能排除跨平台对锁。</small>
          <div v-if="bonusHedgeFinding(selectedRow).details.length" class="table-wrap bonus-evidence-table"><table><thead><tr><th>本账号订单</th><th>关联账号 / 订单</th><th>品种</th><th>双方手数</th><th>开仓时间差</th></tr></thead><tbody>
            <tr v-for="(match, index) in bonusHedgeFinding(selectedRow).details" :key="`${match.subjectTrade}-${match.peerTrade}-${index}`"><td>{{ match.subjectTrade }}</td><td>{{ match.account }} / {{ match.peerTrade }}</td><td>{{ match.symbol }}</td><td>{{ formatNumber(match.subjectVolume, 2) }} / {{ formatNumber(match.peerVolume, 2) }}</td><td>{{ formatNumber(match.openDeltaSeconds, 3) }} 秒</td></tr>
          </tbody></table></div>
        </div>

        <div class="bonus-analysis-section">
          <h4>最低保证金水平对应订单（{{ marginOrderCount(selectedRow.bestCycle) ?? bonusPeakOrders(selectedRow).length }}）</h4>
          <p>以下订单在 {{ marginAt(selectedRow.bestCycle) || '最低点时刻' }} 同时持有，合计 {{ formatNumber(marginLots(selectedRow.bestCycle), 2) }} 手。</p>
          <div v-if="bonusPeakOrders(selectedRow).length" class="table-wrap bonus-evidence-table"><table><thead><tr><th>订单 / 仓位号</th><th>品种 / 方向</th><th>手数</th><th>估算保证金</th><th>开仓时间</th><th>平仓时间</th><th>净盈亏</th></tr></thead><tbody>
            <tr v-for="(order, index) in bonusPeakOrders(selectedRow)" :key="`${order.tradeId}-${index}`"><td>{{ order.tradeId || '-' }}</td><td>{{ order.symbol }} / {{ directionLabel(order.direction) }}</td><td>{{ formatNumber(order.volume, 2) }}</td><td>{{ order.estimatedMargin === undefined ? '-' : formatNumber(order.estimatedMargin, 2) }}</td><td>{{ order.openTime || '-' }}</td><td>{{ order.isOpen ? '当前仍持仓' : order.closeTime || '-' }}</td><td :class="Number(order.netProfit) < 0 ? 'negative' : 'positive'">{{ formatNumber(order.netProfit, 2) }}</td></tr>
          </tbody></table></div>
          <p v-else class="bonus-evidence-empty">该任务结果生成于订单明细字段上线前，请重新运行扫描后查看峰值对应订单。</p>
          <small v-if="selectedRow.bestCycle?.minimumMarginOrdersTruncated || selectedRow.bestCycle?.earlyPeakOrdersTruncated">最低点订单较多，弹窗展示前50笔；总手数和订单总数仍按全部订单计算。</small>
        </div>

        <div class="bonus-analysis-section"><h4>命中依据</h4><p>{{ (selectedRow.triggeredRules || []).join('；') || '未命中明确规则' }}</p></div>
        <div class="bonus-analysis-section"><h4>仍不能确定的地方</h4><p>{{ (selectedRow.limitations || []).join('；') || '无额外限制说明' }}</p></div>
      </section>
    </div>
  </div>
</template>
