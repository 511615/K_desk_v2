<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, ApiError, queryString } from '../api'
import PanelState from '../components/PanelState.vue'
import BonusArbitrageDiscoveryPanel from '../components/BonusArbitrageDiscoveryPanel.vue'
import PositionRiskDiscoveryPanel from '../components/PositionRiskDiscoveryPanel.vue'
import RebateAuditPanel from '../components/RebateAuditPanel.vue'
import RebateDiscoveryPanel from '../components/RebateDiscoveryPanel.vue'
import { startFrontendUpdateMonitor } from '../frontendUpdate'
import { loadPushJobId, pushPollRetryDelay, recoverPushPollingState, savePushJobId } from '../pushDiscovery'

const queryClient = useQueryClient()
const accountInput = ref('')
const listSearch = ref('')
const actionFilter = ref('')
const statusFilter = ref('')
const lookupBusy = ref(false)
const lookupError = ref('')
const lookupMatches = ref<any[]>([])
const lookupSelectionOpen = ref(false)
const statusSaving = ref('')
const tools = reactive({ logs: true, hierarchy: true })
const logsForm = reactive({ account: '', start: localDate(-1), end: localDate(0) })
const logsResult = ref<any>(null)
const logsBusy = ref(false)
const logsError = ref('')
const pushForm = reactive({
  days: 3,
  deepLimit: 50,
  requirePeriodProfit: true,
  limitOrders: true,
  maxOrders: 100,
  requireMaxLot: true,
  minMaxLot: 0.01,
  requireTotalProfit: true,
  limitDeposit: true,
  maxDeposit: 2000,
  limitActiveRatio: true,
  maxActiveRatio: 30,
  excludeHandled: true,
})
const pushJob = ref<any>(null)
const discoveryTab = ref<'push' | 'rebate' | 'bonus' | 'position'>('push')
let pushTimer = 0
let pushPollFailures = 0
let stopFrontendUpdateMonitor: () => void = () => undefined
const hierarchyForm = reactive({ target: '', start: localDate(-7), end: localDate(0), product: '', activityRules: false })
const hierarchyResult = ref<any>(null)
const hierarchyBusy = ref(false)
const hierarchyError = ref('')

function localDate(offsetDays: number): string {
  const date = new Date(Date.now() + offsetDays * 86400000)
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

const query = useQuery({ queryKey: ['accounts'], queryFn: () => api<any>('/api/accounts') })
const products = useQuery({ queryKey: ['hierarchy-products'], queryFn: () => api<any>('/api/hierarchy-products') })
const allRecords = computed<any[]>(() => query.data.value?.records || [])
const actions = computed(() => Array.from(new Set(allRecords.value.map(row => row['建议动作']).filter(Boolean))))
const statuses = computed(() => Array.from(new Set(allRecords.value.map(row => row['状态']).filter(Boolean))))
const records = computed(() => {
  const needle = listSearch.value.trim().toLowerCase()
  return allRecords.value.filter(row => {
    if (actionFilter.value && row['建议动作'] !== actionFilter.value) return false
    if (statusFilter.value && row['状态'] !== statusFilter.value) return false
    return !needle || JSON.stringify(row).toLowerCase().includes(needle)
  })
})
const todayCount = computed(() => allRecords.value.filter(row => String(row['修改时间'] || '').slice(0, 10) === new Date().toISOString().slice(0, 10)).length)
const activePushFilterCount = computed(() => [
  pushForm.requirePeriodProfit,
  pushForm.limitOrders,
  pushForm.requireMaxLot,
  pushForm.requireTotalProfit,
  pushForm.limitDeposit,
  pushForm.limitActiveRatio,
  pushForm.excludeHandled,
].filter(Boolean).length)

async function openAccount(login = accountInput.value.trim()) {
  if (!login) return
  lookupBusy.value = true
  lookupError.value = ''
  try {
    const result = await api<any>(`/api/account-lookup?account=${encodeURIComponent(login)}`)
    const matches = Array.isArray(result.databases) ? result.databases : []
    if (result.database?.queryFailed) throw new Error(result.database.error || '账号查询失败，请稍后重试')
    if (!matches.length && !result.database?.exists) throw new Error('未在交易库或本地台账中找到该账号')
    if (matches.length > 1) {
      lookupMatches.value = matches
      lookupSelectionOpen.value = true
      return
    }
    const source = (matches[0] || result.database).latestSource || {}
    window.location.assign(accountHref(login, source.platform, source.server))
  } catch (error: any) {
    lookupError.value = error.message || '账号查询失败'
  } finally {
    lookupBusy.value = false
  }
}

function chooseAccountSource(match: any) {
  const source = match?.latestSource || {}
  lookupSelectionOpen.value = false
  window.location.assign(accountHref(accountInput.value.trim(), source.platform, source.server))
}

async function updateStatus(row: any, status: string) {
  statusSaving.value = row['记录ID']
  try {
    await api(`/api/accounts/${encodeURIComponent(row['记录ID'])}`, { method: 'PUT', body: JSON.stringify({ ...row, '状态': status }) })
    await queryClient.invalidateQueries({ queryKey: ['accounts'] })
  } finally {
    statusSaving.value = ''
  }
}

async function queryLogs() {
  if (!logsForm.account.trim()) return
  logsBusy.value = true
  logsError.value = ''
  try {
    logsResult.value = await api<any>(`/api/account-logs${queryString(logsForm)}`)
  } catch (error: any) {
    logsError.value = error.message || '日志查询失败'
  } finally {
    logsBusy.value = false
  }
}

async function queryHierarchy() {
  if (!hierarchyForm.target.trim()) return
  hierarchyBusy.value = true
  hierarchyError.value = ''
  try {
    const params = new URLSearchParams({ target: hierarchyForm.target, start: hierarchyForm.start, end: hierarchyForm.end, product: hierarchyForm.product, activityRules: String(hierarchyForm.activityRules) })
    hierarchyResult.value = await api<any>(`/api/hierarchy-net-deposit?${params}`)
  } catch (error: any) {
    hierarchyError.value = error.message || '层级统计失败'
  } finally {
    hierarchyBusy.value = false
  }
}

function detailsPreview(details: any): string {
  if (!details || typeof details !== 'object') return '-'
  const preferred = ['Symbol', 'Action', 'Entry', 'Volume', 'Price', 'Profit', 'Commission', 'Comment']
  return preferred.filter(key => details[key] !== undefined && details[key] !== '').map(key => `${key}: ${details[key]}`).join(' · ') || JSON.stringify(details).slice(0, 220)
}

function pushNumber(value: unknown, digits = 2): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '-'
}

function accountHref(account: unknown, platform = '', server = ''): string {
  const query = new URLSearchParams()
  if (platform) query.set('platform', platform)
  if (server) query.set('server', server)
  const suffix = query.toString()
  return `/account/${encodeURIComponent(String(account || ''))}${suffix ? `?${suffix}` : ''}`
}

function pushAccountHref(row: any): string {
  return accountHref(row.account, row.platform, row.server)
}

function suspectedIntervalBasis(row: any): string {
  return ({
    confirmed_coordination: '确认协同轮次',
    coordinated_candidate: '协同候选轮次',
    dynamic_concentration: '动态集中时段',
  } as Record<string, string>)[row.suspectedIntervalBasis] || '未形成区间'
}

function suspectedIntervalTitle(row: any): string {
  if (!Number(row.suspectedIntervalCount)) return '当前模型没有形成可单列的疑似推盘区间'
  return [
    suspectedIntervalBasis(row),
    `毛收益 ${pushNumber(row.suspectedIntervalGrossProfit)} ${row.currency || ''}`,
    `费用调整 ${pushNumber(row.suspectedIntervalCosts)} ${row.currency || ''}`,
    `净收益 ${pushNumber(row.suspectedIntervalNetProfit)} ${row.currency || ''}`,
    row.suspectedIntervalReturnPct == null ? '入金回报率不可用' : `约占累计入金 ${pushNumber(row.suspectedIntervalReturnPct, 1)}%`,
    `覆盖 ${row.suspectedIntervalOrders || 0} 单（${pushNumber(row.suspectedIntervalOrderRatio, 1)}%）`,
  ].join(' · ')
}

function pushProfitClass(value: unknown): string {
  return Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : ''
}

function pushFailureSummary(): string {
  const summary = pushJob.value?.result?.failureSummary || {}
  return Object.entries(summary).map(([stage, count]) => `${stage} ${count}项`).join(' · ')
}

function pushJobMessage(): string {
  const job = pushJob.value
  if (!job) return '尚未运行'
  if (job.connectionError) return job.connectionError
  if (job.events?.length) return job.events[job.events.length - 1].message
  return job.error || ({ queued: '已提交，等待扫描', running: '正在扫描', done: '扫描完成', failed: '扫描失败', cancelled: '已取消' } as any)[job.status] || ''
}

async function resumeNextActivePushJob(completedId: string) {
  try {
    const active = await api<any>('/api/push-discovery/active')
    if (!active.job?.id || active.job.id === completedId) return
    pushJob.value = active.job
    savePushJobId(window.localStorage, active.job.id)
    void pollPushDiscovery(active.job.id)
  } catch {
    // Keep the completed result visible when no next task can be loaded.
  }
}

async function pollPushDiscovery(id: string) {
  try {
    pushJob.value = await api<any>(`/api/push-discovery/jobs/${encodeURIComponent(id)}`)
    pushPollFailures = 0
    if (!['done', 'failed', 'cancelled'].includes(pushJob.value.status)) {
      pushTimer = window.setTimeout(() => pollPushDiscovery(id), 1200)
    } else {
      await resumeNextActivePushJob(id)
    }
  } catch (error: any) {
    if (error instanceof ApiError && error.status === 404) {
      pushJob.value = { status: 'failed', error: '之前的扫描任务记录已不存在' }
      return
    }
    pushPollFailures += 1
    pushJob.value = recoverPushPollingState(pushJob.value, error, pushPollFailures)
    pushTimer = window.setTimeout(() => pollPushDiscovery(id), pushPollRetryDelay(pushPollFailures))
  }
}

async function startPushDiscovery() {
  pushPollFailures = 0
  pushJob.value = { status: 'queued', progress: 0 }
  try {
    const result = await api<any>('/api/push-discovery/start', { method: 'POST', body: JSON.stringify(pushForm) })
    pushJob.value = result.job
    savePushJobId(window.localStorage, result.job.id)
    await pollPushDiscovery(result.job.id)
  } catch (error: any) {
    pushJob.value = { status: 'failed', error: error.message || '提交扫描失败' }
  }
}

async function cancelPushDiscovery() {
  if (!pushJob.value?.id) return
  try {
    const cancelled = await api<any>(`/api/jobs/${encodeURIComponent(pushJob.value.id)}/cancel`, { method: 'POST' })
    pushJob.value = { ...pushJob.value, ...cancelled, connectionError: '', connectionDetail: '' }
  } catch (error: any) {
    pushPollFailures += 1
    pushJob.value = recoverPushPollingState(pushJob.value, error, pushPollFailures)
  }
}

onMounted(async () => {
  stopFrontendUpdateMonitor = startFrontendUpdateMonitor(() => window.location.reload())
  const storedJobId = loadPushJobId(window.localStorage)
  if (storedJobId) {
    pushJob.value = { id: storedJobId, status: 'queued', progress: 0 }
    void pollPushDiscovery(storedJobId)
    return
  }
  try {
    const active = await api<any>('/api/push-discovery/active')
    if (!active.job?.id) return
    pushJob.value = active.job
    savePushJobId(window.localStorage, active.job.id)
    void pollPushDiscovery(active.job.id)
  } catch {
    // Passive task recovery must not block the rest of the workbench.
  }
})
onBeforeUnmount(() => {
  if (pushTimer) window.clearTimeout(pushTimer)
  stopFrontendUpdateMonitor()
})
</script>

<template>
  <header class="topbar legacy-topbar">
    <div><b>账号风控台账</b><span>统一主帐台 · 8777</span></div>
    <nav><a href="/copy-pool">动态跟单</a><a href="#rebateAuditPanel">IB刷返佣</a><a href="/download/problematic_accounts.xlsx">导出台账</a><a href="/?legacy=1">旧版工作台</a></nav>
  </header>
  <main class="workbench dense-page">
    <section class="hero compact-hero">
      <div><div class="eyebrow">ACCOUNT RISK WORKBENCH</div><h1>账号查询</h1><p>数据库订单与本地台账记录 · 生产服务</p></div>
      <div class="lookup-block">
        <div class="lookup"><input v-model="accountInput" aria-label="账号查询" placeholder="输入交易账号" @keyup.enter="openAccount()"><button :disabled="lookupBusy" @click="openAccount()">{{ lookupBusy ? '查询中…' : '查询' }}</button></div>
        <small v-if="lookupError" class="inline-error">{{ lookupError }}</small>
      </div>
    </section>

    <div v-if="lookupSelectionOpen" class="lookup-modal" role="dialog" aria-modal="true" aria-labelledby="lookup-modal-title">
      <button class="lookup-modal-backdrop" type="button" aria-label="关闭账号来源选择" @click="lookupSelectionOpen=false"></button>
      <section class="lookup-modal-card">
        <div class="section-head"><div><h2 id="lookup-modal-title">选择平台 / 服务器</h2><small>账号 {{ accountInput }} 在多个交易来源存在，请选择要查看的详细数据</small></div><button class="text-button" type="button" @click="lookupSelectionOpen=false">关闭</button></div>
        <div class="lookup-source-list">
          <button v-for="match in lookupMatches" :key="`${match.latestSource?.platform}-${match.latestSource?.server}`" type="button" class="lookup-source-option" @click="chooseAccountSource(match)">
            <span><b>{{ match.latestSource?.platform || '-' }} / {{ match.latestSource?.server || '-' }}</b><small>{{ match.exists ? `${match.orderCount || 0} 笔订单` : '账户暂未做单' }}</small></span><strong>查看详情 →</strong>
          </button>
        </div>
      </section>
    </div>

    <RebateAuditPanel :initial-account="accountInput" />

    <section class="summary-grid four-summary">
      <article><span>台账记录</span><strong>{{ query.data.value?.summary?.total ?? '-' }}</strong></article>
      <article><span>当前筛选</span><strong>{{ records.length }}</strong></article>
      <article><span>今日更新</span><strong>{{ todayCount }}</strong></article>
      <article><span>服务状态</span><strong class="positive">PROD READY</strong></article>
    </section>

    <section class="panel tool-panel">
      <div class="section-head"><div><h2>账号日志查询</h2><small>只读 · MySQL 交易库</small></div><button class="text-button" @click="tools.logs=!tools.logs">{{ tools.logs ? '收起' : '展开' }}</button></div>
      <div v-if="tools.logs">
        <div class="filter-row tool-form"><label>账号<input v-model="logsForm.account" placeholder="输入交易账号"></label><label>开始时间<input v-model="logsForm.start" type="datetime-local"></label><label>结束时间<input v-model="logsForm.end" type="datetime-local"></label><button :disabled="logsBusy" @click="queryLogs">{{ logsBusy ? '查询中…' : '查询日志' }}</button></div>
        <div v-if="logsError" class="panel-state error">{{ logsError }}</div>
        <div v-if="logsResult" class="result-block"><div class="result-summary">匹配 {{ logsResult.matchedCount }} 条<span v-if="logsResult.truncated"> · 结果已截断</span></div><div class="table-wrap scroll-table"><table><thead><tr><th>时间</th><th>数据源 / 类型</th><th>订单 / 成交号</th><th>数据库原始记录</th></tr></thead><tbody><tr v-for="(row,index) in logsResult.rows || []" :key="`${row.eventTime}-${row.ticket}-${index}`"><td>{{ row.eventTime }}</td><td><span class="badge">{{ row.platform }}</span> {{ row.source }} / {{ row.eventType }}</td><td>{{ row.ticket || '-' }}<small class="cell-sub">{{ row.symbol || '' }}</small></td><td class="details-cell" :title="JSON.stringify(row.details)">{{ detailsPreview(row.details) }}</td></tr><tr v-if="!logsResult.rows?.length"><td colspan="4" class="empty-cell">暂无查询结果</td></tr></tbody></table></div></div>
      </div>
    </section>

    <section class="panel tool-panel push-panel">
      <div class="section-head"><div><h2>全平台风险发现</h2><small>只读 · 持久化任务 · 支持取消和重启恢复</small></div><span>{{ discoveryTab === 'push' ? pushJobMessage() : discoveryTab === 'rebate' ? '返佣确认型检测' : discoveryTab === 'bonus' ? '赠金资金周期检测' : '仓位风险与特殊时点检测' }}</span></div>
      <div class="discovery-tabs" role="tablist"><button :class="{ active: discoveryTab === 'push' }" @click="discoveryTab='push'">推盘发现</button><button :class="{ active: discoveryTab === 'rebate' }" @click="discoveryTab='rebate'">刷返佣发现</button><button :class="{ active: discoveryTab === 'bonus' }" @click="discoveryTab='bonus'">赠金套利发现</button><button :class="{ active: discoveryTab === 'position' }" @click="discoveryTab='position'">重仓时点发现</button></div>
      <div v-if="discoveryTab === 'push'">
      <div class="push-scope-row"><label>扫描窗口（天）<input v-model.number="pushForm.days" type="number" min="1" max="30"></label><label>深检账号上限<input v-model.number="pushForm.deepLimit" type="number" min="1" max="300"></label><span>按初筛优先级最多深检 {{ pushForm.deepLimit }} 个账号</span><button class="primary" :disabled="pushJob && ['queued','running'].includes(pushJob.status)" @click="startPushDiscovery">{{ pushJob && ['queued','running'].includes(pushJob.status) ? '检测中…' : '开始全平台检测' }}</button><button v-if="pushJob && ['queued','running'].includes(pushJob.status)" :disabled="pushJob.cancel_requested" @click="cancelPushDiscovery">{{ pushJob.cancel_requested ? '正在停止…' : '取消' }}</button></div>
      <div class="push-filter-grid">
        <div class="push-filter-item"><label class="filter-toggle"><input v-model="pushForm.requirePeriodProfit" type="checkbox"><span>窗口净收益为正</span></label><small>只保留扫描窗口内交易净收益大于 0 的账户</small></div>
        <div class="push-filter-item"><label class="filter-toggle"><input v-model="pushForm.limitOrders" type="checkbox"><span>限制窗口订单数</span></label><label class="filter-value">最多<input v-model.number="pushForm.maxOrders" type="number" min="1" max="1000" :disabled="!pushForm.limitOrders"> 单</label></div>
        <div class="push-filter-item"><label class="filter-toggle"><input v-model="pushForm.requireMaxLot" type="checkbox"><span>要求窗口最大手数</span></label><label class="filter-value">大于<input v-model.number="pushForm.minMaxLot" type="number" min="0" max="100000" step="0.01" :disabled="!pushForm.requireMaxLot"> 手</label></div>
        <div class="push-filter-item"><label class="filter-toggle"><input v-model="pushForm.requireTotalProfit" type="checkbox"><span>历史交易净收益为正</span></label><small>按账户生命周期内已执行交易的净收益计算</small></div>
        <div class="push-filter-item"><label class="filter-toggle"><input v-model="pushForm.limitDeposit" type="checkbox"><span>限制累计入金</span></label><label class="filter-value">不超过<input v-model.number="pushForm.maxDeposit" type="number" min="0" max="10000000" step="100" :disabled="!pushForm.limitDeposit"> USD</label></div>
        <div class="push-filter-item"><label class="filter-toggle"><input v-model="pushForm.limitActiveRatio" type="checkbox"><span>限制活跃天数占比</span></label><label class="filter-value">不超过<input v-model.number="pushForm.maxActiveRatio" type="number" min="0" max="100" step="1" :disabled="!pushForm.limitActiveRatio"> %</label></div>
        <div class="push-filter-item"><label class="filter-toggle"><input v-model="pushForm.excludeHandled" type="checkbox"><span>排除已处置账户</span></label><small>排除数据库状态及本地台账中的 T / TA / A / A/TA</small></div>
      </div>
      <p class="tool-note">最大手数按扫描窗口内单笔成交手数计算，并严格要求大于设定值。活跃天数占比 = 有开仓行为的自然日数 ÷ 注册至今总天数。关闭某项后，该条件不参与候选初筛。扫描窗口只用于候选初筛；进入深检后读取账号全部历史订单。最终名单固定要求历史净收益为正，且疑似区间净收益达到 100，或达到 50 且不低于累计入金的 10%。</p>
      <div v-if="pushJob" class="job-card"><div class="job-head"><b>{{ pushJobMessage() }}</b><span>{{ pushJob.progress || 0 }}%</span></div><div class="progress"><i :style="{width:`${pushJob.progress || 0}%`}" /></div><div v-if="pushJob.connectionError" class="inline-warning">{{ pushJob.connectionDetail }}</div><div v-if="pushJob.error" class="inline-error">{{ pushJob.error }}</div></div>
      <div v-if="pushJob?.result?.summary?.economicQualified != null" class="push-result-subhead"><h3>经济证据通过 {{ pushJob.result.summary.economicQualified }} 个</h3><span>完成深检 {{ pushJob.result.summary.deepCompleted }} 个 · 排除低收益/亏损 {{ pushJob.result.summary.economicallyRejected }} 个</span></div>
      <div v-if="pushJob?.result?.results?.length" class="table-wrap push-results"><table><thead><tr><th>排名</th><th>账号</th><th>平台 / 服务器</th><th>窗口 / 深检订单</th><th>窗口最大手数</th><th>历史净收益</th><th>疑似区间净收益</th><th>累计入金</th><th>活跃 / 注册</th><th>初筛分</th><th>深检分</th><th>等级</th><th>Tick</th><th>协同开仓</th><th>结论</th></tr></thead><tbody><tr v-for="row in pushJob.result.results" :key="`${row.platform}-${row.server}-${row.account}`"><td>{{ row.deepRank }}</td><td><a :href="pushAccountHref(row)">{{ row.account }}</a></td><td>{{ row.platform }} / {{ row.server }}</td><td><b>{{ row.orders }}</b> / <b>{{ row.deepOrders }}</b><small class="cell-sub">初筛窗口 / 全历史深检</small></td><td>{{ pushNumber(row.maxLot, 2) }} 手</td><td>{{ pushNumber(row.totalNet) }} {{ row.currency }}</td><td class="push-interval-profit" :class="pushProfitClass(row.suspectedIntervalNetProfit)" :title="suspectedIntervalTitle(row)"><b>{{ Number(row.suspectedIntervalCount) ? pushNumber(row.suspectedIntervalNetProfit) : '-' }} {{ Number(row.suspectedIntervalCount) ? row.currency : '' }}</b><small>{{ Number(row.suspectedIntervalCount) ? `${row.suspectedIntervalOrders}单 / ${row.suspectedIntervalCount}段 · ${suspectedIntervalBasis(row)}` : '未形成可单列区间' }}</small></td><td>{{ pushNumber(row.depositTotal) }} {{ row.currency }}</td><td>{{ row.activeDays ?? '-' }} / {{ row.registrationDays ?? '-' }}（{{ pushNumber(row.activeRatio, 1) }}%）</td><td>{{ row.initialScore }}</td><td :class="Number(row.deepScore)>=60 ? 'negative' : ''">{{ row.deepScore }}</td><td>{{ row.level || '-' }}</td><td>{{ row.tickAvailable ? '可用' : '无' }}</td><td>{{ row.coordinatedMatchedRatio }}%</td><td class="note-cell" :title="row.headline">{{ row.headline || '-' }}</td></tr></tbody></table></div>
      <div v-else-if="pushJob?.status === 'done' && pushJob?.result?.summary?.economicQualified === 0" class="panel-state">深检已完成，没有账号同时满足形态证据和高风险高回报条件。</div>
      <div v-if="pushJob?.result?.failures?.length" class="push-failure-section">
        <div class="push-result-subhead"><h3>失败明细（{{ pushJob.result.failureTotal }}）</h3><span>{{ pushFailureSummary() }}</span></div>
        <div class="table-wrap push-failures"><table class="push-failure-table"><thead><tr><th>阶段</th><th>账号</th><th>平台 / 服务器</th><th>数据源</th><th>失败原因</th><th>影响</th><th>尝试次数</th></tr></thead><tbody><tr v-for="(failure,index) in pushJob.result.failures" :key="`${failure.stage}-${failure.source}-${failure.account}-${index}`"><td><span class="failure-stage">{{ failure.stageLabel }}</span></td><td><a v-if="failure.account" :href="accountHref(failure.account, failure.platform, failure.server)">{{ failure.account }}</a><span v-else>-</span></td><td>{{ failure.platform && failure.server ? `${failure.platform} / ${failure.server}` : failure.server || failure.platform || '-' }}</td><td>{{ failure.source || '-' }}</td><td class="failure-reason"><b>{{ failure.reason }}</b><small v-if="failure.detail && failure.detail !== failure.reason">{{ failure.detail }}</small></td><td class="failure-impact">{{ failure.impact }}</td><td>{{ failure.attempts }}</td></tr></tbody></table></div>
      </div>
      </div>
      <RebateDiscoveryPanel v-else-if="discoveryTab === 'rebate'" />
      <BonusArbitrageDiscoveryPanel v-else-if="discoveryTab === 'bonus'" />
      <PositionRiskDiscoveryPanel v-else />
    </section>

    <section class="panel tool-panel">
      <div class="section-head"><div><h2>下线净入金统计</h2><small>IB / 客户层级 · 活动归属与产品手数</small></div><button class="text-button" @click="tools.hierarchy=!tools.hierarchy">{{ tools.hierarchy ? '收起' : '展开' }}</button></div>
      <div v-if="tools.hierarchy">
        <div class="filter-row tool-form wrap"><label class="grow">IB / 客户<input v-model="hierarchyForm.target" placeholder="交易账号、CRM ID 或精确姓名"></label><label>开始时间<input v-model="hierarchyForm.start" type="datetime-local"></label><label>结束时间<input v-model="hierarchyForm.end" type="datetime-local"></label><label>产品<select v-model="hierarchyForm.product"><option value="">全部产品</option><option :value="products.data.value?.promotionValue || ''">{{ products.data.value?.promotionLabel || '本次活动产品' }}</option><option v-for="item in products.data.value?.products || []" :key="item" :value="item">{{ item }}</option></select></label><button :disabled="hierarchyBusy" @click="queryHierarchy">{{ hierarchyBusy ? '统计中…' : '统计' }}</button></div>
        <label class="check-row"><input v-model="hierarchyForm.activityRules" type="checkbox">按本次活动归属规则计算（60,000 USD + 600手；排除 Cent）</label>
        <div v-if="hierarchyError" class="panel-state error">{{ hierarchyError }}</div>
        <div v-if="hierarchyResult" class="result-block"><div class="result-summary">{{ hierarchyResult.targetLabel || hierarchyResult.target || hierarchyForm.target }}<span> · {{ hierarchyResult.summary?.message || hierarchyResult.message || '统计完成' }}</span></div><div class="metric-grid hierarchy-summary"><div v-for="(value,key) in hierarchyResult.summary || {}" :key="String(key)"><span>{{ key }}</span><b>{{ value }}</b></div></div><div class="table-wrap" v-if="hierarchyResult.rows?.length"><table><thead><tr><th>层级</th><th>客户 / IB</th><th>角色</th><th>服务器</th><th>交易账号</th><th>入金</th><th>出金</th><th>净入金</th><th>产品订单</th><th>产品手数</th><th>交易盈亏</th></tr></thead><tbody><tr v-for="(row,index) in hierarchyResult.rows" :key="index"><td>{{ row.level ?? row.depth ?? '-' }}</td><td>{{ row.name || row.customer || row.login || '-' }}</td><td>{{ row.role || '-' }}</td><td>{{ row.server || '-' }}</td><td>{{ row.account || row.login || '-' }}</td><td>{{ row.deposit ?? '-' }}</td><td>{{ row.withdrawal ?? '-' }}</td><td>{{ row.netDeposit ?? '-' }}</td><td>{{ row.orders ?? '-' }}</td><td>{{ row.volume ?? '-' }}</td><td>{{ row.profit ?? '-' }}</td></tr></tbody></table></div></div>
      </div>
    </section>

    <section class="panel ledger-panel">
      <div class="section-head"><div><h2>已标记账号 <span class="count-pill">{{ records.length }}</span></h2><small>筛选、查看与行内状态更新</small></div><a class="button-link" href="/download/problematic_accounts.xlsx">导出 Excel</a></div>
      <div class="ledger-filters"><input v-model="listSearch" aria-label="列表过滤" placeholder="账号、标签、备注、IB"><select v-model="actionFilter" aria-label="建议动作"><option value="">全部动作</option><option v-for="item in actions" :key="item" :value="item">{{ item }}</option></select><select v-model="statusFilter" aria-label="状态"><option value="">全部状态</option><option v-for="item in statuses" :key="item" :value="item">{{ item }}</option></select></div>
      <PanelState :loading="query.isLoading.value" :error="query.error.value as Error" :empty="!records.length">
        <div class="table-wrap ledger-table"><table><thead><tr><th>账号</th><th>建议</th><th>分组</th><th>风险标签</th><th>备注</th><th>状态</th><th>更新时间</th></tr></thead>
          <tbody><tr v-for="row in records" :key="row['记录ID']"><td><a :href="accountHref(row['账号'])">{{ row['账号'] || '-' }}</a></td><td><span class="action-badge">{{ row['建议动作'] || '-' }}</span></td><td>{{ row['当前分组'] || '-' }}</td><td>{{ row['风险标签'] || '-' }}</td><td class="note-cell" :title="row['风险/问题备注']">{{ row['风险/问题备注'] || '-' }}</td><td><select class="inline-select" :disabled="statusSaving===row['记录ID']" :value="row['状态']" :aria-label="`修改 ${row['账号']} 的状态`" @change="updateStatus(row, ($event.target as HTMLSelectElement).value)"><option v-for="item in ['待复核','观察中','已确认','已关闭']" :key="item">{{ item }}</option></select></td><td>{{ row['修改时间'] || '-' }}</td></tr></tbody>
        </table></div>
      </PanelState>
    </section>
  </main>
</template>
