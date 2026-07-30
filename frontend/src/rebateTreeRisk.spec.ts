import { describe, expect, it } from 'vitest'
import {
  accountHasRebateActivity,
  accountRiskLevel,
  hasExcessiveHierarchyRebate,
  hasVisibleRebateActivity,
  nodeRiskLevel,
} from './rebateTreeRisk'

describe('rebate tree risk display', () => {
  it('maps account contribution to display severity', () => {
    expect(accountRiskLevel({ riskContribution: 19.9 })).toBe('')
    expect(accountRiskLevel({ riskContribution: 20 })).toBe('预警')
    expect(accountRiskLevel({ riskContribution: 30 })).toBe('高危')
    expect(accountRiskLevel({ riskContribution: 40 })).toBe('严重')
  })

  it('propagates the highest descendant severity to customer nodes', () => {
    const node = {
      accounts: [{ riskContribution: 31 }],
      children: [{ risk: { level: '严重' }, accounts: [], children: [] }],
    }
    expect(nodeRiskLevel(node)).toBe('严重')
  })

  it('hides zero-order zero-contribution accounts and recursively empty branches', () => {
    expect(accountHasRebateActivity({ orders: 0, riskContribution: 0 })).toBe(false)
    expect(accountHasRebateActivity({ orders: 1, riskContribution: 0 })).toBe(true)
    expect(accountHasRebateActivity({ orders: 0, riskContribution: 20 })).toBe(true)
    expect(hasVisibleRebateActivity({
      financials: { accounts: 2, orders: 0, lots: 0, tradeProfit: 0, hierarchyRebate: 0 },
      accounts: [{ orders: 0, riskContribution: 0 }],
      children: [],
    })).toBe(false)
    expect(hasVisibleRebateActivity({
      financials: { accounts: 0, orders: 0 },
      accounts: [],
      children: [{ financials: { hierarchyRebate: 1 }, accounts: [], children: [] }],
    })).toBe(true)
  })

  it('flags only customer rows whose positive hierarchy rebate pushes combined value above zero', () => {
    expect(hasExcessiveHierarchyRebate({ type: 'customer', financials: { tradeProfit: -100, hierarchyRebate: 101 } })).toBe(true)
    expect(hasExcessiveHierarchyRebate({ type: 'customer', financials: { tradeProfit: -100, hierarchyRebate: 100 } })).toBe(false)
    expect(hasExcessiveHierarchyRebate({ type: 'customer', financials: { tradeProfit: 100, hierarchyRebate: 0 } })).toBe(false)
    expect(hasExcessiveHierarchyRebate({ type: 'ib', financials: { tradeProfit: -100, hierarchyRebate: 101 } })).toBe(false)
  })
})
