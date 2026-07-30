export type RebateRiskLevel = '' | '低风险' | '预警' | '高危' | '严重'

const rank: Record<RebateRiskLevel, number> = { '': 0, '低风险': 0, '预警': 1, '高危': 2, '严重': 3 }

export function accountRiskLevel(account: any): RebateRiskLevel {
  const contribution = Number(account?.riskContribution || 0)
  if (contribution >= 40) return '严重'
  if (contribution >= 30) return '高危'
  if (contribution >= 20) return '预警'
  return ''
}

export function nodeRiskLevel(node: any): RebateRiskLevel {
  let level = (node?.risk?.level || '') as RebateRiskLevel
  for (const account of node?.accounts || []) {
    const accountLevel = accountRiskLevel(account)
    if (rank[accountLevel] > rank[level]) level = accountLevel
  }
  for (const child of node?.children || []) {
    const childLevel = nodeRiskLevel(child)
    if (rank[childLevel] > rank[level]) level = childLevel
  }
  return level
}

export function riskClass(level: RebateRiskLevel): string {
  return level === '严重' ? 'severe' : level === '高危' ? 'high' : level === '预警' ? 'warning' : ''
}

export function accountHasRebateActivity(account: any): boolean {
  return Number(account?.orders || 0) > 0 || Number(account?.riskContribution || 0) > 0
}

export function hasVisibleRebateActivity(node: any): boolean {
  const financials = node?.financials || {}
  const hasFinancialActivity = [
    'orders',
    'lots',
    'tradeProfit',
    'currentIbRebate',
    'combinedProfit',
    'hierarchyRebate',
    'externalNetDeposit',
  ].some(key => Math.abs(Number(financials[key] || 0)) > 0)
  return hasFinancialActivity
    || (node?.accounts || []).some(accountHasRebateActivity)
    || (node?.children || []).some(hasVisibleRebateActivity)
}

export function hasAccountOrTrade(node: any): boolean {
  return hasVisibleRebateActivity(node)
}

export function hasExcessiveHierarchyRebate(node: any): boolean {
  if (node?.type !== 'customer') return false
  const financials = node?.financials || {}
  const hierarchyRebate = Number(financials.hierarchyRebate || 0)
  return hierarchyRebate > 0 && Number(financials.tradeProfit || 0) + hierarchyRebate > 0
}
