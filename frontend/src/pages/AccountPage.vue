<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, queryString } from '../api'
import DailyBarChart from '../components/DailyBarChart.vue'
import PanelState from '../components/PanelState.vue'
import PnlLineChart from '../components/PnlLineChart.vue'

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const login = computed(() => String(route.params.login || ''))
const filters = reactive({ platform: String(route.query.platform || ''), server: String(route.query.server || ''), symbol: String(route.query.symbol || '') })
const dateFilters = reactive({ start: String(route.query.start || ''), end: String(route.query.end || '') })
const filterQuery = computed(() => queryString({ ...filters, ...dateFilters }))
const saveState = ref('')
const orderPage = ref(1)
const showOrders = ref(false)
const showToxic = ref(false)
const selectedToxic = ref<string[]>([])
const toxicMode = ref('selected')
const toxicJob = ref<any>(null)
const syncPeerFilter = ref('')
const klineJob = ref<any>(null)
const klineForm = reactive({ start: '', end: '', includeTimeline: false, refreshTimelineCache: false })
const copyGroupRequested = ref(false)
const pollingTimers = new Set<number>()

const detail = useQuery({ queryKey: computed(() => ['detail', login.value, filterQuery.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/detail${filterQuery.value}`) })
const risk = useQuery({ queryKey: computed(() => ['risk', login.value, filterQuery.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/risk-panels${filterQuery.value}`) })
const automation = useQuery({ queryKey: computed(() => ['automation', login.value, filterQuery.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/automation-analysis${filterQuery.value}`) })
const ledger = useQuery({ queryKey: computed(() => ['ledger', login.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/ledger`) })
const ips = useQuery({ queryKey: computed(() => ['ips', login.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/login-ips`) })
const toxicTypes = useQuery({ queryKey: ['toxic-types'], queryFn: () => api<any>('/api/toxic/check-types') })
const orders = useQuery({
  queryKey: computed(() => ['orders', login.value, orderPage.value]),
  queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/orders?page=${orderPage.value}&page_size=20`),
  enabled: computed(() => showOrders.value),
})
const copyGroups = useQuery({
  queryKey: computed(() => ['copy-groups', login.value, filterQuery.value]),
  queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/copy-group-profit${filterQuery.value}`),
  enabled: computed(() => copyGroupRequested.value),
})

const database = computed(() => detail.data.value?.database || {})
const metrics = computed(() => database.value.metrics || {})
const visuals = computed(() => database.value.visualizations || {})
const panels = computed(() => risk.data.value?.riskPanels || {})
const finance = computed(() => panels.value.finance || {})
const highFrequency = computed(() => panels.value.highFrequency || {})
const sameName = computed<any[]>(() => panels.value.sameName || [])
const sameNameTotals = computed(() => panels.value.sameNameTotals || {})
const automationCopy = computed(() => automation.data.value?.copy || {})
const automationEa = computed(() => automation.data.value?.ea || {})
const pushSync = computed(() => toxicJob.value?.result?.pushSync || {})
const syncComparisonRows = computed<any[]>(() => {
  const rows = Array.isArray(pushSync.value.comparisonRows) ? pushSync.value.comparisonRows : []
  const filtered = syncPeerFilter.value ? rows.filter((row: any) => String(row.peerAccount) === syncPeerFilter.value) : rows
  return filtered.slice(0, 200)
})
const form = reactive({ action: '', group: '', tags: '', note: '', status: '待复核', owner: '' })

watch(() => ledger.data.value?.record, record => {
  form.action = record?.['建议动作'] || ''
  form.group = record?.['当前分组'] || ''
  form.tags = record?.['风险标签'] || ''
  form.note = record?.['风险/问题备注'] || ''
  form.status = record?.['状态'] || '待复核'
  form.owner = record?.['处理人/来源'] || ''
}, { immediate: true })

watch(() => toxicTypes.data.value?.types, types => {
  if (!selectedToxic.value.length && types?.length) selectedToxic.value = types.filter((item: any) => !item.requiresTick).map((item: any) => item.id)
}, { immediate: true })

function number(value: unknown, digits = 2): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(parsed) : '-'
}
function money(value: unknown): string { return number(value, 2) }
function signedMoney(value: unknown): string { const parsed = Number(value); return Number.isFinite(parsed) ? `${parsed > 0 ? '+' : ''}${money(parsed)}` : '-' }
function duration(seconds: unknown): string {
  const value = Number(seconds)
  if (!Number.isFinite(value)) return '-'
  if (value < 60) return `${value.toFixed(1)} 秒`
  if (value < 3600) return `${(value / 60).toFixed(1)} 分钟`
  return `${(value / 3600).toFixed(1)} 小时`
}
function optionValue(item: unknown): string {
  if (typeof item === 'string') return item
  if (item && typeof item === 'object') return String((item as Record<string, unknown>).value || (item as Record<string, unknown>).label || '')
  return String(item || '')
}
function percent(value: unknown): string { const parsed = Number(value); return Number.isFinite(parsed) ? `${parsed.toFixed(1)}%` : '-' }
function valueClass(value: unknown): string { return Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : '' }
function jobMessage(job: any): string { return job?.events?.length ? job.events[job.events.length - 1].message : job?.error || ({ queued: '任务已提交', running: '任务执行中', done: '任务完成', failed: '任务失败', cancelled: '任务已取消' } as any)[job?.status] || '' }
function syncDelta(value: unknown): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed > 0 ? '+' : ''}${parsed.toFixed(3).replace(/\.000$/, '')} 秒` : '-'
}
function syncDirection(value: unknown): string { return String(value) === 'buy' ? '买入' : String(value) === 'sell' ? '卖出' : String(value || '-') }

async function applyFilters() {
  orderPage.value = 1
  await router.replace({ query: Object.fromEntries(Object.entries({ ...filters, ...dateFilters }).filter(([, value]) => value)) })
}
async function saveMark() {
  saveState.value = 'saving'
  try {
    await api('/api/accounts/mark', { method: 'POST', body: JSON.stringify({ account: login.value, ...form }) })
    await Promise.all([queryClient.invalidateQueries({ queryKey: ['ledger', login.value] }), queryClient.invalidateQueries({ queryKey: ['detail', login.value] })])
    saveState.value = 'saved'
    window.setTimeout(() => { if (saveState.value === 'saved') saveState.value = '' }, 1800)
  } catch (error: any) { saveState.value = error.message || '保存失败' }
}
function useQuickAction(action: string) { form.action = action === '自定义' ? '' : action }

async function pollJob(kind: 'kline' | 'toxic', id: string) {
  try {
    const current = await api<any>(`/api/${kind}/jobs/${encodeURIComponent(id)}`)
    if (kind === 'kline') klineJob.value = current
    else toxicJob.value = current
    if (!['done', 'failed', 'cancelled'].includes(current.status)) {
      const timer = window.setTimeout(() => { pollingTimers.delete(timer); pollJob(kind, id) }, 1100)
      pollingTimers.add(timer)
    } else if (kind === 'kline' && current.status === 'done') {
      await queryClient.invalidateQueries({ queryKey: ['detail', login.value] })
    }
  } catch (error: any) {
    const target = { status: 'failed', error: error.message || '读取任务失败' }
    if (kind === 'kline') klineJob.value = target
    else toxicJob.value = target
  }
}
async function startKline() {
  klineJob.value = { status: 'queued', progress: 0 }
  try {
    const response = await api<any>('/api/kline/generate-from-db', { method: 'POST', body: JSON.stringify({ account: login.value, ...filters, ...klineForm }) })
    klineJob.value = response.job
    await pollJob('kline', response.job.id)
  } catch (error: any) { klineJob.value = { status: 'failed', error: error.message || '提交失败' } }
}
async function startToxic() {
  if (toxicMode.value === 'selected' && !selectedToxic.value.length) return
  syncPeerFilter.value = ''
  toxicJob.value = { status: 'queued', progress: 0 }
  try {
    const response = await api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/toxic-checks`, { method: 'POST', body: JSON.stringify({ mode: toxicMode.value, types: selectedToxic.value, ...filters, ...dateFilters }) })
    toxicJob.value = response.job
    await pollJob('toxic', response.job.id)
  } catch (error: any) { toxicJob.value = { status: 'failed', error: error.message || '提交失败' } }
}
async function cancelJob(job: any) {
  if (!job?.id) return
  const result = await api<any>(`/api/jobs/${encodeURIComponent(job.id)}/cancel`, { method: 'POST' })
  if (job.kind === 'toxic_check') toxicJob.value = result
  else klineJob.value = result
}
function toggleOrders() { showOrders.value = !showOrders.value }
function requestCopyGroups() { copyGroupRequested.value = true }

onBeforeUnmount(() => pollingTimers.forEach(timer => window.clearTimeout(timer)))
</script>

<template>
  <header class="topbar account-topbar"><div><RouterLink to="/">← 返回台账</RouterLink><b>账号详情</b><span>模块化开发版 · 8877</span></div><nav><a :href="`${route.fullPath}${route.fullPath.includes('?') ? '&' : '?'}legacy=1`">旧版完整页面</a></nav></header>
  <main class="account-page dense-page">
    <section class="account-shell">
      <div class="account-summary-row">
        <div><div class="eyebrow">账户风险画像</div><h1>{{ login }}</h1><div class="account-badges"><span>{{ ledger.data.value?.marked ? '已标记' : '未标记' }}</span><span>{{ database.exists ? '数据库有订单' : '数据库无订单' }}</span><span>{{ database.accountMeta?.displayCurrency || database.accountMeta?.currency || '币种读取中' }}</span><span v-if="metrics.hasEaTrades" class="cyan-badge">EA</span><span v-if="metrics.hasCopyTrades" class="violet-badge">跟单</span></div></div>
        <div class="account-meta"><b>{{ filters.platform || database.latestSource?.platform || '-' }} / {{ filters.server || database.latestSource?.server || '-' }}</b><span>最近交易 {{ metrics.lastTradeTime || database.lastTime || '-' }}</span><span>刷新 {{ database.refreshedAt || '-' }}</span></div>
      </div>

      <div class="mark-zone">
        <div class="mark-toolbar"><div><span class="field-caption">快捷标记</span><div class="quick-actions"><button v-for="item in detail.data.value?.actions || ['B','M','P','T','A','A/TA','待定','自定义']" :key="item" :class="{active: form.action===item}" @click="useQuickAction(item)">{{ item }}</button></div></div><label>本地状态（选择即保存）<select v-model="form.status" @change="saveMark"><option v-for="item in ledger.data.value?.statuses || ['待复核','观察中','已确认','已关闭']" :key="item">{{ item }}</option></select></label><button class="primary large" :disabled="saveState==='saving'" @click="saveMark">{{ saveState==='saving' ? '保存中…' : saveState==='saved' ? '已保存' : '保存全部' }}</button></div>
        <div class="mark-fields"><label>当前分组<input v-model="form.group"></label><label>风险标签<input v-model="form.tags"></label><label>风险备注<input v-model="form.note"></label><label>处理人 / 来源<input v-model="form.owner"></label></div>
        <div v-if="saveState && !['saving','saved'].includes(saveState)" class="inline-error">{{ saveState }}</div>
      </div>

      <div class="filter-zone"><label>平台<select v-model="filters.platform"><option value="">全部平台</option><option v-for="item in database.platforms || []" :key="optionValue(item)" :value="optionValue(item)">{{ optionValue(item) }}</option></select></label><label>服务器<select v-model="filters.server"><option value="">全部服务器</option><option v-for="item in database.servers || []" :key="optionValue(item)" :value="optionValue(item)">{{ optionValue(item) }}</option></select></label><label>品种<select v-model="filters.symbol"><option value="">全部品种</option><option v-for="item in database.symbols || []" :key="optionValue(item)" :value="optionValue(item)">{{ optionValue(item) }}</option></select></label><label>检测开始<input v-model="dateFilters.start" type="datetime-local" step="1"></label><label>检测结束<input v-model="dateFilters.end" type="datetime-local" step="1"></label><button class="primary" @click="applyFilters">刷新指标</button><button @click="requestCopyGroups">跟单查询</button><button class="toxic-button" @click="showToxic=!showToxic">Toxic 检测</button></div>
    </section>

    <section v-if="showToxic" class="panel toxic-panel">
      <div class="section-head"><div><h2>Toxic 风险检测</h2><small>持久化 Worker · 支持进度、重启恢复与取消</small></div><button class="text-button" @click="showToxic=false">关闭</button></div>
      <div class="toxic-modes"><label><input v-model="toxicMode" value="screen" type="radio">快速筛查</label><label><input v-model="toxicMode" value="selected" type="radio">指定项目深检</label></div>
      <div class="toxic-options" :class="{muted:toxicMode==='screen'}"><label v-for="item in toxicTypes.data.value?.types || []" :key="item.id"><input v-model="selectedToxic" :value="item.id" type="checkbox" :disabled="toxicMode==='screen'">{{ item.label }}<small v-if="item.requiresTick">需要 Tick</small></label></div>
      <div class="task-actions"><button class="toxic-button" :disabled="toxicJob && ['queued','running'].includes(toxicJob.status)" @click="startToxic">开始检测</button><button v-if="toxicJob && ['queued','running'].includes(toxicJob.status)" @click="cancelJob(toxicJob)">取消任务</button></div>
      <div v-if="toxicJob" class="job-card">
        <div class="job-head"><b>{{ jobMessage(toxicJob) }}</b><span>{{ toxicJob.progress || 0 }}%</span></div>
        <div class="progress"><i :style="{width:`${toxicJob.progress || 0}%`}" /></div>
        <div v-if="toxicJob.error" class="inline-error">{{ toxicJob.error }}</div>
        <div v-if="toxicJob.result?.results?.length" class="toxic-results"><article v-for="(item,index) in toxicJob.result.results" :key="item.id || index"><div><b>{{ item.label || item.type || item.id }}</b><span :class="Number(item.score)>=60 ? 'negative' : 'positive'">{{ item.conclusion || item.level || (Number(item.score)>=60 ? '命中' : '未命中') }}</span></div><p>{{ item.summary || item.message || '' }}</p><pre v-if="item.evidence">{{ JSON.stringify(item.evidence, null, 2) }}</pre></article></div>
        <details v-else-if="toxicJob.status==='done'"><summary>查看完整检测结果</summary><pre>{{ JSON.stringify(toxicJob.result, null, 2) }}</pre></details>

        <section v-if="pushSync.available" class="sync-comparison-section">
          <div class="sync-section-head"><div><h3>同步订单逐笔对比</h3><small>同品种、同方向且开仓相差不超过2秒；平仓时间差单独判断</small></div><span>抽样 {{ pushSync.sampledOrders || 0 }} 单</span></div>
          <div class="sync-kpis"><div><span>任意开仓匹配</span><b>{{ percent(pushSync.matchedRatio) }}</b></div><div><span>反复账户协调开仓</span><b>{{ percent(pushSync.coordinatedMatchedRatio) }}</b></div><div><span>协调手数覆盖</span><b>{{ percent(pushSync.coordinatedVolumeRatio) }}</b></div><div><span>协调平仓</span><b>{{ percent(pushSync.coordinatedCloseRatio) }}</b></div><div><span>反复关联账户</span><b>{{ pushSync.recurringPeerAccounts || 0 }}</b></div><div><span>重复门槛</span><b>{{ pushSync.recurringMinMatches || 0 }} 单</b></div></div>

          <div class="table-wrap sync-peer-wrap"><table><thead><tr><th>关联账户</th><th>服务器</th><th>同步开仓</th><th>同步平仓</th><th>开仓覆盖</th><th>平仓覆盖</th></tr></thead><tbody><tr v-for="peer in pushSync.suspectedAccounts || []" :key="`${peer.server}-${peer.account}`"><td><RouterLink :to="`/account/${peer.account}?platform=${peer.platform}&server=${encodeURIComponent(peer.server)}`">{{ peer.account }}</RouterLink></td><td>{{ peer.server }}</td><td>{{ peer.matches }} 单</td><td>{{ peer.closeMatches }} 单</td><td>{{ percent(peer.matchRatio) }}</td><td>{{ percent(peer.closeMatchRatio) }}</td></tr></tbody></table></div>

          <div class="sync-detail-head"><div><h3>相似订单明细</h3><small>当前显示 {{ syncComparisonRows.length }} / {{ pushSync.comparisonTotal || 0 }} 组</small></div><label>关联账户<select v-model="syncPeerFilter"><option value="">全部账户</option><option v-for="peer in pushSync.suspectedAccounts || []" :key="peer.account" :value="String(peer.account)">{{ peer.account }} · {{ peer.matches }} 单</option></select></label></div>
          <div class="table-wrap sync-detail-wrap"><table class="sync-compare-table"><thead><tr><th>同步结论</th><th>主体订单</th><th>关联订单</th><th>品种 / 方向</th><th>手数对比</th><th>开仓时间对比</th><th>平仓时间对比</th></tr></thead><tbody><tr v-for="row in syncComparisonRows" :key="`${row.targetTicket}-${row.peerServer}-${row.peerAccount}-${row.peerTicket}`"><td><span class="sync-state" :class="row.closeSynchronized ? 'full' : 'open-only'">{{ row.closeSynchronized ? '开平仓同步' : '仅开仓同步' }}</span></td><td><b>{{ row.targetAccount }}</b><small>#{{ row.targetTicket }}</small></td><td><RouterLink :to="`/account/${row.peerAccount}?platform=${row.peerPlatform}&server=${encodeURIComponent(row.peerServer)}`">{{ row.peerAccount }}</RouterLink><small>#{{ row.peerTicket }} · {{ row.peerServer }}</small></td><td><b>{{ row.targetSymbol }}</b><small>{{ syncDirection(row.targetDirection) }}</small></td><td><b>{{ number(row.targetVolume, 2) }} / {{ number(row.peerVolume, 2) }}</b><small>主体 / 关联</small></td><td><b>{{ syncDelta(row.openDeltaSeconds) }}</b><small>{{ row.targetOpened }}</small><small>{{ row.peerOpened }}</small></td><td><b :class="row.closeSynchronized ? 'positive' : 'negative'">{{ syncDelta(row.closeDeltaSeconds) }}</b><small>{{ row.targetClosed || '-' }}</small><small>{{ row.peerClosed || '-' }}</small></td></tr><tr v-if="!syncComparisonRows.length"><td colspan="7" class="empty-cell">该关联账户暂无可展示的订单对</td></tr></tbody></table></div>
          <p v-if="pushSync.comparisonTruncated" class="tool-note">对照记录较多，后端仅保留前 {{ pushSync.comparisonLimit }} 组；可按关联账户筛选查看。</p>
        </section>
      </div>
    </section>

    <section class="panel same-name-panel"><div class="section-head"><div><h2>同名账户</h2><small>{{ sameName.length }} 个关联账号 · 仅展示账号和交易数据</small></div></div><PanelState :loading="risk.isLoading.value" :error="risk.error.value as Error" :empty="!sameName.length"><div class="table-wrap"><table><thead><tr><th>服务器</th><th>账号</th><th>数据库状态</th><th>本地标记</th><th>账户余额</th><th>净值</th><th>净入金</th><th>持仓盈亏</th><th>平仓净盈亏</th><th>清零+补偿+奖励</th><th>返佣</th><th>综合盈利</th><th>最高持仓量</th></tr></thead><tbody><tr v-for="row in sameName" :key="`${row.platform}-${row.server}-${row.account}`"><td>{{ row.platform }} · {{ row.server }}</td><td><RouterLink :to="`/account/${row.account}?platform=${row.platform}&server=${encodeURIComponent(row.server)}`">{{ row.account }}</RouterLink> · {{ row.currency }}</td><td>{{ row.databaseStatus || '-' }}</td><td>{{ row.localStatus || '-' }}</td><td>{{ money(row.balance) }}</td><td>{{ money(row.equity) }}</td><td :class="valueClass(row.netDeposit)">{{ money(row.netDeposit) }}</td><td :class="valueClass(row.holdingProfit)">{{ money(row.holdingProfit) }}</td><td :class="valueClass(row.closedNetProfit)">{{ money(row.closedNetProfit) }}</td><td>{{ money(row.adjustments) }}</td><td>{{ money(row.rebate) }}</td><td :class="valueClass(row.comprehensiveProfit)">{{ money(row.comprehensiveProfit) }}</td><td>{{ number(row.highestHoldingVolume,2) }}</td></tr><tr class="total-row"><td></td><td>合计</td><td>-</td><td>-</td><td>{{ money(sameNameTotals.balance) }}</td><td>{{ money(sameNameTotals.equity) }}</td><td>{{ money(sameNameTotals.netDeposit) }}</td><td>{{ money(sameNameTotals.holdingProfit) }}</td><td>{{ money(sameNameTotals.closedNetProfit) }}</td><td>{{ money(sameNameTotals.adjustments) }}</td><td>{{ money(sameNameTotals.rebate) }}</td><td>{{ money(sameNameTotals.comprehensiveProfit) }}</td><td>-</td></tr></tbody></table></div></PanelState></section>

    <section class="panel"><div class="section-head"><div><h2>盈亏趋势</h2><small>{{ metrics.orderCount || 0 }} 笔订单 · {{ database.accountMeta?.displayCurrency || database.accountMeta?.currency || '' }}</small></div><div class="section-kpis"><span>净盈亏 <b :class="valueClass(metrics.netProfit)">{{ signedMoney(metrics.netProfit) }}</b></span><span>最大回撤 <b class="negative">{{ signedMoney(-Math.abs(Number(visuals.maxDrawdown || 0))) }}</b></span></div></div><PanelState :loading="detail.isLoading.value" :error="detail.error.value as Error" :empty="!visuals.pnlSeries?.length"><div class="trend-grid"><div><div class="chart-title">累计净盈亏</div><PnlLineChart :data="visuals.pnlSeries" /></div><div><div class="chart-title">每日净盈亏 <small>最近 30 个交易日</small></div><DailyBarChart :data="visuals.dailyPnl" /></div></div></PanelState></section>

    <section class="panel"><div class="section-head"><div><h2>高频与持仓分析</h2><small>{{ highFrequency.orderCount ?? '-' }} 笔平仓订单</small></div></div><PanelState :loading="risk.isLoading.value" :error="risk.error.value as Error"><div class="metric-grid four"><div><span>平均持仓时间</span><b>{{ highFrequency.averageHoldingMinutes == null ? '-' : `${number(highFrequency.averageHoldingMinutes,1)} 分钟` }}</b></div><div><span>盈利单平均持仓</span><b>{{ highFrequency.winningAverageHoldingMinutes == null ? '-' : `${number(highFrequency.winningAverageHoldingMinutes,1)} 分钟` }}</b></div><div><span>亏损单平均持仓</span><b>{{ highFrequency.losingAverageHoldingMinutes == null ? '-' : `${number(highFrequency.losingAverageHoldingMinutes,1)} 分钟` }}</b></div><div><span>高频订单占比</span><b>{{ percent(highFrequency.highFrequencyOrderRatio) }}</b></div></div><div class="bucket-strip"><article v-for="row in highFrequency.buckets || []" :key="row.label"><b>{{ row.label }}</b><span>{{ row.orders }} 单 · {{ percent(row.winRate) }}</span><strong :class="valueClass(row.grossProfit)">{{ signedMoney(row.grossProfit) }}</strong></article></div><div class="table-wrap"><table><thead><tr><th>持仓时段</th><th>订单数量</th><th>胜率</th><th>总盈利</th><th>总手数</th><th>平均每手盈利</th><th>平均每单盈利</th><th>盈利占比</th><th>平均交易手数</th></tr></thead><tbody><tr v-for="row in highFrequency.buckets || []" :key="row.label"><td>{{ row.label }}</td><td>{{ row.orders }}</td><td>{{ percent(row.winRate) }}</td><td :class="valueClass(row.grossProfit)">{{ money(row.grossProfit) }}</td><td>{{ number(row.volume,2) }}</td><td>{{ money(row.averageProfitPerLot) }}</td><td>{{ money(row.averageProfitPerOrder) }}</td><td>{{ percent(row.profitShare) }}</td><td>{{ number(row.averageVolume,2) }}</td></tr></tbody></table></div></PanelState></section>

    <section class="panel"><div class="section-head"><div><h2>跟单 / EA 分析</h2><small>{{ automation.data.value?.totalOrders || 0 }} 笔订单 · {{ number(automation.data.value?.totalVolume,2) }} 手 · {{ automation.data.value?.refreshedAt || '' }}</small></div><button @click="requestCopyGroups">查询信号组利润</button></div><PanelState :loading="automation.isLoading.value" :error="automation.error.value as Error"><div class="automation-grid"><div class="subpanel"><div class="subpanel-title"><h3>跟单分析</h3><span>来源账号 · 占比 · 盈亏</span></div><div class="metric-grid compact"><div><span>订单</span><b>{{ automationCopy.orders || 0 }}</b></div><div><span>订单占全部</span><b>{{ percent(automationCopy.orderRatio) }}</b></div><div><span>手数占全部</span><b>{{ percent(automationCopy.volumeRatio) }}</b></div><div><span>毛盈亏</span><b :class="valueClass(automationCopy.grossProfit)">{{ money(automationCopy.grossProfit) }}</b></div><div><span>净盈亏</span><b :class="valueClass(automationCopy.netProfit)">{{ money(automationCopy.netProfit) }}</b></div><div><span>手数</span><b>{{ number(automationCopy.volume,2) }}</b></div></div><div class="table-wrap"><table><thead><tr><th>来源账号</th><th>订单</th><th>订单占全部</th><th>手数</th><th>手数占全部</th><th>毛盈亏</th><th>净盈亏</th></tr></thead><tbody><tr v-for="row in automationCopy.origins || []" :key="row.account || row.origin"><td>{{ row.account || row.origin }}</td><td>{{ row.orders }}</td><td>{{ percent(row.orderRatio) }}</td><td>{{ number(row.volume,2) }}</td><td>{{ percent(row.volumeRatio) }}</td><td>{{ money(row.grossProfit) }}</td><td>{{ money(row.netProfit) }}</td></tr><tr v-if="!automationCopy.origins?.length"><td colspan="7" class="empty-cell">未识别到跟单订单</td></tr></tbody></table></div></div><div class="subpanel"><div class="subpanel-title"><h3>EA 分析</h3><span>ExpertID / Magic · 占比 · 盈亏</span></div><div class="metric-grid compact"><div><span>订单</span><b>{{ automationEa.orders || 0 }}</b></div><div><span>订单占全部</span><b>{{ percent(automationEa.orderRatio) }}</b></div><div><span>手数占全部</span><b>{{ percent(automationEa.volumeRatio) }}</b></div><div><span>毛盈亏</span><b :class="valueClass(automationEa.grossProfit)">{{ money(automationEa.grossProfit) }}</b></div><div><span>净盈亏</span><b :class="valueClass(automationEa.netProfit)">{{ money(automationEa.netProfit) }}</b></div><div><span>手数</span><b>{{ number(automationEa.volume,2) }}</b></div></div><div class="table-wrap"><table><thead><tr><th>ExpertID / Magic</th><th>平台 / 服务器</th><th>订单</th><th>订单占全部</th><th>手数</th><th>手数占全部</th><th>毛盈亏</th><th>净盈亏</th></tr></thead><tbody><tr v-for="row in automationEa.groups || []" :key="`${row.expertId}-${row.platform}-${row.server}`"><td><b>{{ row.expertId }}</b><small class="cell-sub">{{ row.symbols?.join('、') }}</small></td><td>{{ row.platform }} / {{ row.server }}</td><td>{{ row.orders }}</td><td>{{ percent(row.orderRatio) }}</td><td>{{ number(row.volume,2) }}</td><td>{{ percent(row.volumeRatio) }}</td><td :class="valueClass(row.grossProfit)">{{ money(row.grossProfit) }}</td><td :class="valueClass(row.netProfit)">{{ money(row.netProfit) }}</td></tr></tbody></table></div></div></div><div v-if="copyGroupRequested" class="copy-group-result"><PanelState :loading="copyGroups.isLoading.value" :error="copyGroups.error.value as Error" :empty="!copyGroups.data.value?.groups?.length" empty-text="未识别到可聚合的信号组"><div class="table-wrap"><table><thead><tr><th>来源平台</th><th>发起账号</th><th>命中源订单</th><th>跟单订单</th><th>占全部订单</th><th>占跟单订单</th><th>跟单手数</th><th>毛盈亏</th><th>净盈亏</th></tr></thead><tbody><tr v-for="(row,index) in copyGroups.data.value?.groups || []" :key="index"><td>{{ row.platform || '-' }}</td><td>{{ row.originAccount || row.account || '-' }}</td><td>{{ row.sourceOrders || '-' }}</td><td>{{ row.copyOrders || row.orders || '-' }}</td><td>{{ percent(row.orderRatio) }}</td><td>{{ percent(row.copyOrderRatio) }}</td><td>{{ number(row.volume,2) }}</td><td>{{ money(row.grossProfit) }}</td><td>{{ money(row.netProfit) }}</td></tr></tbody></table></div></PanelState></div></PanelState></section>

    <section class="panel metrics-panel"><div class="section-head"><div><h2>交易指标</h2><small>{{ metrics.orderCount || 0 }} 笔订单 · {{ metrics.symbolCount || 0 }} 个品种 · {{ metrics.activeDays || 0 }} 个活跃日</small></div><button @click="toggleOrders">{{ showOrders ? '收起订单' : '查看订单明细' }}</button></div><PanelState :loading="detail.isLoading.value" :error="detail.error.value as Error"><div class="metric-sections"><div><h3>交易概览</h3><div class="metric-grid four"><div><span>订单数量</span><b>{{ metrics.orderCount }}</b></div><div><span>总手数</span><b>{{ number(metrics.totalVolume,2) }}</b></div><div><span>平均手数</span><b>{{ number(metrics.averageVolume,2) }}</b></div><div><span>最大手数</span><b>{{ number(metrics.maxVolume,2) }}</b></div><div><span>净胜率</span><b>{{ percent(metrics.winRate) }}</b></div><div><span>平均每单</span><b>{{ money(metrics.averageProfit) }}</b></div><div><span>活跃日均订单</span><b>{{ number(metrics.ordersPerActiveDay,1) }}</b></div><div><span>一分钟最多订单</span><b>{{ metrics.maxOrdersInOneMinute ?? '-' }}</b></div></div></div><div><h3>盈亏与持仓</h3><div class="metric-grid four"><div><span>净盈亏</span><b :class="valueClass(metrics.netProfit)">{{ money(metrics.netProfit) }}</b></div><div><span>毛盈亏</span><b :class="valueClass(metrics.grossProfit)">{{ money(metrics.grossProfit) }}</b></div><div><span>盈利 / 亏损单</span><b>{{ metrics.winningOrders }} / {{ metrics.losingOrders }}</b></div><div><span>平均持仓</span><b>{{ duration(metrics.averageHoldingSeconds) }}</b></div><div><span>中位持仓</span><b>{{ duration(metrics.medianHoldingSeconds) }}</b></div><div><span>1分钟内</span><b>{{ percent(metrics.oneMinuteHoldingRatio) }}</b></div><div><span>短线占比</span><b>{{ percent(metrics.shortHoldingRatio) }}</b></div><div><span>平均订单间隔</span><b>{{ duration(metrics.averageOrderGapSeconds) }}</b></div></div></div><div><h3>佣金 / 费用结构</h3><div class="metric-grid four"><div><span>手续费</span><b :class="valueClass(metrics.commissionTotal)">{{ money(metrics.commissionTotal) }}</b></div><div><span>利息 Swap</span><b :class="valueClass(metrics.swapTotal)">{{ money(metrics.swapTotal) }}</b></div><div><span>税费</span><b>{{ money(metrics.taxesTotal) }}</b></div><div><span>总费用</span><b :class="valueClass(metrics.feesTotal)">{{ money(metrics.feesTotal) }}</b></div></div></div></div></PanelState></section>

    <section v-if="showOrders" class="panel orders-panel"><div class="section-head"><div><h2>订单明细</h2><small>第 {{ orders.data.value?.page || orderPage }} / {{ orders.data.value?.pages || '-' }} 页 · 共 {{ orders.data.value?.total || 0 }} 笔</small></div><div class="pager"><button :disabled="orderPage<=1" @click="orderPage--">上一页</button><button :disabled="orderPage>=(orders.data.value?.pages || 1)" @click="orderPage++">下一页</button></div></div><PanelState :loading="orders.isLoading.value" :error="orders.error.value as Error" :empty="!orders.data.value?.orders?.length"><div class="table-wrap order-table"><table><thead><tr><th>订单号</th><th>平台 / 服务器</th><th>品种</th><th>方向</th><th>原因</th><th>注释 / EA</th><th>开仓时间</th><th>平仓时间</th><th>持仓时间</th><th>手数</th><th>毛盈亏</th><th>手续费</th><th>利息</th><th>税费</th><th>净盈亏</th><th>币种</th></tr></thead><tbody><tr v-for="row in orders.data.value?.orders || []" :key="`${row.platform}-${row.server}-${row.ticket}`"><td>{{ row.ticket }}</td><td>{{ row.platform }} / {{ row.server }}</td><td>{{ row.symbol }}</td><td>{{ row.type }}</td><td>{{ row.reason || '-' }}</td><td>{{ row.comment || '-' }}<small v-if="row.expertId" class="cell-sub">EA {{ row.expertId }}</small></td><td>{{ row.openTime }}</td><td>{{ row.closeTime }}</td><td>{{ duration(row.holdingSeconds) }}</td><td>{{ number(row.volume,2) }}</td><td :class="valueClass(row.profit)">{{ money(row.profit) }}</td><td>{{ money(row.commission) }}</td><td>{{ money(row.swap) }}</td><td>{{ money(row.taxes) }}</td><td :class="valueClass(row.netProfit)">{{ money(row.netProfit) }}</td><td>{{ row.displayCurrency || row.currency }}</td></tr></tbody></table></div></PanelState></section>

    <div class="two-col finance-symbol-grid"><section class="panel"><div class="section-head"><div><h2>账户资金情况</h2><small>{{ finance.displayCurrency || finance.currency || '' }}</small></div></div><PanelState :loading="risk.isLoading.value" :error="risk.error.value as Error"><div class="finance-list"><div><span>账户余额 / 净值</span><b>{{ money(finance.balance) }} / {{ money(finance.equity) }}</b></div><div><span>净入金（入金 - 出金）</span><b>{{ money(finance.netDeposit) }}</b></div><div><span>入金 / 出金</span><b>{{ money(finance.depositTotal) }} / {{ money(finance.withdrawalTotal) }}</b></div><div><span>持仓盈亏</span><b :class="valueClass(finance.holdingProfit)">{{ money(finance.holdingProfit) }}</b></div><div><span>平仓净盈亏</span><b :class="valueClass(finance.closedNetProfit)">{{ money(finance.closedNetProfit) }}</b></div><div><span>手续费 / 利息</span><b>{{ money(finance.tradingFees) }} / {{ money(finance.interest) }}</b></div><div><span>清零 / 补偿 / 奖励</span><b>{{ money(finance.negativeBalanceClear) }} / {{ money(finance.compensation) }} / {{ money(finance.reward) }}</b></div><div><span>返佣</span><b>{{ money(finance.rebate) }}</b></div><div class="finance-total"><span>综合盈利</span><b :class="valueClass(finance.comprehensiveProfit)">{{ money(finance.comprehensiveProfit) }}</b></div><div><span>最高持仓量 / 当前持仓</span><b>{{ number(finance.highestHoldingVolume,2) }} / {{ finance.currentPositionCount ?? '-' }}</b></div></div></PanelState></section><section class="panel"><div class="section-head"><div><h2>胜负与费用结构</h2><small>订单结果与交易成本</small></div></div><div class="structure-bars"><div><span>盈利单 {{ visuals.outcomes?.winning || 0 }}</span><i><b class="positive-bar" :style="{width:`${metrics.orderCount ? visuals.outcomes?.winning/metrics.orderCount*100 : 0}%`}" /></i></div><div><span>亏损单 {{ visuals.outcomes?.losing || 0 }}</span><i><b class="negative-bar" :style="{width:`${metrics.orderCount ? visuals.outcomes?.losing/metrics.orderCount*100 : 0}%`}" /></i></div><div v-for="row in visuals.feeBreakdown || []" :key="row.label"><span>{{ row.label }} {{ money(row.value) }}</span><i><b class="fee-bar" :style="{width:`${Math.min(100,Math.abs(Number(row.value))/(Math.max(...(visuals.feeBreakdown || []).map((x:any)=>Math.abs(Number(x.value))),1))*100)}%`}" /></i></div></div><div class="fee-note">费用占净盈利 {{ percent(metrics.feeToProfitRatio) }} · {{ metrics.costsComplete ? '费用数据完整' : '费用数据可能不完整' }}</div></section></div>

    <section class="panel"><div class="section-head"><div><h2>品种表现</h2><small>{{ visuals.symbolPerformance?.length || 0 }} 个品种</small></div></div><div class="symbol-cards"><button v-for="row in visuals.symbolPerformance || []" :key="row.symbol" :class="{active:filters.symbol===row.symbol}" @click="filters.symbol=row.symbol;applyFilters()"><b>{{ row.symbol }}</b><strong :class="valueClass(row.profit)">{{ signedMoney(row.profit) }}</strong><span>{{ row.orders }} 单 · {{ number(row.volume,2) }} 手</span><small>{{ row.firstTime }} 至 {{ row.lastTime }}</small></button></div><div class="table-wrap"><table><thead><tr><th>品种</th><th>订单</th><th>手数</th><th>净盈亏</th><th>净胜率</th><th>首笔交易</th><th>最近交易</th></tr></thead><tbody><tr v-for="row in visuals.symbolPerformance || []" :key="row.symbol"><td><b>{{ row.symbol }}</b></td><td>{{ row.orders }}</td><td>{{ number(row.volume,2) }}</td><td :class="valueClass(row.profit)">{{ money(row.profit) }}</td><td>{{ percent(row.winRate) }}</td><td>{{ row.firstTime }}</td><td>{{ row.lastTime }}</td></tr></tbody></table></div></section>

    <section class="panel"><div class="section-head"><div><h2>登录 IP 来源</h2><small>{{ ips.data.value?.records?.length || 0 }} 个历史 IP</small></div><button @click="queryClient.invalidateQueries({queryKey:['ips',login]})">刷新 IP</button></div><PanelState :loading="ips.isLoading.value" :error="ips.error.value as Error" :empty="!ips.data.value?.records?.length"><div class="ip-list"><article v-for="row in ips.data.value?.records || []" :key="`${row.platform}-${row.server}-${row.ip}`"><div><strong>{{ row.ip }}</strong><span class="badge">{{ row.platform }} / {{ row.server }}</span></div><span>{{ row.geo?.country || '-' }} · {{ row.geo?.region || '-' }} · {{ row.geo?.city || '-' }}</span><span>{{ row.geo?.isp || '-' }}</span><small>首次 {{ row.firstSeenAt || '-' }} · 最后 {{ row.lastSeenAt || '-' }}</small></article></div></PanelState></section>

    <section class="panel"><div class="section-head"><div><h2>交易图表</h2><small>数据库生成 · 持久化任务</small></div><a href="http://127.0.0.1:8766/" target="_blank">打开 K 线任务中心</a></div><div class="kline-controls"><label>开始时间<input v-model="klineForm.start" type="datetime-local"></label><label>结束时间<input v-model="klineForm.end" type="datetime-local"></label><label><input v-model="klineForm.includeTimeline" type="checkbox" @change="!klineForm.includeTimeline && (klineForm.refreshTimelineCache = false)"> 包含资金与 Credit 回放</label><label v-if="klineForm.includeTimeline"><input v-model="klineForm.refreshTimelineCache" type="checkbox"> 刷新全量资金缓存</label><small>时间留空默认全量历史；回放首次读取后使用本地缓存。</small><button class="primary" :disabled="klineJob && ['queued','running'].includes(klineJob.status)" @click="startKline">生成 K 线图</button><button v-if="klineJob && ['queued','running'].includes(klineJob.status)" @click="cancelJob(klineJob)">取消</button></div><div v-if="klineJob" class="job-card compact-job"><div class="job-head"><b>{{ jobMessage(klineJob) }}</b><span>{{ klineJob.progress || 0 }}%</span></div><div class="progress"><i :style="{width:`${klineJob.progress || 0}%`}" /></div><div v-if="klineJob.error" class="inline-error">{{ klineJob.error }}</div><div v-if="klineJob.result?.partial" class="inline-warning">部分成功：{{ klineJob.result.symbols?.length || 0 }} 个品种已生成，{{ klineJob.result.failures?.length || 0 }} 个品种失败</div><div v-if="klineJob.result?.failures?.length" class="kline-failures"><div v-for="failure in klineJob.result.failures" :key="`${failure.symbol}-${failure.code}`"><b>{{ failure.symbol }}</b><span>{{ failure.stage }} / {{ failure.code }}</span><small>{{ failure.reason }}</small></div></div></div><div class="chart-list"><article v-for="chart in detail.data.value?.charts || []" :key="chart.name"><div><b>{{ chart.name }}</b><span>{{ chart.start || '-' }} 至 {{ chart.end || '-' }} · {{ chart.sizeText }}</span></div><div><a :href="chart.url" target="_blank">预览</a><a :href="chart.url" target="_blank">打开</a></div></article><span v-if="!detail.data.value?.charts?.length">当前开发产物目录暂无图表。</span></div></section>

    <section class="panel history-panel"><div class="section-head"><div><h2>数据来源与历史记录</h2><small>审计与可追溯性</small></div></div><div class="two-col"><div class="subpanel"><h3>数据来源</h3><div class="source-list"><span v-for="row in metrics.bySource || []" :key="`${row.platform}-${row.server}`"><b>{{ row.platform }} / {{ row.server }}</b>{{ row.orders }} 单 · {{ row.currency }} · {{ money(row.profit) }}</span></div></div><div class="subpanel"><h3>台账历史</h3><div class="source-list"><span v-for="row in detail.data.value?.history || []" :key="row['历史ID'] || row.id"><b>{{ row['操作'] || row.operation }}</b>{{ row['修改时间'] || row.createdAt }} · {{ row['处理人/来源'] || row.owner || '-' }}</span><span v-if="!detail.data.value?.history?.length">暂无修改历史</span></div></div></div></section>
  </main>
</template>
