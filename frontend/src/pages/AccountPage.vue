<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, queryString } from '../api'
import PanelState from '../components/PanelState.vue'

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const login = computed(() => String(route.params.login || ''))
const filters = reactive({ platform: String(route.query.platform || ''), server: String(route.query.server || ''), symbol: String(route.query.symbol || '') })
const filterQuery = computed(() => queryString(filters))

const detail = useQuery({ queryKey: computed(() => ['detail', login.value, filterQuery.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/detail${filterQuery.value}`) })
const risk = useQuery({ queryKey: computed(() => ['risk', login.value, filterQuery.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/risk-panels${filterQuery.value}`) })
const automation = useQuery({ queryKey: computed(() => ['automation', login.value, filterQuery.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/automation-analysis${filterQuery.value}`) })
const ledger = useQuery({ queryKey: computed(() => ['ledger', login.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/ledger`) })
const ips = useQuery({ queryKey: computed(() => ['ips', login.value]), queryFn: () => api<any>(`/api/accounts/by-login/${encodeURIComponent(login.value)}/login-ips`) })

const database = computed(() => detail.data.value?.database || {})
const metrics = computed(() => database.value.metrics || {})
const panels = computed(() => risk.data.value?.riskPanels || {})
const finance = computed(() => panels.value.finance || {})
const highFrequency = computed(() => panels.value.highFrequency || {})
const sameName = computed(() => panels.value.sameName || [])
const form = reactive({ action: '', group: '', tags: '', note: '', status: '待复核', owner: '' })

watch(() => ledger.data.value?.record, record => {
  if (!record) return
  form.action = record['建议动作'] || ''
  form.group = record['当前分组'] || ''
  form.tags = record['风险标签'] || ''
  form.note = record['风险/问题备注'] || ''
  form.status = record['状态'] || '待复核'
  form.owner = record['处理人/来源'] || ''
}, { immediate: true })

function money(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number) : '-'
}

function duration(seconds: unknown): string {
  const value = Number(seconds)
  if (!Number.isFinite(value)) return '-'
  if (value < 60) return `${value.toFixed(1)} 秒`
  if (value < 3600) return `${(value / 60).toFixed(1)} 分钟`
  return `${(value / 3600).toFixed(1)} 小时`
}

function optionValue(item: unknown): string {
  if (typeof item === 'string') return item
  if (item && typeof item === 'object') {
    const value = item as Record<string, unknown>
    return String(value.value || value.label || '')
  }
  return String(item || '')
}

function percent(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(1)}%` : '-'
}

async function applyFilters() {
  await router.replace({ query: Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) })
}

async function saveMark() {
  await api('/api/accounts/mark', { method: 'POST', body: JSON.stringify({ account: login.value, ...form }) })
  await queryClient.invalidateQueries({ queryKey: ['ledger', login.value] })
  await queryClient.invalidateQueries({ queryKey: ['detail', login.value] })
}
</script>

<template>
  <header class="topbar"><div><RouterLink to="/">← 返回工作台</RouterLink><b>账号详情</b><span>Vue 分面板开发版</span></div><a :href="`${route.fullPath}${route.fullPath.includes('?') ? '&' : '?'}legacy=1`">旧版完整页面</a></header>
  <main class="account-page">
    <section class="account-head"><div><div class="eyebrow">ACCOUNT RISK PROFILE</div><h1>{{ login }}</h1><p>{{ database.platforms?.map(optionValue).join(' / ') || filters.platform || '读取平台中' }} · {{ database.servers?.map(optionValue).join(' / ') || filters.server || '读取服务器中' }}</p></div>
      <div class="head-stats"><span>订单 <b>{{ metrics.orderCount ?? '-' }}</b></span><span>净盈亏 <b :class="Number(metrics.netProfit) >= 0 ? 'positive' : 'negative'">{{ money(metrics.netProfit) }}</b></span><span>最近交易 <b>{{ metrics.lastTradeTime || '-' }}</b></span></div></section>

    <section class="panel mark-panel"><div class="section-head"><h2>快捷标记与本地台账</h2><span>{{ ledger.data.value?.marked ? '已加入台账' : '尚未加入台账' }}</span></div>
      <div class="form-grid"><label>建议动作<input v-model="form.action"></label><label>当前分组<input v-model="form.group"></label><label>状态<select v-model="form.status"><option v-for="item in ledger.data.value?.statuses || []" :key="item">{{ item }}</option></select></label><label>风险标签<input v-model="form.tags"></label><label class="wide">风险备注<textarea v-model="form.note" rows="3"></textarea></label><label>处理人 / 来源<input v-model="form.owner"></label><button @click="saveMark">保存全部</button></div>
    </section>

    <section class="panel filters"><div class="section-head"><h2>查询范围</h2><span>每个面板独立加载和失败</span></div><div class="filter-row"><label>平台<select v-model="filters.platform"><option value="">全部平台</option><option v-for="item in database.platforms || []" :key="optionValue(item)" :value="optionValue(item)">{{ optionValue(item) }}</option></select></label><label>服务器<select v-model="filters.server"><option value="">全部服务器</option><option v-for="item in database.servers || []" :key="optionValue(item)" :value="optionValue(item)">{{ optionValue(item) }}</option></select></label><label>品种<select v-model="filters.symbol"><option value="">全部品种</option><option v-for="item in database.symbols || []" :key="optionValue(item)" :value="optionValue(item)">{{ optionValue(item) }}</option></select></label><button @click="applyFilters">刷新指标</button></div></section>

    <section class="panel"><div class="section-head"><h2>同名账户</h2><span>{{ sameName.length }} 个关联账号</span></div><PanelState :loading="risk.isLoading.value" :error="risk.error.value as Error" :empty="!sameName.length"><div class="table-wrap"><table><thead><tr><th>平台/服务器</th><th>账号</th><th>数据库状态</th><th>余额</th><th>净值</th><th>综合盈利</th><th>最高持仓量</th></tr></thead><tbody><tr v-for="row in sameName" :key="`${row.platform}-${row.server}-${row.account}`"><td>{{ row.platform }} / {{ row.server }}</td><td><RouterLink :to="`/account/${row.account}?platform=${row.platform}&server=${encodeURIComponent(row.server)}`">{{ row.account }}</RouterLink></td><td>{{ row.databaseStatus || '-' }}</td><td>{{ money(row.balance) }}</td><td>{{ money(row.equity) }}</td><td>{{ money(row.comprehensiveProfit) }}</td><td>{{ row.highestHoldingVolume ?? '-' }}</td></tr></tbody></table></div></PanelState></section>

    <div class="two-col">
      <section class="panel"><div class="section-head"><h2>交易指标</h2><span>{{ metrics.orderCount ?? '-' }} 笔</span></div><PanelState :loading="detail.isLoading.value" :error="detail.error.value as Error"><div class="metric-grid"><div><span>净胜率</span><b>{{ percent(metrics.winRate) }}</b></div><div><span>总手数</span><b>{{ metrics.totalVolume ?? '-' }}</b></div><div><span>平均持仓</span><b>{{ duration(metrics.averageHoldingSeconds) }}</b></div><div><span>1分钟内</span><b>{{ percent(metrics.oneMinuteHoldingRatio) }}</b></div><div><span>手续费</span><b>{{ money(metrics.commissionTotal) }}</b></div><div><span>Swap</span><b>{{ money(metrics.swapTotal) }}</b></div></div></PanelState></section>
      <section class="panel"><div class="section-head"><h2>账户资金情况</h2><span>{{ finance.displayCurrency || finance.currency || '' }}</span></div><PanelState :loading="risk.isLoading.value" :error="risk.error.value as Error"><div class="metric-grid"><div><span>余额</span><b>{{ money(finance.balance) }}</b></div><div><span>净值</span><b>{{ money(finance.equity) }}</b></div><div><span>净入金</span><b>{{ money(finance.netDeposit) }}</b></div><div><span>持仓盈亏</span><b>{{ money(finance.holdingProfit) }}</b></div><div><span>平仓净盈亏</span><b>{{ money(finance.closedNetProfit) }}</b></div><div><span>综合盈利</span><b>{{ money(finance.comprehensiveProfit) }}</b></div></div></PanelState></section>
    </div>

    <section class="panel"><div class="section-head"><h2>高频与持仓分析</h2><span>{{ highFrequency.orderCount ?? '-' }} 笔平仓订单</span></div><PanelState :loading="risk.isLoading.value" :error="risk.error.value as Error"><div class="metric-grid"><div><span>平均持仓</span><b>{{ highFrequency.averageHoldingMinutes == null ? '-' : `${Number(highFrequency.averageHoldingMinutes).toFixed(1)} 分钟` }}</b></div><div><span>盈利单平均持仓</span><b>{{ highFrequency.winningAverageHoldingMinutes == null ? '-' : `${Number(highFrequency.winningAverageHoldingMinutes).toFixed(1)} 分钟` }}</b></div><div><span>亏损单平均持仓</span><b>{{ highFrequency.losingAverageHoldingMinutes == null ? '-' : `${Number(highFrequency.losingAverageHoldingMinutes).toFixed(1)} 分钟` }}</b></div><div><span>高频订单占比</span><b>{{ percent(highFrequency.highFrequencyOrderRatio) }}</b></div></div></PanelState></section>

    <section class="panel"><div class="section-head"><h2>跟单 / EA 分析</h2><span>独立异步面板</span></div><PanelState :loading="automation.isLoading.value" :error="automation.error.value as Error"><div class="two-col"><div class="subpanel"><h3>跟单分析</h3><div class="metric-grid"><div><span>订单</span><b>{{ automation.data.value?.copy?.orders ?? 0 }}</b></div><div><span>订单占比</span><b>{{ percent(automation.data.value?.copy?.orderRatio) }}</b></div><div><span>净盈亏</span><b>{{ money(automation.data.value?.copy?.netProfit) }}</b></div></div></div><div class="subpanel"><h3>EA分析</h3><div class="metric-grid"><div><span>订单</span><b>{{ automation.data.value?.ea?.orders ?? 0 }}</b></div><div><span>订单占比</span><b>{{ percent(automation.data.value?.ea?.orderRatio) }}</b></div><div><span>净盈亏</span><b>{{ money(automation.data.value?.ea?.netProfit) }}</b></div></div></div></div></PanelState></section>

    <section class="panel"><div class="section-head"><h2>登录 IP 来源</h2><span>{{ ips.data.value?.records?.length || 0 }} 个历史IP</span></div><PanelState :loading="ips.isLoading.value" :error="ips.error.value as Error" :empty="!ips.data.value?.records?.length"><div class="ip-list"><article v-for="row in ips.data.value?.records || []" :key="`${row.platform}-${row.server}-${row.ip}`"><strong>{{ row.ip }}</strong><span>{{ row.platform }} / {{ row.server }}</span><span>{{ row.geo?.country || '-' }} · {{ row.geo?.region || '-' }} · {{ row.geo?.isp || '-' }}</span><small>最后观察 {{ row.lastSeenAt || '-' }}</small></article></div></PanelState></section>
    <section class="panel"><div class="section-head"><h2>交易图表</h2><span>{{ detail.data.value?.charts?.length || 0 }} 个</span></div><div class="chart-list"><a v-for="chart in detail.data.value?.charts || []" :key="chart.name" :href="chart.url" target="_blank">{{ chart.name }}</a><span v-if="!detail.data.value?.charts?.length">开发产物目录暂无图表；旧图表可在 8866 最近图表查看。</span></div></section>
  </main>
</template>
