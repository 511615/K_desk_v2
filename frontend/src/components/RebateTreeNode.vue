<script setup lang="ts">
defineOptions({ name: 'RebateTreeNode' })

defineProps<{
  node: any
  targetAccount: string
}>()

function number(value: unknown, digits = 1): string {
  const parsed = Number(value || 0)
  return parsed.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function money(value: unknown): string {
  return number(value, 2)
}

function percent(value: unknown): string {
  return `${number(Number(value || 0) * 100, 1)}%`
}

function valueClass(value: unknown): string {
  return Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : ''
}

function riskClass(level: string): string {
  return level === '严重' ? 'severe' : level === '高危' ? 'high' : level === '预警' ? 'warning' : ''
}

function accountHref(account: any): string {
  const params = new URLSearchParams()
  if (account.platform) params.set('platform', account.platform)
  if (account.server) params.set('server', account.server)
  return `/account/${encodeURIComponent(String(account.account || ''))}?${params}`
}

function financialItems(node: any): Array<[string, string, string?]> {
  const item = node.financials || {}
  if (node.type === 'ib') {
    return [
      ['下属账户', number(item.accounts, 0)],
      ['区间订单', number(item.orders, 0)],
      ['区间手数', number(item.lots, 2)],
      ['下属交易盈亏', money(item.tradeProfit), valueClass(item.tradeProfit)],
      ['IB实收返佣', money(item.currentIbRebate)],
      ['IB口径综合收益', money(item.combinedProfit), valueClass(item.combinedProfit)],
      ['下属产生层级返佣', money(item.hierarchyRebate)],
    ]
  }
  return [
    ['账户数', number(item.accounts, 0)],
    ['区间订单', number(item.orders, 0)],
    ['区间手数', number(item.lots, 2)],
    ['客户交易盈亏', money(item.tradeProfit), valueClass(item.tradeProfit)],
    ['产生层级返佣', money(item.hierarchyRebate)],
    ['外部净入金', money(item.externalNetDeposit), valueClass(item.externalNetDeposit)],
  ]
}
</script>

<template>
  <details class="rebate-tree-node" open>
    <summary class="rebate-node-summary">
      <div class="rebate-node-heading">
        <span class="relation">{{ node.relationship || node.type }}</span>
        <span class="node-name"><b>{{ node.name || '-' }}</b><small>CRM {{ node.userId }}<template v-if="node.ibLevel !== null && node.ibLevel !== undefined"> · IB L{{ node.ibLevel }}</template></small></span>
        <template v-if="node.risk">
          <span class="risk-pill" :class="riskClass(node.risk.level)">{{ node.risk.level }}</span>
          <strong>{{ number(node.risk.score, 1) }}分</strong>
        </template>
      </div>
      <div class="rebate-finance-grid rebate-finance-summary">
        <div v-for="item in financialItems(node)" :key="item[0]"><span>{{ item[0] }}</span><b :class="item[2] || ''">{{ item[1] }}</b></div>
      </div>
    </summary>
    <div class="rebate-node-body">
      <template v-if="node.risk">
        <div class="rebate-risk-grid">
          <div><span>结构分</span><b>{{ number(node.risk.components?.structure, 1) }}</b></div>
          <div><span>返佣经济性</span><b>{{ number(node.risk.components?.rebateEconomics, 1) }}</b></div>
          <div><span>IB协同</span><b>{{ number(node.risk.components?.ibCoordination, 1) }}</b></div>
          <div><span>资金闭环</span><b>{{ number(node.risk.components?.fundingCycle, 1) }}</b></div>
          <div><span>反证扣分</span><b>{{ number(node.risk.components?.counterevidence, 1) }}</b></div>
          <div><span>可疑账户</span><b>{{ number(node.risk.summary?.suspiciousAccounts, 0) }} / {{ number(node.risk.summary?.accounts, 0) }}</b></div>
        </div>
        <div class="rebate-tags"><span v-for="tag in node.risk.evidenceTags || []" :key="tag">{{ tag }}</span></div>
      </template>

      <div v-if="node.accounts?.length" class="rebate-account-list">
        <details v-for="account in node.accounts" :key="`${account.serverCode}-${account.account}`" class="rebate-account" :class="{ target: String(account.account) === targetAccount }" :open="String(account.account) === targetAccount">
          <summary>
            <span v-if="String(account.account) === targetAccount" class="target-flag">目标账户</span>
            <span v-if="account.isHistorical" class="relation">历史账户</span>
            <span class="account-name"><a :href="accountHref(account)">{{ account.account }}</a><small>{{ account.server || account.platform || '-' }} · {{ account.typeName || '-' }}</small></span>
            <span class="account-facts">{{ number(account.orders, 0) }}单 · {{ number(account.lots, 2) }}手 · 贡献 {{ number(account.riskContribution, 1) }}分</span>
          </summary>
          <div class="rebate-account-grid">
            <div><span>区间交易盈亏</span><b :class="valueClass(account.tradeProfit)">{{ money(account.tradeProfit) }}</b></div>
            <div><span>贡献当前IB返佣</span><b>{{ money(account.currentIbRebate) }}</b></div>
            <div><span>IB口径综合收益</span><b :class="valueClass(Number(account.tradeProfit || 0) + Number(account.currentIbRebate || 0))">{{ money(Number(account.tradeProfit || 0) + Number(account.currentIbRebate || 0)) }}</b></div>
            <div><span>产生层级返佣</span><b>{{ money(account.hierarchyRebate) }}</b></div>
            <div><span>配对覆盖</span><b>{{ percent(account.pairCoverage) }}</b></div>
            <div><span>同秒覆盖</span><b>{{ percent(account.sameSecondCoverage) }}</b></div>
            <div><span>10秒覆盖</span><b>{{ percent(account.short10Coverage) }}</b></div>
            <div><span>订单/活跃日</span><b>{{ number(account.ordersPerActiveDay, 1) }}</b></div>
            <div><span>外部净入金</span><b :class="valueClass(account.externalNetDeposit)">{{ money(account.externalNetDeposit) }}</b></div>
          </div>
          <div class="rebate-tags"><span v-for="tag in account.evidenceTags || []" :key="tag">{{ tag }}</span></div>
        </details>
      </div>

      <RebateTreeNode v-for="child in node.children || []" :key="child.userId" :node="child" :target-account="targetAccount" />
    </div>
  </details>
</template>

<style scoped>
.rebate-tree-node { margin: 7px 0 7px 18px; border-left: 2px solid #1b5279; padding-left: 12px }
.rebate-tree-node:first-child { margin-left: 0 }
.rebate-node-summary, .rebate-account>summary { cursor: pointer; list-style: none }
.rebate-node-summary { position: relative; display: block; border: 1px solid #17466d; background: #061b31 }
.rebate-account>summary { display: flex; align-items: center; gap: 9px; min-height: 48px; padding: 8px 10px; border: 1px solid #17466d; background: #061b31 }
.rebate-node-summary::-webkit-details-marker, .rebate-account>summary::-webkit-details-marker { display: none }
.rebate-node-summary::before, .rebate-account>summary::before { content: '▸'; color: #7294ad }
.rebate-node-summary::before { position: absolute; z-index: 1; top: 24px; left: 10px; transform: translateY(-50%) }
.rebate-account>summary::before { width: 13px }
details[open]>.rebate-node-summary::before, .rebate-account[open]>summary::before { content: '▾' }
.rebate-node-heading { display: flex; align-items: center; gap: 9px; min-height: 48px; padding: 8px 10px 8px 30px }
.relation, .target-flag, .risk-pill { padding: 3px 7px; border: 1px solid #256a8c; border-radius: 4px; color: #76d9f3; background: #0a314c; font-size: 10px; font-weight: 700 }
.target-flag { color: #fff; background: #137fc0 }
.risk-pill { color: #a9bdd0; border-color: #45647b; background: #10273a }
.risk-pill.warning { color: #ffd27b; border-color: #926b23; background: #38290e }
.risk-pill.high { color: #ffb073; border-color: #a34e22; background: #3b1d10 }
.risk-pill.severe { color: #ff8d99; border-color: #a63c4b; background: #3d1720 }
.node-name, .account-name { min-width: 180px; flex: 1 }
.node-name b, .node-name small, .account-name a, .account-name small { display: block }
.node-name small, .account-name small, .account-facts { margin-top: 3px; color: #7895ad; font-size: 10px }
.account-name a { color: #76d9f3; font-weight: 800 }
.rebate-node-body { padding: 0 0 5px 11px }
.rebate-finance-grid, .rebate-risk-grid, .rebate-account-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(125px, 1fr)); border: 1px solid #163e5d; border-top: 0; background: #07172a }
.rebate-finance-summary { border-right: 0; border-bottom: 0; border-left: 0; background: #071a2e }
.rebate-finance-grid>div, .rebate-risk-grid>div, .rebate-account-grid>div { padding: 9px 10px; border-right: 1px solid #163e5d }
.rebate-finance-grid span, .rebate-risk-grid span, .rebate-account-grid span { display: block; color: #718da5; font-size: 10px }
.rebate-finance-grid b, .rebate-risk-grid b, .rebate-account-grid b { display: block; margin-top: 4px; font-size: 12px }
.rebate-tags { display: flex; flex-wrap: wrap; gap: 5px; padding: 7px 0 }
.rebate-tags span { padding: 2px 6px; border-radius: 4px; color: #7ddac2; background: #0b342d; font-size: 10px }
.rebate-account-list { margin: 7px 0 }
.rebate-account { margin: 6px 0; border-left: 3px solid #49677e }
.rebate-account.target { border-left-color: #17b9f4 }
.positive { color: #4bd29a !important }
.negative { color: #ff7885 !important }
@media (max-width: 900px) {
  .rebate-tree-node { margin-left: 8px; padding-left: 7px }
  .rebate-node-heading, .rebate-account>summary { align-items: flex-start; flex-wrap: wrap }
  .rebate-finance-summary { grid-template-columns: repeat(3, minmax(125px, 1fr)) }
  .rebate-account-grid { grid-template-columns: repeat(2, minmax(125px, 1fr)) }
}
</style>
