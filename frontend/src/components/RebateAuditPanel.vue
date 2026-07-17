<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api, ApiError } from '../api'
import RebateTreeNode from './RebateTreeNode.vue'

const props = defineProps<{ initialAccount?: string }>()

const form = reactive({ account: '', fullHistory: true, start: '', end: '', environment: '' })
const customRange = reactive({ start: localDate(-30), end: localDate(0) })
const result = ref<any>(null)
const candidates = ref<any[]>([])
const selectedCandidate = ref(0)
const busy = ref(false)
const error = ref('')
const panel = ref<HTMLElement | null>(null)

watch(() => props.initialAccount, value => {
  if (value?.trim()) form.account = value.trim()
}, { immediate: true })

function localDate(offsetDays: number): string {
  const date = new Date(Date.now() + offsetDays * 86400000)
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

function syncRange(): void {
  if (form.fullHistory) {
    if (form.start) customRange.start = form.start
    if (form.end) customRange.end = form.end
    form.start = ''
    form.end = ''
  } else {
    form.start = customRange.start
    form.end = customRange.end
  }
}

function number(value: unknown, digits = 1): string {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function riskClass(level: string): string {
  return level === '严重' ? 'severe' : level === '高危' ? 'high' : level === '预警' ? 'warning' : ''
}

async function query(candidate: any = null): Promise<void> {
  const account = form.account.trim()
  if (!account) { error.value = '请输入交易账户'; return }
  if (!form.fullHistory && (!form.start || !form.end)) { error.value = '请选择开始和结束时间'; return }
  busy.value = true
  error.value = ''
  result.value = null
  candidates.value = []
  const params = new URLSearchParams()
  if (!form.fullHistory) {
    params.set('start', form.start)
    params.set('end', form.end)
  }
  const environment = candidate?.environment ?? form.environment
  if (environment) params.set('environment', environment)
  if (candidate?.serverCode) params.set('serverCode', candidate.serverCode)
  try {
    result.value = await api<any>(`/api/rebate-churning/accounts/${encodeURIComponent(account)}?${params}`)
  } catch (caught: any) {
    error.value = caught.message || '账户刷返佣审计失败'
    if (caught instanceof ApiError && Array.isArray(caught.payload.candidates)) candidates.value = caught.payload.candidates
  } finally {
    busy.value = false
  }
}

function useCandidate(): void {
  const candidate = candidates.value[selectedCandidate.value]
  if (candidate) query(candidate)
}

function setAll(open: boolean): void {
  panel.value?.querySelectorAll('details').forEach(node => { node.open = open })
}

function exportFinancialItems(node: any): Array<[string, string]> {
  const financials = node.financials || {}
  if (node.type === 'ib') {
    return [
      ['下属账户', number(financials.accounts, 0)],
      ['区间订单', number(financials.orders, 0)],
      ['区间手数', number(financials.lots, 2)],
      ['下属交易盈亏', number(financials.tradeProfit, 2)],
      ['IB实收返佣', number(financials.currentIbRebate, 2)],
      ['IB口径综合收益', number(financials.combinedProfit, 2)],
      ['下属产生层级返佣', number(financials.hierarchyRebate, 2)],
    ]
  }
  return [
    ['账户数', number(financials.accounts, 0)],
    ['区间订单', number(financials.orders, 0)],
    ['区间手数', number(financials.lots, 2)],
    ['客户交易盈亏', number(financials.tradeProfit, 2)],
    ['产生层级返佣', number(financials.hierarchyRebate, 2)],
    ['外部净入金', number(financials.externalNetDeposit, 2)],
  ]
}

function exportAccountItems(account: any): Array<[string, string]> {
  return [
    ['区间订单', number(account.orders, 0)],
    ['区间手数', number(account.lots, 2)],
    ['区间交易盈亏', number(account.tradeProfit, 2)],
    ['当前IB返佣', number(account.currentIbRebate, 2)],
    ['IB口径综合收益', number(Number(account.tradeProfit || 0) + Number(account.currentIbRebate || 0), 2)],
    ['产生层级返佣', number(account.hierarchyRebate, 2)],
    ['外部净入金', number(account.externalNetDeposit, 2)],
  ]
}

function xml(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[character] || character)
}

function exportTree(): void {
  if (!result.value?.tree) return
  const rows: Array<{ depth: number; parent: number | null; type: string; title: string; subtitle: string; metrics: Array<[string, string]> }> = []
  const appendNode = (node: any, depth: number, parent: number | null) => {
    const nodeIndex = rows.length
    rows.push({
      depth,
      parent,
      type: node.type,
      title: `${node.relationship || (node.type === 'ib' ? 'IB' : '客户')} · ${node.name || '-'}`,
      subtitle: `CRM ${node.userId}${node.ibLevel !== null && node.ibLevel !== undefined ? ` · IB L${node.ibLevel}` : ''}`,
      metrics: exportFinancialItems(node),
    })
    for (const account of node.accounts || []) {
      rows.push({
        depth: depth + 1,
        parent: nodeIndex,
        type: 'account',
        title: `${String(account.account) === String(result.value.account?.account) ? '目标账户' : account.isHistorical ? '历史账户' : '交易账户'} · ${account.account}`,
        subtitle: `${account.server || account.platform || '-'} · ${account.typeName || '-'}`,
        metrics: exportAccountItems(account),
      })
    }
    for (const child of node.children || []) appendNode(child, depth + 1, nodeIndex)
  }
  appendNode(result.value.tree, 0, null)

  const rowHeight = 92
  const cardHeight = 78
  const headerHeight = 92
  const maxDepth = Math.max(0, ...rows.map(row => row.depth))
  const maxMetrics = Math.max(1, ...rows.map(row => row.metrics.length))
  const width = Math.max(1500, 530 + maxDepth * 52 + maxMetrics * 155)
  const height = headerHeight + rows.length * rowHeight + 28
  const positions = rows.map((row, index) => ({ x: 36 + row.depth * 52, y: headerHeight + index * rowHeight }))
  const connectors = rows.map((row, index) => {
    if (row.parent === null) return ''
    const parent = positions[row.parent]
    const current = positions[index]
    const railX = current.x - 24
    return `<path d="M ${parent.x + 13} ${parent.y + cardHeight} V ${current.y + cardHeight / 2} H ${current.x}" fill="none" stroke="#2c668d" stroke-width="2"/>`
  }).join('')
  const cards = rows.map((row, index) => {
    const position = positions[index]
    const cardWidth = width - position.x - 28
    const metricStart = position.x + 320
    const metricWidth = Math.max(105, (cardWidth - 330) / row.metrics.length)
    const accent = row.type === 'ib' ? '#22b5f3' : row.type === 'customer' ? '#43c7b0' : '#829db7'
    const metricText = row.metrics.map((metric, metricIndex) => {
      const metricX = metricStart + metricIndex * metricWidth
      return `<text x="${metricX}" y="${position.y + 27}" fill="#7895ad" font-size="12">${xml(metric[0])}</text><text x="${metricX}" y="${position.y + 53}" fill="#e2edf6" font-size="16" font-weight="700">${xml(metric[1])}</text>`
    }).join('')
    return `<rect x="${position.x}" y="${position.y}" width="${cardWidth}" height="${cardHeight}" rx="7" fill="#071b31" stroke="#245678"/><rect x="${position.x}" y="${position.y}" width="5" height="${cardHeight}" rx="2" fill="${accent}"/><text x="${position.x + 20}" y="${position.y + 30}" fill="#e2edf6" font-size="17" font-weight="700">${xml(row.title)}</text><text x="${position.x + 20}" y="${position.y + 55}" fill="#7895ad" font-size="12">${xml(row.subtitle)}</text>${metricText}`
  }).join('')
  const account = result.value.account || {}
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#041222"/><text x="36" y="34" fill="#e2edf6" font-family="Microsoft YaHei,Segoe UI,sans-serif" font-size="24" font-weight="700">IB刷返佣树形图 · 账户 ${xml(account.account)}</text><text x="36" y="62" fill="#7895ad" font-family="Microsoft YaHei,Segoe UI,sans-serif" font-size="13">${xml(account.environmentLabel)} · ${xml(account.server || '-')} · ${xml(result.value.query?.start)} 至 ${xml(result.value.query?.end)}</text><g font-family="Microsoft YaHei,Segoe UI,sans-serif">${connectors}${cards}</g></svg>`
  const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `IB返佣树形图_${account.account}_${new Date().toISOString().slice(0, 10)}.svg`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section id="rebateAuditPanel" ref="panel" class="panel tool-panel rebate-audit-panel">
    <div class="section-head"><div><h2>IB刷返佣树形审计</h2><small>只读 · 账户 → IB完整客户树</small></div><span v-if="result">{{ result.scope?.customers || 0 }}位客户 / {{ result.scope?.accounts || 0 }}个账户</span></div>
    <div class="rebate-query-grid">
      <label class="account-field">交易账户<input v-model="form.account" placeholder="输入MT4 / MT5账户" @keyup.enter="query()"></label>
      <label class="history-toggle"><input v-model="form.fullHistory" type="checkbox" @change="syncRange"><span>全历史</span></label>
      <label>开始时间<input v-model="form.start" type="datetime-local" :disabled="form.fullHistory"></label>
      <label>结束时间<input v-model="form.end" type="datetime-local" :disabled="form.fullHistory"></label>
      <label>环境<select v-model="form.environment"><option value="">自动识别</option><option value="gb">AC GB</option><option value="cn">AC CN</option><option value="dbg_cn">DBG CN</option><option value="dbg_vn">DBG VN</option></select></label>
      <button class="primary" :disabled="busy" @click="query()">{{ busy ? '查询中…' : '查询并判断' }}</button>
    </div>

    <div v-if="error" class="panel-state error">{{ error }}</div>
    <div v-if="candidates.length" class="rebate-candidates"><select v-model.number="selectedCandidate"><option v-for="(candidate,index) in candidates" :key="`${candidate.environment}-${candidate.serverCode}-${candidate.userId}`" :value="index">{{ candidate.environmentLabel }} · {{ candidate.server || `服务器${candidate.serverCode}` }} · {{ candidate.ownerName || `CRM ${candidate.userId}` }}</option></select><button @click="useCandidate">使用此账户</button></div>
    <div v-if="busy" class="panel-state"><span class="spinner" /> {{ form.fullHistory ? '正在读取全历史IB客户树和交易证据' : '正在读取所选区间IB客户树和交易证据' }}</div>

    <div v-if="result" class="rebate-result">
      <div class="rebate-result-head">
        <div><h3>账户 {{ result.account?.account }} · {{ result.assessment?.level }}</h3><small>{{ result.account?.environmentLabel }} · {{ result.account?.server || '-' }} · {{ result.query?.start }} 至 {{ result.query?.end }} · {{ result.assessment?.stage }} · 置信度{{ result.assessment?.confidence }}</small></div>
        <div class="rebate-tools"><button title="导出不含任何评分内容的SVG树形图" @click="exportTree">导出树形图</button><button title="展开全部节点" @click="setAll(true)">全部展开</button><button title="收起全部节点" @click="setAll(false)">全部收起</button></div>
      </div>
      <div class="rebate-summary">
        <div><span>总体评分</span><b>{{ number(result.assessment?.score, 1) }}分</b></div>
        <div><span>总体等级</span><b class="risk-text" :class="riskClass(result.assessment?.level)">{{ result.assessment?.level }}</b></div>
        <div><span>直属IB</span><b>CRM {{ result.assessment?.directIbId }}</b></div>
        <div><span>直属IB评分</span><b>{{ number(result.assessment?.directIbScore, 1) }}分</b></div>
        <div><span>最高风险IB</span><b>{{ result.assessment?.highestRiskIbName || '-' }} · {{ result.assessment?.highestRiskIbId }}</b></div>
        <div><span>所属客户</span><b>{{ result.account?.ownerName || result.account?.userId }}</b></div>
      </div>
      <div class="rebate-lineage"><template v-for="(node,index) in result.lineage || []" :key="node.userId"><span v-if="index">›</span><b>{{ node.type === 'ib' ? 'IB' : '客户' }} {{ node.name || node.userId }}</b></template></div>
      <div class="rebate-tree"><RebateTreeNode :node="result.tree" :target-account="String(result.account?.account || '')" /></div>
    </div>
  </section>
</template>

<style scoped>
.rebate-audit-panel { border-color: #13739a }
.rebate-query-grid { display: grid; grid-template-columns: minmax(220px, 1fr) 120px 190px 190px 150px 150px; gap: 9px; align-items: end }
.rebate-query-grid label { display: flex; flex-direction: column; gap: 5px; color: #7895ad; font-size: 11px }
.history-toggle { min-height: 38px; flex-direction: row !important; align-items: center; gap: 8px !important; padding: 8px 10px; border: 1px solid #1d5378; border-radius: 5px; background: #071a2e }
.history-toggle input { flex: 0 0 auto }
.rebate-query-grid input:disabled { opacity: .45 }
.rebate-candidates { display: grid; grid-template-columns: 1fr 130px; gap: 9px; margin-top: 10px; padding: 10px; border: 1px solid #1d5378; background: #071a2e }
.rebate-result { margin-top: 12px; border-top: 1px solid #1b4d70 }
.rebate-result-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; padding: 14px 0 }
.rebate-result-head h3 { margin: 0; font-size: 17px }
.rebate-result-head small { display: block; margin-top: 5px; color: #7895ad }
.rebate-tools { display: flex; gap: 7px }
.rebate-summary { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); border: 1px solid #17466d }
.rebate-summary>div { min-height: 70px; padding: 11px; border-right: 1px solid #17466d }
.rebate-summary>div:last-child { border-right: 0 }
.rebate-summary span, .rebate-summary b { display: block }
.rebate-summary span { color: #7895ad; font-size: 10px }
.rebate-summary b { margin-top: 5px; overflow-wrap: anywhere; font-size: 14px }
.risk-text.warning { color: #ffd27b }
.risk-text.high { color: #ffad70 }
.risk-text.severe { color: #ff7885 }
.rebate-lineage { display: flex; gap: 6px; flex-wrap: wrap; padding: 10px; border: 1px solid #17466d; border-top: 0; color: #8ea9bf; font-size: 11px }
.rebate-tree { padding-top: 10px }
@media (max-width: 1280px) {
  .rebate-query-grid { grid-template-columns: 1fr 120px 1fr 1fr }
  .rebate-query-grid label:nth-of-type(5), .rebate-query-grid button { grid-column: span 2 }
  .rebate-summary { grid-template-columns: repeat(3, 1fr) }
}
@media (max-width: 900px) {
  .rebate-query-grid { grid-template-columns: 1fr 1fr }
  .account-field { grid-column: 1 / -1 }
  .rebate-query-grid label:nth-of-type(5), .rebate-query-grid button { grid-column: auto }
  .rebate-result-head { display: block }
  .rebate-tools { margin-top: 10px }
  .rebate-summary { grid-template-columns: repeat(2, 1fr) }
}
</style>
