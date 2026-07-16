<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, queryString } from '../api'
import PanelState from '../components/PanelState.vue'

const router = useRouter()
const queryClient = useQueryClient()
const accountInput = ref('')
const listSearch = ref('')
const actionFilter = ref('')
const statusFilter = ref('')
const lookupBusy = ref(false)
const lookupError = ref('')
const statusSaving = ref('')
const tools = reactive({ logs: true, hierarchy: true })
const logsForm = reactive({ account: '', start: localDate(-1), end: localDate(0) })
const logsResult = ref<any>(null)
const logsBusy = ref(false)
const logsError = ref('')
const pushForm = reactive({ days: 7, maxOrders: 200 })
const pushJob = ref<any>(null)
let pushTimer = 0
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

async function openAccount(login = accountInput.value.trim()) {
  if (!login) return
  lookupBusy.value = true
  lookupError.value = ''
  try {
    const result = await api<any>(`/api/account-lookup?account=${encodeURIComponent(login)}`)
    if (!result.database?.exists) throw new Error('未在交易库或本地台账中找到该账号')
    const source = result.database.latestSource || {}
    await router.push({ path: `/account/${encodeURIComponent(login)}`, query: { ...(source.platform ? { platform: source.platform } : {}), ...(source.server ? { server: source.server } : {}) } })
  } catch (error: any) {
    lookupError.value = error.message || '账号查询失败'
  } finally {
    lookupBusy.value = false
  }
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

function pushJobMessage(): string {
  const job = pushJob.value
  if (!job) return '尚未运行'
  if (job.events?.length) return job.events[job.events.length - 1].message
  return job.error || ({ queued: '已提交，等待扫描', running: '正在扫描', done: '扫描完成', failed: '扫描失败', cancelled: '已取消' } as any)[job.status] || ''
}

async function pollPushDiscovery(id: string) {
  try {
    pushJob.value = await api<any>(`/api/push-discovery/jobs/${encodeURIComponent(id)}`)
    if (!['done', 'failed', 'cancelled'].includes(pushJob.value.status)) {
      pushTimer = window.setTimeout(() => pollPushDiscovery(id), 1200)
    }
  } catch (error: any) {
    pushJob.value = { status: 'failed', error: error.message || '读取扫描任务失败' }
  }
}

async function startPushDiscovery() {
  pushJob.value = { status: 'queued', progress: 0 }
  try {
    const result = await api<any>('/api/push-discovery/start', { method: 'POST', body: JSON.stringify(pushForm) })
    pushJob.value = result.job
    await pollPushDiscovery(result.job.id)
  } catch (error: any) {
    pushJob.value = { status: 'failed', error: error.message || '提交扫描失败' }
  }
}

async function cancelPushDiscovery() {
  if (!pushJob.value?.id) return
  pushJob.value = await api<any>(`/api/jobs/${encodeURIComponent(pushJob.value.id)}/cancel`, { method: 'POST' })
}

onBeforeUnmount(() => { if (pushTimer) window.clearTimeout(pushTimer) })
</script>

<template>
  <header class="topbar legacy-topbar">
    <div><b>账号风控台账</b><span>模块化开发环境 · 8877</span></div>
    <nav><a href="/download/problematic_accounts.xlsx">导出台账</a><a href="/?legacy=1">旧版工作台</a></nav>
  </header>
  <main class="workbench dense-page">
    <section class="hero compact-hero">
      <div><div class="eyebrow">ACCOUNT RISK WORKBENCH</div><h1>账号查询</h1><p>数据库订单与本地台账记录 · 生产服务不受影响</p></div>
      <div class="lookup-block">
        <div class="lookup"><input v-model="accountInput" aria-label="账号查询" placeholder="输入交易账号" @keyup.enter="openAccount()"><button :disabled="lookupBusy" @click="openAccount()">{{ lookupBusy ? '查询中…' : '查询' }}</button></div>
        <small v-if="lookupError" class="inline-error">{{ lookupError }}</small>
      </div>
    </section>

    <section class="summary-grid four-summary">
      <article><span>台账记录</span><strong>{{ query.data.value?.summary?.total ?? '-' }}</strong></article>
      <article><span>当前筛选</span><strong>{{ records.length }}</strong></article>
      <article><span>今日更新</span><strong>{{ todayCount }}</strong></article>
      <article><span>服务状态</span><strong class="positive">DEV READY</strong></article>
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
      <div class="section-head"><div><h2>全平台推盘发现</h2><small>只读 · 近期开仓结构初筛 → Tick / 协同深检 · 持久化任务</small></div><span>{{ pushJobMessage() }}</span></div>
      <div class="filter-row tool-form"><label>盈利窗口（天）<input v-model.number="pushForm.days" type="number" min="1" max="30"></label><label>近期开平仓订单上限<input v-model.number="pushForm.maxOrders" type="number" min="20" max="1000"></label><button class="primary" :disabled="pushJob && ['queued','running'].includes(pushJob.status)" @click="startPushDiscovery">{{ pushJob && ['queued','running'].includes(pushJob.status) ? '检测中…' : '开始全平台检测' }}</button><button v-if="pushJob && ['queued','running'].includes(pushJob.status)" @click="cancelPushDiscovery">取消</button></div>
      <p class="tool-note">自动排除数据库已处置状态和本地 T / TA / A 类账号；扫描产物只写入 v2 开发运行目录。</p>
      <div v-if="pushJob" class="job-card"><div class="job-head"><b>{{ pushJobMessage() }}</b><span>{{ pushJob.progress || 0 }}%</span></div><div class="progress"><i :style="{width:`${pushJob.progress || 0}%`}" /></div><div v-if="pushJob.error" class="inline-error">{{ pushJob.error }}</div></div>
      <div v-if="pushJob?.result?.results?.length" class="table-wrap push-results"><table><thead><tr><th>排名</th><th>账号</th><th>平台 / 服务器</th><th>近期开平仓单</th><th>初筛分</th><th>深检分</th><th>等级</th><th>Tick</th><th>协同开仓</th><th>结论</th></tr></thead><tbody><tr v-for="row in pushJob.result.results" :key="`${row.platform}-${row.server}-${row.account}`"><td>{{ row.deepRank }}</td><td><RouterLink :to="`/account/${row.account}?platform=${row.platform}&server=${encodeURIComponent(row.server)}`">{{ row.account }}</RouterLink></td><td>{{ row.platform }} / {{ row.server }}</td><td>{{ row.orders }}</td><td>{{ row.initialScore }}</td><td :class="Number(row.deepScore)>=60 ? 'negative' : ''">{{ row.deepScore }}</td><td>{{ row.level || '-' }}</td><td>{{ row.tickAvailable ? '可用' : '无' }}</td><td>{{ row.coordinatedMatchedRatio }}%</td><td class="note-cell" :title="row.headline">{{ row.headline || '-' }}</td></tr></tbody></table></div>
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
          <tbody><tr v-for="row in records" :key="row['记录ID']"><td><RouterLink :to="`/account/${encodeURIComponent(row['账号'])}`">{{ row['账号'] || '-' }}</RouterLink></td><td><span class="action-badge">{{ row['建议动作'] || '-' }}</span></td><td>{{ row['当前分组'] || '-' }}</td><td>{{ row['风险标签'] || '-' }}</td><td class="note-cell" :title="row['风险/问题备注']">{{ row['风险/问题备注'] || '-' }}</td><td><select class="inline-select" :disabled="statusSaving===row['记录ID']" :value="row['状态']" :aria-label="`修改 ${row['账号']} 的状态`" @change="updateStatus(row, ($event.target as HTMLSelectElement).value)"><option v-for="item in ['待复核','观察中','已确认','已关闭']" :key="item">{{ item }}</option></select></td><td>{{ row['修改时间'] || '-' }}</td></tr></tbody>
        </table></div>
      </PanelState>
    </section>
  </main>
</template>
