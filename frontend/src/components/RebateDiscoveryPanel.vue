<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { api } from '../api'
import RebateTreeNode from './RebateTreeNode.vue'

const environmentOptions = [
  { value: 'gb', label: 'AC GB' }, { value: 'cn', label: 'AC CN' },
  { value: 'dbg_cn', label: 'DBG CN' }, { value: 'dbg_vn', label: 'DBG VN' },
]
const form = reactive({ start: localDate(-7), end: localDate(0), environments: environmentOptions.map(item => item.value), level: 'warning' })
const job = ref<any>(null)
const detail = ref<any>(null)
const detailBusy = ref(false)
const detailError = ref('')
const hideInactiveNodes = ref(false)
let timer = 0

function localDate(offset: number): string {
  const date = new Date(Date.now() + offset * 86400000)
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}
function number(value: unknown, digits = 1): string { return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) }
function levelRank(value: string): number { return ({ '低风险': 0, '预警': 1, '高危': 2, '严重': 3 } as Record<string, number>)[value] ?? 0 }
const rows = computed(() => {
  const all = job.value?.result?.allResults || job.value?.result?.results || []
  const minimum = ({ all: 0, warning: 1, high: 2, severe: 3 } as Record<string, number>)[form.level] ?? 1
  return all.filter((row: any) => levelRank(row.level) >= minimum)
})
function jobMessage(): string {
  if (!job.value) return '尚未运行'
  const events = job.value.events || []
  return events.length ? events[events.length - 1].message : job.value.error || ({ queued: '已提交，等待扫描', running: '正在扫描', done: '扫描完成', failed: '扫描失败', cancelled: '已取消' } as any)[job.value.status] || ''
}
async function poll(id: string): Promise<void> {
  try {
    job.value = await api<any>(`/api/rebate-churning/scans/${encodeURIComponent(id)}`)
    localStorage.setItem('kdesk.rebateScanJobId', id)
    if (!['done', 'failed', 'cancelled'].includes(job.value.status)) timer = window.setTimeout(() => poll(id), 1400)
  } catch (error: any) { job.value = { status: 'failed', error: error.message || '读取刷返佣任务失败' } }
}
async function start(): Promise<void> {
  detail.value = null
  if (!form.start || !form.end) { job.value = { status: 'failed', error: '请选择开始和结束时间' }; return }
  if (!form.environments.length) { job.value = { status: 'failed', error: '请至少选择一个环境' }; return }
  job.value = { status: 'queued', progress: 0 }
  try {
    const response = await api<any>('/api/rebate-churning/scans', { method: 'POST', body: JSON.stringify({ start: form.start, end: form.end, environments: form.environments }) })
    job.value = response.job
    await poll(response.job.id)
  } catch (error: any) { job.value = { status: 'failed', error: error.message || '提交刷返佣扫描失败' } }
}
async function cancel(): Promise<void> {
  if (!job.value?.id) return
  job.value = await api<any>(`/api/jobs/${encodeURIComponent(job.value.id)}/cancel`, { method: 'POST' })
}
async function loadTree(row: any): Promise<void> {
  detailBusy.value = true; detailError.value = ''; detail.value = null
  const params = new URLSearchParams({ start: form.start, end: form.end })
  try { detail.value = await api<any>(`/api/rebate-churning/ibs/${encodeURIComponent(row.environment)}/${encodeURIComponent(row.ibId)}?${params}`) }
  catch (error: any) { detailError.value = error.message || 'IB树读取失败' }
  finally { detailBusy.value = false }
}
function setAll(open: boolean): void { document.querySelectorAll('.rebate-discovery-tree details').forEach(node => { (node as HTMLDetailsElement).open = open }) }
function xml(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[character] || character) }
function exportTree(): void {
  if (!detail.value?.tree) return
  const rows: Array<{ depth: number; title: string; subtitle: string }> = []
  const append = (node: any, depth: number) => {
    const finance = node.financials || {}
    rows.push({ depth, title: `${node.relationship || (node.type === 'ib' ? 'IB' : '客户')} · ${node.name || '-'}`, subtitle: `CRM ${node.userId} · 账户 ${number(finance.accounts, 0)} · 订单 ${number(finance.orders, 0)} · 手数 ${number(finance.lots, 2)} · 交易盈亏 ${number(finance.tradeProfit, 2)} · 实收返佣 ${number(finance.currentIbRebate, 2)} · 层级返佣 ${number(finance.hierarchyRebate, 2)}` })
    for (const account of node.accounts || []) rows.push({ depth: depth + 1, title: `交易账户 · ${account.account}`, subtitle: `${account.server || account.platform || '-'} · 订单 ${number(account.orders, 0)} · 手数 ${number(account.lots, 2)} · 交易盈亏 ${number(account.tradeProfit, 2)} · 当前IB返佣 ${number(account.currentIbRebate, 2)} · 层级返佣 ${number(account.hierarchyRebate, 2)}` })
    for (const child of node.children || []) append(child, depth + 1)
  }
  append(detail.value.tree, 0)
  const width = 1500, height = 90 + rows.length * 78
  const cards = rows.map((row, index) => { const x = 30 + row.depth * 42, y = 72 + index * 78; return `<rect x="${x}" y="${y}" width="${width - x - 24}" height="64" rx="6" fill="#071b31" stroke="#245678"/><text x="${x + 16}" y="${y + 25}" fill="#e2edf6" font-size="16" font-weight="700">${xml(row.title)}</text><text x="${x + 16}" y="${y + 47}" fill="#7895ad" font-size="12">${xml(row.subtitle)}</text>` }).join('')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#041222"/><text x="30" y="38" fill="#e2edf6" font-family="Microsoft YaHei,Segoe UI,sans-serif" font-size="22" font-weight="700">IB返佣关系树 · CRM ${xml(detail.value.ib?.id)}</text><g font-family="Microsoft YaHei,Segoe UI,sans-serif">${cards}</g></svg>`
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' })), anchor = document.createElement('a')
  anchor.href = url; anchor.download = `IB返佣关系树_${detail.value.ib?.id}_${new Date().toISOString().slice(0, 10)}.svg`; anchor.click(); URL.revokeObjectURL(url)
}
const savedJobId = localStorage.getItem('kdesk.rebateScanJobId')
if (savedJobId) poll(savedJobId)
onBeforeUnmount(() => { if (timer) window.clearTimeout(timer) })
</script>

<template>
  <div class="rebate-discovery">
    <div class="rebate-scan-controls"><label>开始时间<input v-model="form.start" type="datetime-local"></label><label>结束时间<input v-model="form.end" type="datetime-local"></label><fieldset><legend>环境</legend><label v-for="item in environmentOptions" :key="item.value"><input v-model="form.environments" type="checkbox" :value="item.value">{{ item.label }}</label></fieldset><label>榜单等级<select v-model="form.level"><option value="warning">预警及以上</option><option value="high">高危及以上</option><option value="severe">仅严重</option><option value="all">全部</option></select></label><button class="primary" :disabled="job && ['queued','running'].includes(job.status)" @click="start">{{ job && ['queued','running'].includes(job.status) ? '扫描中…' : '开始刷返佣检测' }}</button><button v-if="job && ['queued','running'].includes(job.status)" @click="cancel">取消</button></div>
    <small class="tool-note">按返佣入账时间扫描，默认最近7天，最长31天。候选分页深检，不做全交易表秒级配对。</small>
    <div v-if="job" class="job-card"><div class="job-head"><b>{{ jobMessage() }}</b><span>{{ job.progress || 0 }}%</span></div><div class="progress"><i :style="{ width: `${job.progress || 0}%` }" /></div><div v-if="job.error" class="inline-error">{{ job.error }}</div></div>
    <div v-if="job?.result?.summary" class="rebate-scan-summary"><div><span>活跃收佣IB</span><b>{{ job.result.summary.activeIbs }}</b></div><div><span>返佣账户</span><b>{{ job.result.summary.rebateAccounts }}</b></div><div><span>深检账户</span><b>{{ job.result.summary.deepAccounts }}</b></div><div><span>预警</span><b>{{ job.result.summary.warnings }}</b></div><div><span>高危</span><b>{{ job.result.summary.highRisk }}</b></div><div><span>严重</span><b>{{ job.result.summary.severe }}</b></div><div><span>失败</span><b>{{ job.result.summary.failures }}</b></div><div><span>耗时</span><b>{{ number(job.result.summary.elapsedSeconds, 1) }}秒</b></div></div>
    <div v-if="rows.length" class="table-wrap rebate-ranking"><table><thead><tr><th>评分</th><th>收佣IB</th><th>环境</th><th>账户 / 可疑客户</th><th>订单 / 手数</th><th>交易盈亏</th><th>IB实收返佣</th><th>返佣 / 亏损</th><th>主要证据</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="`${row.environment}-${row.ibId}`"><td><b>{{ number(row.score, 1) }}</b><small class="cell-sub">{{ row.level }} · {{ row.confidence }}置信度</small></td><td>{{ row.ibName }}<small class="cell-sub">CRM {{ row.ibId }}</small></td><td>{{ row.environment }}</td><td>{{ row.summary?.accounts || 0 }} / {{ row.summary?.suspiciousCustomers || 0 }}</td><td>{{ row.summary?.orders || 0 }} / {{ number(row.summary?.lots, 2) }}</td><td :class="Number(row.summary?.tradeProfit) < 0 ? 'negative' : 'positive'">{{ number(row.summary?.tradeProfit, 2) }}</td><td>{{ number(row.summary?.currentIbRebate, 2) }}</td><td>{{ row.summary?.rebateLossCoverage == null ? '-' : `${number(Number(row.summary.rebateLossCoverage) * 100, 1)}%` }}</td><td class="note-cell" :title="(row.evidenceTags || []).join(' · ')">{{ (row.evidenceTags || []).join(' · ') || '-' }}</td><td><button @click="loadTree(row)">查看树</button></td></tr></tbody></table></div>
    <div v-if="job?.result?.failures?.length" class="push-failure-section"><div class="push-result-subhead"><h3>部分失败（{{ job.result.failureTotal }}）</h3><span>成功环境与IB结果已保留</span></div><div class="table-wrap"><table><thead><tr><th>阶段</th><th>环境</th><th>IB</th><th>原因</th></tr></thead><tbody><tr v-for="(failure,index) in job.result.failures" :key="index"><td>{{ failure.stage }}</td><td>{{ failure.environment }}</td><td>{{ failure.ibId || '-' }}</td><td>{{ failure.reason }}</td></tr></tbody></table></div></div>
    <div v-if="detailBusy" class="panel-state"><span class="spinner" />正在加载完整IB客户树</div><div v-if="detailError" class="panel-state error">{{ detailError }}</div>
    <div v-if="detail" class="rebate-discovery-tree"><div class="rebate-tree-head"><div><h3>{{ detail.ib?.name }} · CRM {{ detail.ib?.id }}</h3><small>{{ detail.period?.start }} 至 {{ detail.period?.end }}</small></div><div><button @click="hideInactiveNodes=!hideInactiveNodes">{{ hideInactiveNodes ? '显示空节点' : '隐藏空节点' }}</button><button @click="exportTree">导出树形图</button><button @click="setAll(true)">全部展开</button><button @click="setAll(false)">全部收起</button></div></div><RebateTreeNode :node="detail.tree" target-account="" :hide-inactive="hideInactiveNodes" /></div>
  </div>
</template>
