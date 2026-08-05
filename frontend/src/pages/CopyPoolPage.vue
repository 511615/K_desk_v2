<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { formatBeijingDateTime as dateTime, formatBeijingTime as timeOnly } from '../beijingTime'
import { accountPrimaryLabel, accountSecondaryLabel, copyReasonLabel, copyStatusLabel, currentCopyRows, formatDuration, linePath, orderActionLabel, phaseLabel, POOL_TIER_TABS, poolTierLabel, poolTierReason, poolTierTabLabel, resolvePoolTierRows, schedulerStateLabel, sourceActionLabel, sourceEntryLabel, sourceSideLabel, sourceStateFailed, sourceStateLabel, stepPath, weightReason, weightStateLabel } from '../copyPool'
import type { PoolTierTab } from '../copyPool'
import { startFrontendUpdateMonitor } from '../frontendUpdate'

const poolSearch = ref('')
const poolFilter = ref<'all' | 'abook' | 'position' | 'reduced'>('all')
const selectedPoolTier = ref<PoolTierTab>('active')
const controlsSaving = ref(false)
const controlsMessage = ref('')
const controlForm = ref({ autoTradingEnabled: true, equityFloorEnabled: true, dailyLossEnabled: true, cycleLossEnabled: true })
const runtimeClockMs = ref(Date.now())
let stopFrontendUpdateMonitor: () => void = () => undefined
let runtimeClockTimer: ReturnType<typeof setInterval> | undefined

const dashboard = useQuery({
  queryKey: ['copy-pool-dashboard'],
  queryFn: () => api<any>('/api/copy-pool/dashboard?timeline_limit=720&event_limit=120&order_limit=120'),
  refetchInterval: 1000,
  staleTime: 0,
  retry: 1,
})

const payload = computed<any>(() => dashboard.data.value || {})
const status = computed<any>(() => payload.value.status || {})
const demoAccount = computed<any>(() => payload.value.demoAccount || {})
const demoAccountSummary = computed<any>(() => demoAccount.value.account || {})
const demoAccountPositions = computed<any[]>(() => demoAccount.value.positions || [])
const demoAccountDeals = computed<any[]>(() => demoAccount.value.deals || [])
const demoAccountFloatingPnl = computed(() => demoAccountPositions.value.reduce(
  (total, row) => total + Number(row.floatingPnlUsd || 0) + Number(row.swapUsd || 0),
  0,
))
const pool = computed<any[]>(() => payload.value.pool || [])
const sourceCoverage = computed<any>(() => payload.value.sourceCoverage || {})
const sourceRows = computed<any[]>(() => sourceCoverage.value.sources || [])
const timeline = computed<any[]>(() => payload.value.timeline || [])
const clientRisks = computed<any[]>(() => payload.value.clientRisks || [])
const copyPositions = computed<any[]>(() => payload.value.copyPositions || [])
const ticketMappings = computed<any[]>(() => payload.value.ticketMappings || [])
const currentCopies = computed<any[]>(() => payload.value.currentCopies || [])
const exposures = computed<any[]>(() => payload.value.exposures || [])
const productQuotes = computed<any[]>(() => status.value.products || [])
const dynamicSleeves = computed<any[]>(() => payload.value.dynamicSleeves || status.value.dynamicSleeves || [])
const scheduler = computed<any>(() => payload.value.scheduler || status.value.scheduler || {})
const controls = computed<any>(() => payload.value.controls || status.value.manualControls || {})
watch(controls, value => {
  controlForm.value = {
    autoTradingEnabled: value.autoTradingEnabled !== false,
    equityFloorEnabled: value.equityFloorEnabled !== false,
    dailyLossEnabled: value.dailyLossEnabled !== false,
    cycleLossEnabled: value.cycleLossEnabled !== false,
  }
}, { immediate: true })
async function saveControls(resumeRequested = false) {
  controlsSaving.value = true
  controlsMessage.value = ''
  try {
    await api('/api/copy-pool/controls', { method: 'PUT', body: JSON.stringify({ ...controlForm.value, resumeRequested }) })
    controlsMessage.value = resumeRequested ? '已请求解除硬停，系统将进入恢复影子核对' : '风控开关已保存，Producer 将在下一轮读取'
    await dashboard.refetch?.()
  } catch (error: any) {
    controlsMessage.value = `保存失败：${error?.message || '未知错误'}`
  } finally {
    controlsSaving.value = false
  }
}
const chartRows = computed(() => timeline.value.slice(-360))
const filters = [
  { key: 'all', label: '全部' },
  { key: 'abook', label: 'A 类账户' },
  { key: 'position', label: '当前持仓' },
  { key: 'reduced', label: '已降权' },
] as const

const filteredPool = computed(() => {
  const needle = poolSearch.value.trim().toLowerCase()
  return pool.value.filter(row => {
    if (poolFilter.value === 'abook' && !row.isABook) return false
    if (poolFilter.value === 'position' && Number(row.openPositionCount) <= 0) return false
    if (poolFilter.value === 'reduced' && row.weightState !== 'reduced') return false
    return !needle
      || String(row.accountLogin).toLowerCase().includes(needle)
      || String(row.accountServer).toLowerCase().includes(needle)
      || String(row.product).toLowerCase().includes(needle)
      || String(row.routeKey).toLowerCase().includes(needle)
      || weightStateLabel(row).includes(needle)
  })
})

const equityPath = computed(() => linePath(chartRows.value, 'equityUsd', 760, 250, 56, 22))
const positionPath = computed(() => stepPath(chartRows.value, 'actualStrategyLots', status.value.hardMaxLots || 0.05, 760, 250, 56, 22))
const spreadPath = computed(() => linePath(chartRows.value, 'spreadPrice', 330, 112, 34, 17))
const latencyPath = computed(() => linePath(chartRows.value, 'dbLatencyP95Seconds', 330, 112, 34, 17))
const pnlPath = computed(() => linePath(chartRows.value, 'strategyMarkedPnlUsd', 330, 112, 34, 17))
const equityRange = computed(() => numericRange(chartRows.value, 'equityUsd'))
const spreadRange = computed(() => numericRange(chartRows.value, 'spreadPrice'))
const latencyRange = computed(() => numericRange(chartRows.value, 'dbLatencyP95Seconds'))
const pnlRange = computed(() => numericRange(chartRows.value, 'strategyMarkedPnlUsd'))
const chartTimes = computed(() => {
  if (!chartRows.value.length) return ['-', '-', '-']
  const middle = chartRows.value[Math.floor(chartRows.value.length / 2)]
  return [timeOnly(chartRows.value[0].time), timeOnly(middle.time), timeOnly(chartRows.value.at(-1)?.time)]
})

const contributionRows = computed(() => pool.value
  .filter(row => Math.abs(Number(row.targetContributionLots)) > 1e-8)
  .sort((left, right) => Math.abs(right.targetContributionLots) - Math.abs(left.targetContributionLots))
  .slice(0, 8))
const contributionMax = computed(() => Math.max(...contributionRows.value.map(row => Math.abs(row.targetContributionLots)), 0.0001))
const weightRows = computed(() => [...pool.value]
  .sort((left, right) => Number(right.baseWeight) - Number(left.baseWeight))
  .slice(0, 10))
const weightMax = computed(() => Math.max(...weightRows.value.map(row => Number(row.baseWeight)), 0.03))
const openRiskRows = computed(() => pool.value
  .filter(row => Number(row.openPositionCount) > 0)
  .sort((left, right) => openRiskSeverity(right) - openRiskSeverity(left))
  .slice(0, 10))
const openRiskSummary = computed(() => ({
  accounts: pool.value.filter(row => Number(row.openPositionCount) > 0).length,
  positions: pool.value.reduce((total, row) => total + Number(row.openPositionCount || 0), 0),
  xauGrossLots: pool.value.reduce((total, row) => total + Number(row.xauGrossLots || 0), 0),
  floatingPnlUsd: pool.value.reduce((total, row) => total + Number(row.floatingPnlUsd || 0), 0),
}))
const demoExposure = computed(() => exposures.value.reduce((summary, row) => ({
  long: summary.long + Number(row.longLots || 0),
  short: summary.short + Number(row.shortLots || 0),
  gross: summary.gross + Number(row.grossLots || 0),
  net: summary.net + Number(row.netLots || 0),
  locked: summary.locked + Number(row.lockedLots || 0),
}), { long: 0, short: 0, gross: 0, net: 0, locked: 0 }))
const clientRiskRows = computed(() => [...clientRisks.value]
  .sort((left, right) => Number(right.lossUsage) - Number(left.lossUsage)))
const activeCopyPositions = computed(() => copyPositions.value
  .filter(row => Number(row.copiedLots) > 0 || Number(row.copiedSignedLots) !== 0 || (row.demoTickets || []).length > 0))
const currentCopyRowsForDisplay = computed(() => currentCopyRows(
  activeCopyPositions.value,
  ticketMappings.value,
  currentCopies.value,
))
const tierRows = computed(() => resolvePoolTierRows(pool.value, dynamicSleeves.value, clientRisks.value))
const tierSummary = computed(() => tierRows.value.reduce((summary, row) => {
  const tier = row.currentTier
  summary[tier] = (summary[tier] || 0) + 1
  return summary
}, {} as Record<string, number>))
const selectedTierRows = computed(() => tierRows.value
  .filter(row => row.currentTier === selectedPoolTier.value)
  .sort((left, right) => Number(right.effectiveWeight) - Number(left.effectiveWeight)))
const schedulerRows = computed(() => [
  { label: '风险检查', cadence: '10 秒', at: scheduler.value.lastRiskAt || scheduler.value.last_risk_at, state: scheduler.value.riskState || 'completed' },
  { label: '池内重排', cadence: '15 分钟', at: scheduler.value.lastRankAt || scheduler.value.last_rank_at, state: scheduler.value.rankState || 'completed' },
  { label: '全市场发现', cadence: '1 小时', at: scheduler.value.lastDiscoveryAt || scheduler.value.last_discovery_at, state: scheduler.value.discoveryState || 'completed' },
  { label: '完整建池', cadence: '每日 05:15', at: scheduler.value.lastDailyRebuildAt || scheduler.value.lastDailyRebuildDate || scheduler.value.last_daily_rebuild_date, state: scheduler.value.dailyState || 'completed' },
])

const activity = computed(() => {
  const source = (payload.value.events || []).map((row: any) => ({
    key: row.eventId,
    time: row.time,
    kind: '客户成交',
    subject: `${row.accountLogin || '来源账号'} ${sourceSideLabel(row.sourceSide)} ${lots(row.sourceLots)} 手`,
    reason: `${row.product || '-'} · ${sourceEntryLabel(row.sourceEntry)} · ${row.decision || '已更新独立来源仓'}`,
    latency: `${number(row.dbLatencySeconds, 2)}秒`,
    warning: false,
  }))
  const orders = (payload.value.orders || []).map((row: any) => ({
    key: row.orderEvent,
    time: row.time,
    kind: '模拟账户',
    subject: `${row.accountLogin || '组合风控'} · ${orderActionLabel(row.action)}`,
    reason: `${row.product || '-'} · 来源仓 ${row.sourcePositionId || '-'} · Demo ${row.demoTickets?.join('、') || '-'} · ${signedLots(row.beforeLots)} → ${signedLots(row.afterLots)} · 回报码 ${row.retcode || '-'}`,
    latency: `${number(row.quoteAgeSeconds, 2)}秒`,
    warning: Number(row.retcode) !== 10009,
  }))
  return [...source, ...orders]
    .sort((left, right) => Date.parse(right.time) - Date.parse(left.time))
    .slice(0, 30)
})

const gates = computed(() => [
  { label: '全部逻辑路由完成建池扫描', value: `${sourceCoverage.value.logicalScanned || 0} / ${sourceCoverage.value.logicalExpected || 11}`, ok: Number(sourceCoverage.value.logicalScanned) === Number(sourceCoverage.value.logicalExpected) && Number(sourceCoverage.value.logicalExpected) > 0 },
  { label: '入池物理源均保持可用', value: `${sourceCoverage.value.healthy || 0} / ${sourceCoverage.value.physicalScanned || 9}`, ok: sourceRows.value.filter(row => Number(row.selectedClients) > 0).every(row => row.state === 'ok' && Number(row.ageSeconds) <= 3) },
  { label: '状态文件持续更新', value: payload.value.sourceAgeSeconds == null ? '-' : `${number(payload.value.sourceAgeSeconds, 2)}秒`, ok: !payload.value.stale },
  { label: '数据库最近读取成功', value: `${number(status.value.dbSecondsSinceSuccess, 2)}秒前`, ok: Number(status.value.dbSecondsSinceSuccess) <= 3 },
  { label: '行情更新时间小于 2 秒', value: `${number(status.value.quoteAgeSeconds, 2)}秒`, ok: Number(status.value.quoteAgeSeconds) <= 2 },
  { label: '点差小于 1.00', value: number(status.value.spreadPrice, 2), ok: Number(status.value.spreadPrice) <= 1 },
  { label: '模拟账户允许交易', value: status.value.terminalTradeAllowed ? '已允许' : '已禁止', ok: Boolean(status.value.terminalTradeAllowed) },
  { label: '程序化下单已授权', value: status.value.liveExecutionAuthorized ? '已授权' : '未授权', ok: Boolean(status.value.liveExecutionAuthorized) },
  { label: '无外部仓位冲突', value: status.value.externalPositionConflict ? '发现冲突' : '正常', ok: !status.value.externalPositionConflict },
  { label: '无外部挂单冲突', value: status.value.pendingOrderConflict ? '发现冲突' : '正常', ok: !status.value.pendingOrderConflict },
])

function numericRange(rows: any[], key: string): { min: number; max: number } {
  const values = rows.map(row => Number(row[key])).filter(Number.isFinite)
  return values.length ? { min: Math.min(...values), max: Math.max(...values) } : { min: 0, max: 0 }
}

function number(value: unknown, digits = 2): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '-'
}

function money(value: unknown): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'
}

function percent(value: unknown, digits = 2): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(digits)}%` : '-'
}

function lots(value: unknown, digits = 2): string {
  return number(Math.abs(Number(value)), digits)
}

function signedLots(value: unknown, digits = 2): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return `${parsed > 0 ? '+' : ''}${parsed.toFixed(digits)}`
}

function demoEntryLabel(value: unknown): string {
  const labels: Record<string, string> = { IN: '开仓', OUT: '平仓', INOUT: '反转', OUT_BY: '对向平仓' }
  return labels[String(value || '').toUpperCase()] || '成交'
}

function ownershipLabel(value: unknown): string {
  return value ? '本策略' : '其他交易'
}

function positionHolding(value: unknown): string {
  const opened = Date.parse(String(value || ''))
  return Number.isFinite(opened) ? formatDuration(Math.max(0, (runtimeClockMs.value - opened) / 1000)) : '-'
}

function sideLabel(value: unknown): string {
  const parsed = Number(value)
  return parsed > 0 ? '多头' : parsed < 0 ? '空头' : '空仓'
}

function meterWidth(value: unknown, limit: unknown): string {
  const ratio = Math.abs(Number(value)) / Math.max(Math.abs(Number(limit)), 1e-9)
  return `${Math.min(100, Math.max(0, ratio * 100)).toFixed(1)}%`
}

function contributionWidth(value: unknown): string {
  return `${Math.max(2, Math.abs(Number(value)) / contributionMax.value * 100).toFixed(1)}%`
}

function weightWidth(value: unknown): string {
  return `${Math.max(0, Number(value)) / weightMax.value * 100}%`
}

function thresholdWidth(value: unknown, threshold: number): string {
  return `${Math.min(100, Math.max(0, Number(value) / threshold * 100)).toFixed(1)}%`
}

function delayValue(row: any, phase: 'entry' | 'exit' | 'combined'): unknown {
  return row[`${phase}DelayScore`] ?? row[`${phase}_delay_score`] ?? (phase === 'combined' ? row.delay?.score ?? row.delayScore ?? row.factorDelayScore : undefined)
}

function currentHoldingDuration(row: any): string {
  if (row.holdingSeconds != null) return formatDuration(row.holdingSeconds)
  const openedAt = Date.parse(String(row.sourceOpenedAt || ''))
  return Number.isFinite(openedAt) ? formatDuration((runtimeClockMs.value - openedAt) / 1000) : '-'
}

function shadowProgress(row: any): string {
  const endsAt = row.shadowEndsAt || row.shadow_ends_at
  if (!endsAt) return '-'
  const remaining = Date.parse(String(endsAt)) - runtimeClockMs.value
  return remaining <= 0 ? '等待状态确认' : `剩余 ${formatDuration(remaining / 1000)}`
}

function openRiskSeverity(row: any): number {
  return Math.max(
    Number(row.floatingLossRatio) / 0.10,
    Number(row.marginToEquity) / 0.50,
    Number(row.xauHedgeRatio),
  )
}

onMounted(() => {
  document.title = '动态跟单监控 · K_desk'
  runtimeClockTimer = setInterval(() => {
    runtimeClockMs.value = Date.now()
  }, 250)
  stopFrontendUpdateMonitor = startFrontendUpdateMonitor(() => window.location.reload())
})

onBeforeUnmount(() => {
  if (runtimeClockTimer !== undefined) clearInterval(runtimeClockTimer)
  stopFrontendUpdateMonitor()
})
</script>

<template>
  <header class="topbar copy-topbar">
    <div><b>账号风控台账</b><span>统一主帐台 · 8777</span></div>
    <nav><a href="/">账号工作台</a><a class="active" href="/copy-pool">动态跟单</a><a href="/download/problematic_accounts.xlsx">导出台账</a><a href="/?legacy=1">旧版工作台</a></nav>
  </header>

  <main class="copy-pool-page">
    <section class="copy-titlebar">
      <div><h1>动态客户池独立跟单</h1><p>1 万美元资金方案 · 全产品横截面 · 客户仓位互不抵消 · {{ status.server || '模拟账户' }} · 11 条逻辑路由</p></div>
      <div class="copy-title-status">
        <span class="status-live" :class="{ stale: payload.stale }"><i></i>{{ payload.stale ? '数据已停滞' : phaseLabel(status.phase) }}</span>
        <span class="badge">只读监控</span>
        <span class="badge">{{ status.clients || pool.length || 0 }} 个客户</span>
        <span data-testid="runtime-clock">北京时间 {{ dateTime(runtimeClockMs) }}</span>
      </div>
    </section>

    <div v-if="dashboard.isLoading.value" class="panel-state"><span class="spinner"></span> 正在读取实时跟单状态</div>
    <div v-else-if="dashboard.error.value" class="panel-state error">监控接口读取失败：{{ (dashboard.error.value as any)?.message || '未知错误' }}</div>
    <div v-else-if="!payload.available" class="panel-state">{{ payload.message || '当前没有可显示的跟单数据' }}</div>

    <template v-else>
      <section class="copy-panel demo-account-panel" data-testid="demo-account-panel">
        <div class="copy-panel-head demo-account-head">
          <div><h2>当前 Demo 账户</h2><small>{{ demoAccountSummary.login || status.accountLogin || '-' }} · {{ demoAccountSummary.server || status.server || '-' }} · <span data-testid="demo-account-clock">北京时间 {{ dateTime(runtimeClockMs) }}</span></small></div>
          <span :class="status.terminalTradeAllowed ? 'positive' : 'warning'">{{ status.terminalTradeAllowed ? '自动交易已开启' : '自动交易已关闭' }}</span>
        </div>
        <div class="demo-account-summary">
          <div><span>账号</span><b>{{ demoAccountSummary.login || status.accountLogin || '-' }}</b></div>
          <div><span>余额</span><b>{{ money(demoAccountSummary.balanceUsd ?? status.balanceUsd) }} USD</b></div>
          <div><span>权益</span><b>{{ money(demoAccountSummary.equityUsd ?? status.equityUsd) }} USD</b></div>
          <div><span>已用 / 可用保证金</span><b>{{ money(demoAccountSummary.marginUsd) }} / {{ money(demoAccountSummary.freeMarginUsd) }}</b></div>
          <div><span>保证金率</span><b>{{ number(demoAccountSummary.marginLevelPercent, 2) }}%</b></div>
          <div><span>当前持仓盈亏</span><b :class="demoAccountFloatingPnl >= 0 ? 'positive' : 'negative'">{{ demoAccountFloatingPnl >= 0 ? '+' : '' }}{{ money(demoAccountFloatingPnl) }} USD</b></div>
        </div>
        <div class="demo-account-ledgers">
          <div class="demo-ledger">
            <div class="demo-ledger-title"><h3>当前持仓</h3><span>{{ demoAccountPositions.length }} 笔</span></div>
            <div class="table-wrap demo-account-table"><table><thead><tr><th>Ticket</th><th>产品 / 方向</th><th>手数</th><th>开仓价 / 现价</th><th>浮盈亏 / 隔夜费</th><th>开仓时间（北京时间）/ 持仓</th><th>归属</th></tr></thead><tbody><tr v-for="row in demoAccountPositions" :key="row.ticket"><td><b>{{ row.ticket }}</b><small class="cell-note">Position {{ row.positionId }}</small></td><td><b>{{ row.product || '-' }}</b><small class="cell-note" :class="row.side === 'BUY' ? 'positive' : 'negative'">{{ sourceSideLabel(row.side) }}</small></td><td><b>{{ lots(row.lots) }}</b></td><td><b>{{ number(row.openPrice, 5) }}</b><small class="cell-note">现 {{ number(row.currentPrice, 5) }}</small></td><td :class="Number(row.floatingPnlUsd) + Number(row.swapUsd) >= 0 ? 'positive' : 'negative'"><b>{{ money(Number(row.floatingPnlUsd) + Number(row.swapUsd)) }}</b><small class="cell-note">浮 {{ money(row.floatingPnlUsd) }} · 隔夜 {{ money(row.swapUsd) }}</small></td><td><b>{{ dateTime(row.openedAt) }}</b><small class="cell-note">{{ positionHolding(row.openedAt) }}</small></td><td><span class="ownership-badge" :class="{ external: !row.strategyOwned }">{{ ownershipLabel(row.strategyOwned) }}</span></td></tr><tr v-if="!demoAccountPositions.length"><td colspan="7" class="empty-cell">当前账户没有持仓</td></tr></tbody></table></div>
          </div>
          <div class="demo-ledger">
            <div class="demo-ledger-title"><h3>历史成交</h3><span>近 30 日 · 最近 {{ demoAccountDeals.length }} 条</span></div>
            <div class="table-wrap demo-account-table"><table><thead><tr><th>成交时间（北京时间）</th><th>Deal / Position</th><th>产品 / 动作</th><th>手数 / 价格</th><th>净损益</th><th>归属</th></tr></thead><tbody><tr v-for="row in demoAccountDeals" :key="row.dealTicket"><td><b>{{ dateTime(row.time) }}</b></td><td><b>{{ row.dealTicket }}</b><small class="cell-note">Position {{ row.positionId }}</small></td><td><b>{{ row.product || '-' }}</b><small class="cell-note" :class="row.side === 'BUY' ? 'positive' : 'negative'">{{ demoEntryLabel(row.entry) }} · {{ sourceSideLabel(row.side) }}</small></td><td><b>{{ lots(row.lots) }} 手</b><small class="cell-note">{{ number(row.price, 5) }}</small></td><td :class="Number(row.netPnlUsd) >= 0 ? 'positive' : 'negative'"><b>{{ Number(row.netPnlUsd) >= 0 ? '+' : '' }}{{ money(row.netPnlUsd) }}</b></td><td><span class="ownership-badge" :class="{ external: !row.strategyOwned }">{{ ownershipLabel(row.strategyOwned) }}</span></td></tr><tr v-if="!demoAccountDeals.length"><td colspan="6" class="empty-cell">近 30 日没有交易成交</td></tr></tbody></table></div>
          </div>
        </div>
      </section>

      <section class="copy-panel risk-control-panel" data-testid="risk-controls">
        <div class="copy-panel-head"><div><h2>人工风控控制</h2><small>仅本机可修改；关闭保护不会自动解除已触发的硬停，需单独请求恢复影子</small></div><span :class="status.dailyHardStop ? 'negative' : 'positive'">{{ status.dailyHardStop ? '当前硬停' : '未硬停' }}</span></div>
        <div class="risk-control-grid">
          <label><input v-model="controlForm.autoTradingEnabled" type="checkbox"><span><b>自动下单</b><small>关闭后禁止新增敞口，仍允许减仓和平仓</small></span></label>
          <label><input v-model="controlForm.equityFloorEnabled" data-testid="equity-floor-toggle" type="checkbox"><span><b>权益地板</b><small>当前阈值 {{ money(status.equityFloorUsd) }} USD</small></span></label>
          <label><input v-model="controlForm.dailyLossEnabled" type="checkbox"><span><b>日内亏损硬停</b><small>当前额度 {{ money(status.dailyLossLimitUsd) }} USD</small></span></label>
          <label><input v-model="controlForm.cycleLossEnabled" type="checkbox"><span><b>周期亏损冷却</b><small>当前额度 {{ money(status.cycleLossLimitUsd) }} USD</small></span></label>
        </div>
        <div class="risk-control-actions"><button class="primary" data-testid="apply-risk-controls" :disabled="controlsSaving" @click="saveControls(false)">保存风控开关</button><button :disabled="controlsSaving || !status.dailyHardStop" @click="saveControls(true)">解除硬停并恢复影子</button><small>{{ controlsMessage || `当前阶段：${phaseLabel(status.phase)}` }}</small></div>
      </section>
      <section class="copy-summary-grid">
        <article><span>模拟账户权益</span><strong>{{ money(status.equityUsd) }} USD</strong><small :class="Number(status.strategyMarkedPnlUsd) >= 0 ? 'positive' : 'negative'">今日 {{ Number(status.strategyMarkedPnlUsd) >= 0 ? '+' : '' }}{{ money(status.strategyMarkedPnlUsd) }} USD</small></article>
        <article><span>Demo 多仓 / 空仓</span><strong class="positive">+{{ number(demoExposure.long) }}</strong><small class="negative">空仓 -{{ number(demoExposure.short) }} · 双边 {{ number(demoExposure.gross) }} 手</small></article>
        <article><span>独立来源仓 / Demo Ticket</span><strong>{{ status.independentSourcePositions || copyPositions.length }} / {{ status.independentDemoTickets || ticketMappings.length }}</strong><small>组合净敞口 {{ signedLots(demoExposure.net) }} · 对锁 {{ number(demoExposure.locked) }} 手</small></article>
        <article><span>本周期损益</span><strong :class="Number(status.cyclePnlUsd) >= 0 ? 'positive' : 'negative'">{{ Number(status.cyclePnlUsd) >= 0 ? '+' : '' }}{{ money(status.cyclePnlUsd) }} USD</strong><small>周期止损额度 {{ money(status.cycleLossLimitUsd) }} USD</small></article>
      </section>

      <section class="health-strip" aria-label="实时链路状态">
        <article><span>可见运行时长</span><b>{{ formatDuration(payload.uptimeSeconds) }}</b></article>
        <article><span>数据库状态</span><b>{{ Number(status.dbSecondsSinceSuccess) <= 3 ? '正常' : '中断' }} · {{ number(status.dbSecondsSinceSuccess, 2) }}秒</b></article>
        <article><span>最近客户成交（北京时间）</span><b>{{ payload.lastSourceEventAt ? timeOnly(payload.lastSourceEventAt) : '-' }}</b></article>
        <article><span>行情更新时间</span><b>{{ number(status.quoteAgeSeconds, 2) }}秒前</b></article>
        <article><span>95% 多源轮询</span><b :class="{ warning: Number(status.dbPollLatencyP95Seconds) > 2 }">{{ number(status.dbPollLatencyP95Seconds, 2) }}秒</b></article>
        <article><span>连续对账一致</span><b>{{ status.reconcileStreak || 0 }} 次</b></article>
        <article><span>自动交易</span><b :class="status.terminalTradeAllowed ? 'positive' : 'negative'">{{ status.terminalTradeAllowed ? '已开启' : '已关闭' }}</b></article>
        <article><span>重复事件</span><b :class="Number(status.duplicateEvents) ? 'warning' : ''">{{ status.duplicateEvents || 0 }} 条</b></article>
      </section>

      <section class="copy-analysis-grid scheduler-grid">
        <article class="copy-panel tier-panel">
          <div class="copy-panel-head"><div><h2>客户池层级与影子准入</h2><small>选择层级查看当前归属账号；监控与候补持续参与动态评估</small></div><span>{{ tierRows.length }} 个 sleeve</span></div>
          <div class="tier-summary tier-tabs" role="tablist" aria-label="客户池层级">
            <button v-for="tier in POOL_TIER_TABS" :key="tier" type="button" role="tab" :aria-selected="selectedPoolTier === tier" :class="{ active: selectedPoolTier === tier }" @click="selectedPoolTier = tier">
              <span>{{ poolTierTabLabel(tier) }}</span><b>{{ tierSummary[tier] || 0 }}</b>
            </button>
          </div>
          <div class="tier-table-wrap" role="tabpanel">
            <table class="tier-account-table"><thead><tr><th>交易账号</th><th>产品</th><th>计划 / 实际权重</th><th>当前状态</th><th>主要原因</th></tr></thead><tbody><tr v-for="row in selectedTierRows" :key="String(row.clientProductKey)"><td><a v-if="row.detailPath" :href="String(row.detailPath)">{{ accountPrimaryLabel(row) }} ↗</a><b v-else>{{ accountPrimaryLabel(row) }}</b><small v-if="row.accountServer">{{ accountSecondaryLabel(row) }}</small></td><td><b>{{ row.product }}</b></td><td>{{ percent(row.baseWeight) }} / {{ percent(row.effectiveWeight) }}</td><td><b>{{ poolTierLabel(row.currentTier) }}</b><small v-if="row.clientRisk?.status">{{ copyStatusLabel(row.clientRisk.status) }}</small></td><td><small>{{ poolTierReason(row) }}</small></td></tr><tr v-if="!selectedTierRows.length"><td colspan="5" class="empty-cell">当前层级暂无账户 × 产品组合</td></tr></tbody></table>
          </div>
          <small class="panel-footnote">影子期产生的来源仓永久仅监控，不补追；活动资格、最小风险手数和硬门槛均需同时满足。</small>
        </article>
        <article class="copy-panel">
          <div class="copy-panel-head"><div><h2>调度节奏</h2><small>实时成交、风险降权、排序发现和每日完整重建分层运行</small></div></div>
          <div class="scheduler-list"><div v-for="row in schedulerRows" :key="row.label"><b>{{ row.label }}</b><span>{{ row.cadence }}</span><small>{{ row.at ? dateTime(row.at) : '尚未运行' }}</small><em>{{ schedulerStateLabel(row.state) }}</em></div></div>
        </article>
      </section>

      <section class="copy-panel source-coverage-panel">
        <div class="copy-panel-head"><div><h2>全库来源覆盖</h2><small>建池 {{ sourceCoverage.logicalScanned || 0 }} / {{ sourceCoverage.logicalExpected || 11 }} 条逻辑路由 · 监控 {{ sourceCoverage.monitorAccounts || 0 }} 人 / 活动 {{ sourceCoverage.activeAccounts || 0 }} 人 · 产品 {{ (sourceCoverage.activeProducts || []).join('、') || '无' }}</small></div><span :class="Number(sourceCoverage.healthy) === Number(sourceCoverage.physicalScanned) ? 'positive' : 'warning'">{{ sourceCoverage.healthy || 0 }} / {{ sourceCoverage.physicalScanned || 9 }} 源可用</span></div>
        <div class="source-grid" role="list" aria-label="数据库来源运行状态">
          <div v-for="row in sourceRows" :key="row.physicalKey" class="source-row" :class="{ failed: sourceStateFailed(row) }" role="listitem">
            <i></i><div><b>{{ row.connection }} · {{ row.platform }}</b><small>{{ row.physicalKey }}</small></div>
            <div><span>候选 / 合格 / 入池</span><b>{{ row.candidateAccounts }} / {{ row.eligibleAccounts }} / {{ row.selectedClients }}</b></div>
            <div><span>读取延迟</span><b>{{ number(Number(row.latencyMs) / 1000, 2) }}秒</b></div>
            <strong>{{ sourceStateLabel(row) }}</strong>
          </div>
        </div>
      </section>

      <section class="copy-main-grid">
        <article class="copy-panel equity-panel">
          <div class="copy-panel-head"><div><h2>权益与净仓位</h2><small>最近 {{ chartRows.length }} 个状态点 · 北京时间</small></div><div class="chart-legend"><span><i class="equity-line"></i>权益</span><span><i class="position-line"></i>实际净仓</span></div></div>
          <div class="main-chart">
            <svg viewBox="0 0 760 250" role="img" aria-label="模拟账户权益与实际净仓时间序列">
              <line v-for="y in [22,74,126,178,228]" :key="y" class="grid-line" x1="56" :y1="y" x2="704" :y2="y" />
              <line class="zero-line" x1="56" y1="125" x2="704" y2="125" />
              <path class="position-path" :d="positionPath" />
              <path class="equity-path" :d="equityPath" />
              <text class="axis-label" x="4" y="28">{{ money(equityRange.max) }}</text>
              <text class="axis-label" x="4" y="226">{{ money(equityRange.min) }}</text>
              <text class="axis-label" x="710" y="28">+{{ number(status.hardMaxLots) }}</text>
              <text class="axis-label" x="716" y="129">0.00</text>
              <text class="axis-label" x="710" y="226">-{{ number(status.hardMaxLots) }}</text>
              <text class="axis-label" x="56" y="246">{{ chartTimes[0] }}</text>
              <text class="axis-label" x="350" y="246">{{ chartTimes[1] }}</text>
              <text class="axis-label" x="660" y="246">{{ chartTimes[2] }}</text>
            </svg>
          </div>
        </article>

        <aside class="copy-side-stack">
          <article class="copy-panel">
            <div class="copy-panel-head"><div><h2>组合风险额度</h2><small>风险层只拒绝或缩量，不合并客户 Ticket</small></div><span class="badge">{{ status.dailyHardStop ? '已停止' : '正常' }}</span></div>
            <div class="risk-row"><div><span>压力损失预算</span><b>{{ money(status.portfolioStressBudgetUsd) }} USD</b></div><i><i class="warning-fill" :style="{ width: meterWidth(Math.max(0, -Number(status.cyclePnlUsd)), status.portfolioStressBudgetUsd) }"></i></i></div>
            <div class="risk-row"><div><span>周期亏损</span><b>{{ money(Math.max(0, -Number(status.cyclePnlUsd))) }} / {{ money(status.cycleLossLimitUsd) }} USD</b></div><i><i :style="{ width: meterWidth(Math.min(0, Number(status.cyclePnlUsd)), status.cycleLossLimitUsd) }"></i></i></div>
            <div class="risk-row"><div><span>当日亏损</span><b>{{ money(Math.max(0, -Number(status.strategyMarkedPnlUsd))) }} / {{ money(status.dailyLossLimitUsd) }} USD</b></div><i><i class="danger-fill" :style="{ width: meterWidth(Math.min(0, Number(status.strategyMarkedPnlUsd)), status.dailyLossLimitUsd) }"></i></i></div>
            <div class="risk-row"><div><span>权益地板缓冲</span><b>{{ money(Math.max(0, Number(status.equityUsd) - Number(status.equityFloorUsd))) }} USD</b></div><i><i class="safe-fill" :style="{ width: meterWidth(Number(status.equityUsd) - Number(status.equityFloorUsd), Number(status.balanceUsd) - Number(status.equityFloorUsd)) }"></i></i></div>
          </article>
          <article class="copy-panel">
            <div class="copy-panel-head"><div><h2>Demo 独立仓敞口</h2><small>多空仓同时保留，净额仅用于风险观察</small></div></div>
            <div class="exposure-bar"><i class="long" :style="{ width: percent(demoExposure.long / Math.max(demoExposure.gross, .0001), 2) }"></i><i class="short"></i></div>
            <div class="exposure-values"><div><span>多头</span><b class="positive">+{{ number(demoExposure.long, 4) }}</b></div><div><span>空头</span><b class="negative">-{{ number(demoExposure.short, 4) }}</b></div><div><span>净敞口</span><b>{{ signedLots(demoExposure.net, 4) }}</b></div></div>
            <div class="product-exposure-list"><div v-for="row in exposures" :key="row.product"><b>{{ row.product }}</b><span>多 {{ number(row.longLots) }} · 空 {{ number(row.shortLots) }} · 净 {{ signedLots(row.netLots) }}</span></div><div v-if="!exposures.length" class="empty-inline">当前无 Demo 策略仓</div></div>
          </article>
        </aside>
      </section>

      <section class="mini-chart-grid">
        <article class="copy-panel"><div class="mini-head"><div><h2>主报价点差</h2><small>各产品按自身压力阈值判断，不共用黄金阈值</small></div><b>{{ number(status.spreadPrice, 2) }}</b></div><svg viewBox="0 0 330 112" role="img" aria-label="主报价点差变化"><line class="grid-line" x1="34" y1="17" x2="320" y2="17" /><line class="grid-line" x1="34" y1="95" x2="320" y2="95" /><path class="small-path" :d="spreadPath" /><text class="axis-label" x="2" y="22">{{ number(spreadRange.max, 2) }}</text><text class="axis-label" x="2" y="99">{{ number(spreadRange.min, 2) }}</text></svg></article>
        <article class="copy-panel"><div class="mini-head"><div><h2>成交入库延迟</h2><small>秒 · 95 分位参考上限 2.00</small></div><b :class="{ warning: Number(status.dbLatencyP95Seconds) > 2 }">{{ number(status.dbLatencyP95Seconds, 2) }}</b></div><svg viewBox="0 0 330 112" role="img" aria-label="成交入库延迟变化"><line class="grid-line" x1="34" y1="17" x2="320" y2="17" /><line class="grid-line" x1="34" y1="95" x2="320" y2="95" /><path class="small-path warning-path" :d="latencyPath" /><text class="axis-label" x="2" y="22">{{ number(latencyRange.max, 2) }}</text><text class="axis-label" x="2" y="99">{{ number(latencyRange.min, 2) }}</text></svg></article>
        <article class="copy-panel"><div class="mini-head"><div><h2>策略当日损益</h2><small>USD · 已实现与持仓浮盈亏合计</small></div><b :class="Number(status.strategyMarkedPnlUsd) >= 0 ? 'positive' : 'negative'">{{ money(status.strategyMarkedPnlUsd) }}</b></div><svg viewBox="0 0 330 112" role="img" aria-label="策略当日损益变化"><line class="zero-line" x1="34" y1="56" x2="320" y2="56" /><path class="small-path pnl-path" :d="pnlPath" /><text class="axis-label" x="2" y="22">{{ money(pnlRange.max) }}</text><text class="axis-label" x="2" y="99">{{ money(pnlRange.min) }}</text></svg></article>
      </section>

      <section class="copy-panel product-watch-panel">
        <div class="copy-panel-head"><div><h2>产品执行监控</h2><small>每个产品独立检查报价、点差、当前多空仓和有效权重</small></div><span>{{ productQuotes.length }} 个已配置产品</span></div>
        <div class="product-watch-grid"><div v-for="row in productQuotes" :key="row.product" :class="{ failed: !row.spreadAllowsOpen }"><i></i><div><b>{{ row.product }}</b><span>Bid {{ number(row.bid, 3) }} · Ask {{ number(row.ask, 3) }}</span></div><div><span>点差 / 报价年龄</span><b>{{ number(row.spreadPrice, 3) }} / {{ number(row.quoteAgeSeconds, 2) }}秒</b></div><div><span>多 / 空 / 有效权重</span><b>{{ number(row.grossLongLots) }} / {{ number(row.grossShortLots) }} / {{ percent(row.activeWeight) }}</b></div><strong>{{ row.spreadAllowsOpen ? '允许开仓' : '禁止加仓' }}</strong></div><div v-if="!productQuotes.length" class="empty-inline">尚无产品执行快照</div></div>
      </section>

      <section class="copy-panel open-risk-panel">
        <div class="copy-panel-head"><div><h2>客户池未平仓风险</h2><small>按浮亏率、保证金占用和黄金对锁比例排序 · 总手数不会被净手数抵消</small></div><span>10% 浮亏 / 50% 保证金占用为建池硬门槛</span></div>
        <div class="open-risk-summary">
          <div><span>持仓账户</span><b>{{ openRiskSummary.accounts }} / {{ pool.length }}</b></div>
          <div><span>未平仓笔数</span><b>{{ openRiskSummary.positions }}</b></div>
          <div><span>黄金总手数</span><b>{{ number(openRiskSummary.xauGrossLots, 2) }}</b></div>
          <div><span>池内浮盈亏</span><b :class="openRiskSummary.floatingPnlUsd >= 0 ? 'positive' : 'negative'">{{ money(openRiskSummary.floatingPnlUsd) }}</b></div>
        </div>
        <div class="open-risk-list">
          <div v-for="row in openRiskRows" :key="row.clientProductKey" class="open-risk-row">
            <a v-if="row.detailPath" :href="row.detailPath">{{ accountPrimaryLabel(row) }} ↗</a><b v-else>{{ accountPrimaryLabel(row) }}</b>
            <div><span>{{ row.openPositionCount }} 笔 · 黄金总 {{ number(row.xauGrossLots, 2) }} / 净 {{ signedLots(row.xauNetLots) }}</span><small>最老 {{ formatDuration(row.oldestOpenSeconds) }} · 对锁 {{ percent(row.xauHedgeRatio, 0) }}</small></div>
            <div class="risk-meter"><span>浮亏 {{ percent(row.floatingLossRatio) }}</span><i><i class="danger-fill" :style="{ width: thresholdWidth(row.floatingLossRatio, .10) }"></i></i></div>
            <div class="risk-meter"><span>保证金 {{ percent(row.marginToEquity) }}</span><i><i class="warning-fill" :style="{ width: thresholdWidth(row.marginToEquity, .50) }"></i></i></div>
            <strong :class="Number(row.floatingPnlUsd) >= 0 ? 'positive' : 'negative'">{{ money(row.floatingPnlUsd) }}</strong>
          </div>
          <div v-if="!openRiskRows.length" class="empty-inline">当前池内账户均无未平仓头寸</div>
        </div>
      </section>

      <section class="copy-analysis-grid">
        <article class="copy-panel">
          <div class="copy-panel-head"><div><h2>客户比例手数参考</h2><small>按资金同比估算排序，实际手数还受客户与组合风险额度约束</small></div><span>仅用于解释，不执行客户间净仓</span></div>
          <div class="contribution-list"><div v-for="row in contributionRows" :key="row.clientProductKey" class="contribution-row"><a v-if="row.detailPath" :href="row.detailPath">{{ accountPrimaryLabel(row) }} · {{ row.product }} ↗</a><b v-else>{{ accountPrimaryLabel(row) }} · {{ row.product }}</b><i><i :class="Number(row.targetContributionLots) >= 0 ? 'positive-fill' : 'negative-fill'" :style="{ width: contributionWidth(row.targetContributionLots) }"></i></i><span :class="Number(row.targetContributionLots) >= 0 ? 'positive' : 'negative'">{{ signedLots(row.targetContributionLots, 4) }}</span></div><div v-if="!contributionRows.length" class="empty-inline">当前没有比例手数参考</div></div>
        </article>
        <article class="copy-panel">
          <div class="copy-panel-head"><div><h2>账户 × 产品权重变化</h2><small>浅蓝为计划分配，实色为实际执行</small></div><span>实际 / 计划</span></div>
          <div class="weight-list"><div v-for="row in weightRows" :key="row.clientProductKey" class="weight-row"><a v-if="row.detailPath" :href="row.detailPath">{{ accountPrimaryLabel(row) }}</a><b v-else>{{ accountPrimaryLabel(row) }}</b><i class="weight-track"><i class="base" :style="{ width: weightWidth(row.baseWeight) }"></i><i class="effective" :class="{ reduced: row.weightState !== 'full' }" :style="{ width: weightWidth(row.effectiveWeight) }"></i></i><span><b>{{ row.product }} · {{ percent(row.effectiveWeight) }} / {{ percent(row.baseWeight) }}</b><small :class="{ negative: row.weightState !== 'full' }">{{ weightReason(row) }}</small></span></div></div>
        </article>
      </section>

      <section class="copy-panel client-budget-panel">
        <div class="copy-panel-head"><div><h2>客户独立亏损额度</h2><small>每个客户只使用自己的 Demo 实体仓损益；其他客户盈利不能抵消</small></div><span>活动 {{ status.activeCopyClients || 0 }} / 监控 {{ status.monitorSleeves || pool.length }}</span></div>
        <div class="client-budget-grid">
          <a v-for="row in clientRiskRows" :key="row.clientAlias" :href="row.detailPath" class="client-budget-row">
            <div><b>{{ accountPrimaryLabel(row) }}</b><span>{{ copyStatusLabel(row.status) }} · {{ row.reductionReason || '额度正常' }}</span></div>
            <div class="budget-meter"><i><i :class="{ warning: Number(row.lossUsage) >= .5, danger: Number(row.lossUsage) >= .8 }" :style="{ width: percent(Math.min(1, Number(row.lossUsage)), 1) }"></i></i><span>{{ money(row.lossUsedUsd) }} / {{ money(row.lossBudgetUsd) }} USD</span></div>
            <strong :class="Number(row.totalPnlUsd) >= 0 ? 'positive' : 'negative'">{{ money(row.totalPnlUsd) }}</strong>
          </a>
          <div v-if="!clientRiskRows.length" class="empty-inline">尚无客户复制额度状态</div>
        </div>
      </section>

      <section class="copy-panel independent-panel">
        <div class="copy-panel-head"><div><h2>当前跟单</h2><small>每行对应一个来源 Position 到 Demo Ticket 的独立关系；客户之间不相互对冲或平仓</small></div><span>{{ activeCopyPositions.length }} 个来源仓 · {{ currentCopyRowsForDisplay.filter(row => row.demoTicket != null).length }} 个 Demo Ticket</span></div>
        <div v-if="dashboard.isLoading.value" class="empty-inline">正在读取当前跟单状态...</div>
        <div v-else class="table-wrap current-copy-table"><table><thead><tr><th>单主账号</th><th>服务器 / 平台</th><th>产品 / 方向</th><th>来源 Position / 手数</th><th>Demo Ticket / 手数</th><th>来源开仓（北京时间）</th><th>单主浮盈亏</th><th>我们的收益</th><th>入场延迟</th><th>持仓时间</th><th>状态</th></tr></thead><tbody><tr v-for="row in currentCopyRowsForDisplay" :key="row.currentCopyKey"><td class="account-identity"><a v-if="row.detailPath" :href="row.detailPath"><b>{{ row.accountLogin || '-' }}</b><span aria-hidden="true">↗</span></a><b v-else>{{ row.accountLogin || '-' }}</b></td><td><b>{{ row.accountServer || '-' }}</b><small class="cell-note">{{ row.accountPlatform || '平台未提供' }}</small></td><td><b>{{ row.product || '-' }}</b><small class="cell-note" :class="{ positive: row.signedLots > 0, negative: row.signedLots < 0 }">{{ row.signedLots > 0 ? '买入' : row.signedLots < 0 ? '卖出' : '方向未提供' }}</small></td><td><b>{{ row.sourcePositionId || '-' }}</b><small class="cell-note">{{ lots(row.sourceLots) }} 手</small></td><td><b>{{ row.demoTicket ?? '尚未复制' }}</b><small class="cell-note" :class="{ positive: row.signedLots > 0, negative: row.signedLots < 0 }">{{ row.demoTicket == null ? '-' : `${signedLots(row.signedLots)} 手` }}</small></td><td><b>{{ dateTime(row.sourceOpenedAt) }}</b><small class="cell-note">{{ row.sourceOpenPrice == null ? '开仓价未提供' : `价格 ${number(row.sourceOpenPrice, 5)}` }}</small></td><td :class="{ positive: Number(row.sourcePnlUsd) >= 0, negative: Number(row.sourcePnlUsd) < 0 }"><b>{{ row.sourcePnlUsd == null ? '未提供' : money(row.sourcePnlUsd) }}</b><small class="cell-note">{{ row.sourcePnlUsd == null ? '待运行时投影' : '当前来源仓 · USD' }}</small></td><td :class="{ positive: Number(row.demoPnlUsd) >= 0, negative: Number(row.demoPnlUsd) < 0 }"><b>{{ row.demoPnlUsd == null ? '未提供' : money(row.demoPnlUsd) }}</b><small class="cell-note">{{ row.demoPnlUsd == null ? '待运行时投影' : '已实现 + 浮动 · USD' }}</small></td><td><b>{{ row.entryDelaySeconds == null ? '-' : `${number(row.entryDelaySeconds, 2)}秒` }}</b><small class="cell-note">{{ row.entryDelaySeconds == null ? '等待运行时记录' : '来源到Demo开仓' }}</small></td><td><b>{{ currentHoldingDuration(row) }}</b><small class="cell-note">来源仓</small></td><td><b>{{ copyStatusLabel(row.status) }}</b><small class="cell-note">{{ row.rejectReason ? copyReasonLabel(row.rejectReason) : '正常跟踪' }}</small></td></tr><tr v-if="!currentCopyRowsForDisplay.length"><td colspan="11" class="empty-cell">当前没有正在复制的来源仓和 Demo Ticket</td></tr></tbody></table></div>
      </section>

      <section class="copy-panel pool-panel">
        <div class="copy-panel-head pool-heading">
          <div><h2>当前账户 × 产品监控池</h2><small>首道门槛为20日已平仓净收益 + 当前同产品浮盈亏 &gt; 0 · 收益不含返佣 · 美分账户金额已换算为 USD</small></div>
          <div class="pool-controls"><label>筛选账户<input v-model="poolSearch" placeholder="输入交易账号、服务器或产品"></label><div class="pool-tabs"><button v-for="item in filters" :key="item.key" :class="{ active: poolFilter === item.key }" @click="poolFilter = item.key">{{ item.label }}</button></div></div>
        </div>
        <div class="table-wrap pool-table"><table><thead><tr><th>交易账号</th><th>产品 / 当前层级</th><th>历史评分 / 盘中评分</th><th>历史延迟因子</th><th>权益回撤</th><th>典型持仓区间</th><th>计划分配 / 实际执行</th><th>影子准入 / 闸门</th><th>同产品来源仓</th><th>20日综合收益 / 浮盈亏</th><th>执行状态</th></tr></thead><tbody><tr v-for="row in filteredPool" :key="row.clientProductKey"><td class="account-identity"><a v-if="row.detailPath" :href="row.detailPath"><b>{{ accountPrimaryLabel(row) }}</b><span aria-hidden="true">↗</span></a><b v-else>{{ accountPrimaryLabel(row) }}</b><small v-if="row.accountLogin">{{ accountSecondaryLabel(row) }}</small></td><td><b>{{ row.product }}</b><small class="cell-note">{{ poolTierLabel(row.poolTier || row.tier || row.poolStatus) }}</small></td><td><b>历史 {{ number(row.factorBaseScore ?? row.adjustedScore, 3) }} · 盘中 {{ row.hourlyScore == null ? '待刷新' : number(row.hourlyScore, 3) }}</b><small class="cell-note">1小时 {{ money(row.recentNet1hUsd) }} · 4小时 {{ money(row.recentNet4hUsd) }}</small><small class="cell-note">{{ row.isABook ? 'A 类 +0.02' : '标准账户' }} · 风险 × {{ percent(row.openRiskMultiplier, 0) }}</small></td><td class="quality-cell"><template v-if="row.historicalDelayFactorEnabled"><b>入 {{ number(row.delay?.entryP95Ms, 0) }} / 出 {{ number(row.delay?.exitP95Ms, 0) }} ms</b><small class="cell-note">综合分 {{ percent(delayValue(row, 'combined'), 0) }} · 收益保留 {{ percent(row.delay?.profitRetention, 0) }}</small><small class="cell-note">平衡延迟 入 / 出 / 综合 {{ number(row.delay?.entryBreakEvenMs / 1000, 1) }} / {{ number(row.delay?.exitBreakEvenMs / 1000, 1) }} / {{ number(row.delay?.combinedBreakEvenMs / 1000, 1) }}秒</small></template><template v-else><b>后续版本启用</b><small class="cell-note">当前不参与评分或硬过滤</small><small class="cell-note">实时信号过期与执行延迟监控仍生效</small></template></td><td class="quality-cell"><b>近20日 {{ percent(row.drawdown?.mdd20d) }} · 近60日 {{ percent(row.drawdown?.mdd60d) }} · 当前 {{ percent(row.drawdown?.current) }}</b><small class="cell-note">{{ row.drawdown?.equityCoverage20d && row.drawdown?.equityCoverage60d ? '历史数据完整' : '历史数据不足' }}</small><small class="cell-note">{{ row.drawdown?.intradayComplete ? '盘中细分完整' : '缺少盘中细分' }}</small></td><td class="quality-cell"><b>75% 长于 {{ formatDuration(row.holdP25Seconds) }}</b><small class="cell-note">90% 短于 {{ formatDuration(row.holdP90Seconds) }}</small><small class="cell-note">隔夜 {{ percent(row.holdingQuality?.overnightRatio) }} · 周末 {{ percent(row.holdingQuality?.weekendRatio) }}</small></td><td class="weight-cell"><b>计划 {{ percent(row.baseWeight) }} · 实际 {{ percent(row.effectiveWeight) }}</b><i class="inline-weight"><i class="base" :style="{ width: weightWidth(row.baseWeight) }"></i><i class="effective" :class="{ reduced: row.weightState !== 'full' }" :style="{ width: weightWidth(row.effectiveWeight) }"></i></i><small class="cell-note">{{ weightReason(row) }}</small></td><td class="quality-cell"><b>{{ shadowProgress(row.dynamicState || row) }}</b><small class="cell-note">入场过期 {{ row.dynamicState?.entryExpiredCount ?? 0 }} · 出场 {{ row.dynamicState?.exitExpiredCount ?? 0 }}</small><small class="cell-note">{{ row.hourlyHardEligible == null ? '待小时刷新（按日建池资格）' : row.hourlyHardEligible ? '当前综合收益硬门通过' : '当前综合收益硬门失败' }}</small><small class="cell-note">{{ row.factorGateReasons?.join('、') || row.factorGateReasons || '无额外拒绝原因' }}</small></td><td :class="Number(row.virtualPositionLots) >= 0 ? 'positive' : 'negative'">{{ signedLots(row.virtualPositionLots) }}<small class="cell-note">比例 {{ signedLots(row.targetContributionLots, 4) }}</small></td><td :class="Number(row.currentComprehensiveNet20dUsd ?? row.comprehensiveNet20dUsd) >= 0 ? 'positive' : 'negative'">{{ money(row.currentComprehensiveNet20dUsd ?? row.comprehensiveNet20dUsd) }}<small class="cell-note">{{ row.currentComprehensiveNet20dUsd == null ? '待小时刷新 · 日建池综合' : '当前小时口径' }}</small><small class="cell-note" :class="Number(row.productFloatingPnlUsd) >= 0 ? 'positive' : 'negative'">浮 {{ money(row.productFloatingPnlUsd) }}</small></td><td :class="{ warning: row.weightState === 'reduced', negative: row.weightState === 'removed' }"><b>{{ weightStateLabel(row) }}</b><small class="cell-note">{{ row.hourlyActivityEligible == null ? '待小时刷新（按日建池资格）' : row.hourlyActivityEligible ? '可进入活动区' : '仅保留监控' }}</small></td></tr><tr v-if="!filteredPool.length"><td colspan="11" class="empty-cell">当前筛选没有账户 × 产品组合</td></tr></tbody></table></div>
      </section>

      <section class="copy-bottom-grid">
        <article class="copy-panel">
          <div class="copy-panel-head"><div><h2>实时事件流</h2><small>客户成交、目标变化与模拟账户回报合并展示</small></div><span>最近 {{ activity.length }} 条</span></div>
          <div class="activity-list"><div v-for="item in activity" :key="`${item.kind}-${item.key}`" class="activity-row"><span>{{ timeOnly(item.time) }}</span><b>{{ item.kind }}</b><strong :class="{ negative: item.warning }">{{ item.subject }}</strong><span>{{ item.reason }}</span><small>{{ item.latency }}</small></div><div v-if="!activity.length" class="empty-inline">暂无事件</div></div>
        </article>
        <article class="copy-panel">
          <div class="copy-panel-head"><div><h2>执行闸门</h2><small>硬闸失败时禁止增加仓位</small></div></div>
          <div class="gate-list"><div v-for="gate in gates" :key="gate.label" class="gate-row" :class="{ failed: !gate.ok }"><i></i><span>{{ gate.label }}</span><b>{{ gate.value }}</b></div></div>
          <div v-if="status.lastError" class="copy-error">最近错误：{{ status.lastError }}</div>
        </article>
      </section>
    </template>
  </main>
</template>

<style scoped>
.copy-topbar nav a.active { color: #fff; background: #0b5683; border-radius: 4px; }
.copy-pool-page { max-width: 1580px; margin: auto; padding: 14px 16px 50px; font-variant-numeric: tabular-nums; }
.risk-control-panel { margin-bottom: 12px; }
.risk-control-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.risk-control-grid label { display: flex; gap: 9px; align-items: flex-start; padding: 10px; border: 1px solid #164c72; border-radius: 6px; background: #061a2e; cursor: pointer; }
.risk-control-grid input { margin-top: 3px; accent-color: #28c89a; }
.risk-control-grid span { display: grid; gap: 3px; }
.risk-control-grid small { color: #7f9db7; line-height: 1.35; }
.risk-control-actions { display: flex; align-items: center; gap: 9px; margin-top: 10px; flex-wrap: wrap; }
.risk-control-actions small { color: #8fa9bf; }
.copy-titlebar { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; padding: 5px 0 12px; border-bottom: 1px solid var(--kdesk-border); }
.copy-titlebar h1 { margin: 0; font-size: 24px; }
.copy-titlebar p { margin: 5px 0 0; color: var(--kdesk-muted); font-size: 12px; }
.copy-title-status { display: flex; align-items: center; justify-content: flex-end; gap: 7px; flex-wrap: wrap; color: var(--kdesk-muted); font-size: 11px; }
.status-live { display: inline-flex; align-items: center; gap: 7px; color: var(--kdesk-text); }
.status-live i { width: 7px; height: 7px; background: var(--kdesk-success); border-radius: 50%; box-shadow: 0 0 0 3px #34c8901f; }
.status-live.stale i { background: var(--kdesk-danger); box-shadow: 0 0 0 3px #f45c6b1f; }
.demo-account-panel { margin-top: 11px; padding: 0; overflow: hidden; }
.demo-account-head { margin: 0; padding: 11px 12px; border-bottom: 1px solid var(--kdesk-border); }
.demo-account-summary { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); border-bottom: 1px solid var(--kdesk-border); }
.demo-account-summary>div { min-width: 0; padding: 9px 11px; border-right: 1px solid var(--kdesk-border); }
.demo-account-summary>div:last-child { border-right: 0; }
.demo-account-summary span,.demo-account-summary b { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.demo-account-summary span { color: var(--kdesk-muted); font-size: 10px; }
.demo-account-summary b { margin-top: 4px; font-size: 13px; }
.demo-account-ledgers { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.demo-ledger { min-width: 0; padding: 10px 11px 11px; }
.demo-ledger:first-child { border-right: 1px solid var(--kdesk-border); }
.demo-ledger-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 7px; }
.demo-ledger-title h3 { margin: 0; font-size: 12px; }
.demo-ledger-title span { color: var(--kdesk-muted); font-size: 10px; }
.demo-account-table { max-height: 230px; border: 1px solid var(--kdesk-border); }
.demo-account-table table { min-width: 760px; }
.demo-account-table th { white-space: nowrap; }
.demo-account-table td { vertical-align: top; }
.ownership-badge { display: inline-block; min-width: 48px; padding: 2px 5px; border: 1px solid #28c89a66; color: var(--kdesk-success); text-align: center; font-size: 10px; }
.ownership-badge.external { border-color: #d7a63b66; color: var(--kdesk-warning); }
.copy-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 11px 0; }
.copy-summary-grid article { min-width: 0; padding: 11px 12px; background: var(--kdesk-surface); border: 1px solid var(--kdesk-border); border-radius: 5px; }
.copy-summary-grid span,.copy-summary-grid small { display: block; color: var(--kdesk-muted); font-size: 11px; }
.copy-summary-grid strong { display: block; margin: 4px 0; font-size: 18px; }
.health-strip { display: grid; grid-template-columns: repeat(8, minmax(100px, 1fr)); margin-bottom: 14px; border-top: 1px solid var(--kdesk-border); border-bottom: 1px solid var(--kdesk-border); }
.health-strip article { min-width: 0; padding: 8px 9px; border-right: 1px solid var(--kdesk-border); }
.health-strip article:last-child { border-right: 0; }
.health-strip span,.health-strip b { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.health-strip span { color: var(--kdesk-muted); font-size: 10px; }
.health-strip b { margin-top: 4px; font-size: 12px; }
.source-coverage-panel { margin-bottom: 14px; }
.source-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--kdesk-border); border-left: 1px solid var(--kdesk-border); }
.source-row { display: grid; grid-template-columns: 10px minmax(135px, 1.35fr) minmax(105px, .9fr) 70px 48px; align-items: center; gap: 8px; min-height: 54px; padding: 7px 9px; border-right: 1px solid var(--kdesk-border); border-bottom: 1px solid var(--kdesk-border); font-size: 10px; }
.source-row>i { width: 7px; height: 7px; border-radius: 50%; background: var(--kdesk-success); }
.source-row.failed>i { background: var(--kdesk-danger); }
.source-row div { min-width: 0; }
.source-row span,.source-row small { display: block; color: var(--kdesk-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-row b { display: block; margin-top: 3px; font-size: 11px; }
.source-row strong { color: var(--kdesk-success); text-align: right; }
.source-row.failed strong { color: var(--kdesk-danger); }
.copy-main-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(290px, .68fr); gap: 14px; }
.copy-side-stack { display: grid; gap: 14px; }
.copy-panel { min-width: 0; padding: 11px; background: linear-gradient(180deg, #071e38, #061a31); border: 1px solid #154875; border-radius: 6px; box-shadow: 0 8px 20px #0003; }
.copy-panel-head,.mini-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.copy-panel h2 { margin: 0; font-size: 14px; }
.copy-panel-head small,.copy-panel-head>span,.mini-head small { display: block; margin-top: 3px; color: var(--kdesk-muted); font-size: 10px; }
.chart-legend { display: flex; gap: 10px; color: var(--kdesk-muted); font-size: 10px; }
.chart-legend i { display: inline-block; width: 15px; height: 2px; margin-right: 4px; vertical-align: middle; }
.chart-legend .equity-line { background: var(--kdesk-primary); }
.chart-legend .position-line { background: var(--kdesk-success); }
.main-chart svg { display: block; width: 100%; height: 250px; }
.grid-line { stroke: #17466d88; stroke-width: 1; }
.zero-line { stroke: #7895ad66; stroke-width: 1; }
.axis-label { fill: var(--kdesk-muted); font-size: 10px; }
.equity-path { fill: none; stroke: var(--kdesk-primary); stroke-width: 2; }
.position-path { fill: none; stroke: var(--kdesk-success); stroke-width: 2; }
.risk-row { margin: 10px 0; }
.risk-row>div { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 5px; font-size: 11px; }
.risk-row>div span { color: var(--kdesk-muted); }
.risk-row>i,.table-weight>i { display: block; height: 6px; overflow: hidden; background: #102a40; border-radius: 4px; }
.risk-row>i>i,.table-weight>i>i { display: block; height: 100%; background: var(--kdesk-primary); }
.risk-row>i>i.warning-fill { background: var(--kdesk-warning); }
.risk-row>i>i.danger-fill,.table-weight>i>i.reduced { background: var(--kdesk-danger); }
.risk-row>i>i.safe-fill { background: var(--kdesk-success); }
.exposure-bar { display: flex; height: 20px; margin: 10px 0 8px; overflow: hidden; background: #102a40; border-radius: 4px; }
.exposure-bar i.long { background: var(--kdesk-success); }
.exposure-bar i.short { min-width: 3px; flex: 1; background: var(--kdesk-danger); }
.exposure-values { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.exposure-values span,.exposure-values b { display: block; }
.exposure-values span { color: var(--kdesk-muted); font-size: 10px; }
.exposure-values b { margin-top: 4px; font-size: 13px; }
.product-exposure-list { margin-top: 9px; border-top: 1px solid var(--kdesk-border); }
.product-exposure-list>div { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; border-bottom: 1px solid #17466d88; font-size: 10px; }
.product-exposure-list span { color: var(--kdesk-muted); }
.mini-chart-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }
.mini-head b { font-size: 15px; }
.mini-chart-grid svg { display: block; width: 100%; height: 112px; }
.small-path { fill: none; stroke: var(--kdesk-primary); stroke-width: 2; }
.warning-path { stroke: var(--kdesk-warning); }
.pnl-path { stroke: var(--kdesk-success); }
.product-watch-panel,.client-budget-panel,.independent-panel { margin-top: 14px; }
.product-watch-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1px solid var(--kdesk-border); border-left: 1px solid var(--kdesk-border); }
.product-watch-grid>div { display: grid; grid-template-columns: 8px minmax(110px, 1fr) minmax(120px, 1fr) minmax(145px, 1.15fr) 70px; align-items: center; gap: 8px; min-height: 48px; padding: 7px 9px; border-right: 1px solid var(--kdesk-border); border-bottom: 1px solid var(--kdesk-border); font-size: 10px; }
.product-watch-grid>div>i { width: 7px; height: 7px; border-radius: 50%; background: var(--kdesk-success); }
.product-watch-grid>div.failed>i { background: var(--kdesk-danger); }
.product-watch-grid span { display: block; color: var(--kdesk-muted); }
.product-watch-grid strong { color: var(--kdesk-success); text-align: right; }
.product-watch-grid .failed strong { color: var(--kdesk-danger); }
.open-risk-panel { margin-top: 14px; }
.open-risk-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 9px; border: 1px solid var(--kdesk-border); }
.open-risk-summary div { padding: 8px 10px; border-right: 1px solid var(--kdesk-border); }
.open-risk-summary div:last-child { border-right: 0; }
.open-risk-summary span,.open-risk-summary b { display: block; }
.open-risk-summary span { color: var(--kdesk-muted); font-size: 10px; }
.open-risk-summary b { margin-top: 4px; font-size: 13px; }
.open-risk-row { display: grid; grid-template-columns: minmax(100px, .8fr) minmax(180px, 1.4fr) minmax(115px, .8fr) minmax(115px, .8fr) 86px; align-items: center; gap: 10px; min-height: 43px; border-bottom: 1px solid #17466d88; font-size: 11px; }
.open-risk-row:last-child { border-bottom: 0; }
.open-risk-row span,.open-risk-row small { display: block; }
.open-risk-row small { margin-top: 3px; color: var(--kdesk-muted); font-size: 10px; }
.open-risk-row>strong { text-align: right; }
.risk-meter>span { margin-bottom: 4px; color: var(--kdesk-muted); font-size: 10px; }
.risk-meter>i { display: block; height: 6px; overflow: hidden; background: #102a40; border-radius: 4px; }
.risk-meter>i>i { display: block; height: 100%; }
.risk-meter .danger-fill { background: var(--kdesk-danger); }
.risk-meter .warning-fill { background: var(--kdesk-warning); }
.copy-analysis-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; margin-top: 14px; }
.contribution-row { display: grid; grid-template-columns: 52px minmax(80px, 1fr) 70px; align-items: center; gap: 7px; min-height: 27px; font-size: 11px; }
.contribution-row>i { height: 7px; overflow: hidden; background: #102a40; border-radius: 3px; }
.contribution-row>i>i { display: block; height: 100%; }
.positive-fill { background: var(--kdesk-success); }
.negative-fill { background: var(--kdesk-danger); }
.contribution-row>span { text-align: right; }
.weight-row { display: grid; grid-template-columns: 46px minmax(100px, 1fr) 150px; align-items: center; gap: 8px; min-height: 39px; border-bottom: 1px solid #17466d88; font-size: 11px; }
.weight-row:last-child { border-bottom: 0; }
.weight-track { position: relative; height: 13px; overflow: hidden; background: #102a40; border-radius: 3px; }
.weight-track i { position: absolute; left: 0; border-radius: 2px; }
.weight-track .base { top: 2px; height: 9px; background: #149fe644; border-right: 2px solid var(--kdesk-primary); }
.weight-track .effective { top: 4px; height: 5px; background: var(--kdesk-success); }
.weight-track .effective.reduced { background: var(--kdesk-danger); }
.weight-row>span { text-align: right; }
.weight-row>span b,.weight-row>span small { display: block; }
.weight-row>span small { margin-top: 2px; color: var(--kdesk-muted); font-size: 10px; }
.client-budget-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1px solid var(--kdesk-border); border-left: 1px solid var(--kdesk-border); }
.client-budget-row { display: grid; grid-template-columns: minmax(145px, .8fr) minmax(180px, 1.35fr) 76px; align-items: center; gap: 10px; min-height: 48px; padding: 7px 9px; border-right: 1px solid var(--kdesk-border); border-bottom: 1px solid var(--kdesk-border); color: inherit; }
.client-budget-row:hover { background: #0a2946; text-decoration: none; }
.client-budget-row span { display: block; margin-top: 3px; color: var(--kdesk-muted); font-size: 10px; }
.client-budget-row>strong { text-align: right; }
.budget-meter>i { display: block; height: 7px; overflow: hidden; background: #102a40; border-radius: 3px; }
.budget-meter>i>i { display: block; height: 100%; background: var(--kdesk-success); }
.budget-meter>i>i.warning { background: var(--kdesk-warning); }
.budget-meter>i>i.danger { background: var(--kdesk-danger); }
.independent-panel table { min-width: 1180px; }
.current-copy-table { max-height: 420px; }
.current-copy-table table { min-width: 1760px; }
.current-copy-table th { white-space: nowrap; }
.current-copy-table td { vertical-align: top; }
.pool-panel { margin-top: 14px; }
.pool-heading { align-items: flex-end; }
.pool-controls { display: flex; align-items: flex-end; gap: 8px; flex-wrap: wrap; }
.pool-controls label { min-width: 150px; }
.pool-controls input { margin-top: 4px; padding: 6px 8px; }
.pool-tabs { display: flex; overflow: hidden; border: 1px solid var(--kdesk-border-strong); border-radius: 5px; }
.pool-tabs button { border: 0; border-right: 1px solid var(--kdesk-border); border-radius: 0; padding: 7px 9px; background: var(--kdesk-bg); color: var(--kdesk-muted); box-shadow: none; }
.pool-tabs button:last-child { border-right: 0; }
.pool-tabs button.active { color: #fff; background: #0b5683; }
.pool-table { max-height: 540px; }
.pool-table table { min-width: 2120px; }
.scheduler-grid { margin: 14px 0; }
.tier-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-top: 1px solid #17466d88; border-left: 1px solid #17466d88; }
.tier-tabs button { min-width: 0; padding: 8px 9px; border: 0; border-right: 1px solid #17466d88; border-bottom: 1px solid #17466d88; background: transparent; color: var(--kdesk-muted); text-align: left; cursor: pointer; }
.tier-tabs button:hover,.tier-tabs button.active { background: #0b568344; color: var(--kdesk-text); }
.tier-tabs button.active { box-shadow: inset 0 -2px 0 var(--kdesk-accent); }
.tier-summary span,.panel-footnote { display: block; color: var(--kdesk-muted); font-size: 10px; }
.tier-summary b { display: block; margin-top: 3px; color: var(--kdesk-text); font-size: 16px; }
.tier-table-wrap { max-height: 286px; margin-top: 9px; overflow: auto; border: 1px solid #17466d88; }
.tier-account-table { width: 100%; min-width: 660px; border-collapse: collapse; font-size: 11px; }
.tier-account-table th { position: sticky; top: 0; z-index: 1; padding: 7px 8px; background: #08223f; color: var(--kdesk-muted); text-align: left; font-size: 10px; font-weight: 600; }
.tier-account-table td { padding: 7px 8px; border-top: 1px solid #17466d66; vertical-align: top; }
.tier-account-table td small { display: block; margin-top: 2px; color: var(--kdesk-muted); line-height: 1.4; }
.tier-account-table a { color: #69c3f0; text-decoration: none; }
.tier-account-table a:hover { color: #a7dcf7; text-decoration: underline; }
.panel-footnote { margin: 9px 0 0; line-height: 1.55; }
.scheduler-list { border-top: 1px solid #17466d88; }
.scheduler-list>div { display: grid; grid-template-columns: minmax(80px, 1fr) 64px minmax(120px, 1.4fr) 72px; align-items: center; gap: 8px; min-height: 29px; border-bottom: 1px solid #17466d88; font-size: 11px; }
.scheduler-list span,.scheduler-list small { color: var(--kdesk-muted); }
.scheduler-list em { color: var(--kdesk-success); font-style: normal; text-align: right; }
.quality-cell { min-width: 150px; line-height: 1.4; }
.quality-cell b,.quality-cell small,.weight-cell b,.weight-cell small { display: block; }
.inline-weight { position: relative; display: block; width: 100%; height: 5px; margin: 6px 0 4px; overflow: hidden; background: #041426; border-radius: 0; }
.inline-weight .base,.inline-weight .effective { position: absolute; left: 0; height: 100%; }
.inline-weight .base { background: #5bb7e455; }
.inline-weight .effective { background: var(--kdesk-success); }
.inline-weight .effective.reduced { background: var(--kdesk-warning); }
.account-identity { min-width: 175px; }
.account-identity>a { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.account-identity small { display: block; max-width: 210px; margin-top: 3px; color: var(--kdesk-muted); font-size: 10px; white-space: normal; }
.table-weight { display: grid; grid-template-columns: 48px 58px; align-items: center; gap: 6px; }
.cell-note { display: block; margin-top: 3px; color: var(--kdesk-muted); font-size: 9px; white-space: nowrap; }
.copy-bottom-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr); gap: 14px; margin-top: 14px; }
.activity-row { display: grid; grid-template-columns: 68px 78px 130px minmax(180px, 1fr) 58px; align-items: center; gap: 8px; min-height: 34px; border-bottom: 1px solid #17466d88; font-size: 11px; }
.activity-row:last-child { border-bottom: 0; }
.activity-row>span,.activity-row>small { color: var(--kdesk-muted); }
.activity-row>small { text-align: right; }
.gate-row { display: grid; grid-template-columns: 10px 1fr auto; align-items: center; gap: 8px; min-height: 34px; border-bottom: 1px solid #17466d88; font-size: 11px; }
.gate-row:last-child { border-bottom: 0; }
.gate-row>i { width: 7px; height: 7px; border-radius: 50%; background: var(--kdesk-success); }
.gate-row.failed>i { background: var(--kdesk-danger); }
.gate-row.failed b { color: var(--kdesk-danger); }
.copy-error { margin-top: 10px; padding: 8px; color: var(--kdesk-danger); background: #f45c6b12; border: 1px solid #f45c6b55; border-radius: 5px; font-size: 11px; }
.empty-inline { padding: 16px; text-align: center; color: var(--kdesk-muted); font-size: 11px; }
.warning { color: var(--kdesk-warning) !important; }
@media (max-width: 1100px) {
  .demo-account-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .demo-account-summary>div:nth-child(3) { border-right: 0; }
  .demo-account-summary>div:nth-child(-n+3) { border-bottom: 1px solid var(--kdesk-border); }
  .demo-account-ledgers { grid-template-columns: 1fr; }
  .demo-ledger:first-child { border-right: 0; border-bottom: 1px solid var(--kdesk-border); }
  .risk-control-grid { grid-template-columns: 1fr 1fr; }
  .health-strip { grid-template-columns: repeat(4, 1fr); }
  .health-strip article:nth-child(4n) { border-right: 0; }
  .health-strip article:nth-child(-n+4) { border-bottom: 1px solid var(--kdesk-border); }
  .copy-main-grid,.copy-bottom-grid { grid-template-columns: 1fr; }
  .copy-side-stack { grid-template-columns: 1fr 1fr; }
  .source-grid { grid-template-columns: 1fr 1fr; }
  .product-watch-grid { grid-template-columns: 1fr; }
  .open-risk-row { grid-template-columns: minmax(100px, .8fr) minmax(170px, 1.3fr) minmax(110px, .8fr) minmax(110px, .8fr) 80px; }
  .scheduler-list>div { grid-template-columns: minmax(75px, 1fr) 58px minmax(105px, 1.2fr) 64px; }
}
@media (max-width: 760px) {
  .copy-pool-page { padding: 10px 8px 32px; }
  .copy-titlebar { flex-direction: column; }
  .copy-title-status { justify-content: flex-start; }
  .copy-summary-grid,.mini-chart-grid,.copy-analysis-grid,.copy-side-stack { grid-template-columns: 1fr; }
  .tier-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tier-table-wrap { max-height: 330px; }
  .scheduler-list>div { grid-template-columns: minmax(80px, 1fr) 58px; gap: 3px 8px; padding: 6px 0; }
  .scheduler-list small { grid-column: 1 / 2; }
  .scheduler-list em { grid-column: 2; grid-row: 1 / 3; }
  .pool-heading { align-items: flex-start; }
  .activity-row { grid-template-columns: 60px 72px 1fr; padding: 6px 0; }
  .activity-row>span:nth-of-type(2) { grid-column: 2 / 4; }
  .activity-row>small { grid-column: 3; grid-row: 1; }
  .source-grid { grid-template-columns: 1fr; }
  .client-budget-grid { grid-template-columns: 1fr; }
  .product-watch-grid>div { grid-template-columns: 8px minmax(95px, 1fr) minmax(105px, 1fr) 62px; }
  .product-watch-grid>div>div:nth-of-type(3) { display: none; }
  .source-row { grid-template-columns: 8px minmax(0, 1.35fr) minmax(76px, .9fr) 50px 36px; gap: 4px; padding: 7px 6px; }
  .source-row strong { font-size: 9px; }
  .open-risk-summary { grid-template-columns: 1fr 1fr; }
  .open-risk-summary div:nth-child(2) { border-right: 0; }
  .open-risk-summary div:nth-child(-n+2) { border-bottom: 1px solid var(--kdesk-border); }
  .open-risk-row { grid-template-columns: 1fr 1fr; gap: 6px 10px; padding: 7px 0; }
  .open-risk-row .risk-meter { grid-column: auto; }
  .open-risk-row>strong { text-align: left; }
}
@media (max-width: 520px) {
  .demo-account-summary { grid-template-columns: 1fr 1fr; }
  .demo-account-summary>div:nth-child(3) { border-right: 1px solid var(--kdesk-border); }
  .demo-account-summary>div:nth-child(2n) { border-right: 0; }
  .demo-account-summary>div:nth-child(-n+4) { border-bottom: 1px solid var(--kdesk-border); }
  .copy-summary-grid,.health-strip { grid-template-columns: 1fr 1fr; }
  .health-strip article:nth-child(2n) { border-right: 0; }
  .health-strip article:nth-child(-n+6) { border-bottom: 1px solid var(--kdesk-border); }
  .pool-controls { width: 100%; align-items: stretch; flex-direction: column; }
  .pool-tabs { width: 100%; }
  .pool-tabs button { flex: 1; padding: 7px 3px; }
  .weight-row { grid-template-columns: 42px minmax(80px, 1fr) 122px; }
  .client-budget-row { grid-template-columns: minmax(110px, .8fr) minmax(130px, 1.2fr) 70px; }
}
</style>
