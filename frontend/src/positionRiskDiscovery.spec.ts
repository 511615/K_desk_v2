import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

import { filterPositionRiskResults, positionClassificationLabel, positionRiskAccountHref, sortPositionRiskResults } from './positionRiskDiscovery'

describe('position risk discovery helpers', () => {
  it('keeps routed account links', () => {
    expect(positionRiskAccountHref({ account: '5005153', platform: 'MT5', server: 'AC GB MT5' }))
      .toBe('/account/5005153?platform=MT5&server=AC+GB+MT5')
  })

  it('filters by the shared toxic score levels', () => {
    const rows = [{ score: 39 }, { score: 60 }, { score: 75 }, { score: 90 }]
    expect(filterPositionRiskResults(rows, 'warning')).toHaveLength(3)
    expect(filterPositionRiskResults(rows, 'severe')).toEqual([{ score: 90 }])
    expect(filterPositionRiskResults(rows, 'all')).toHaveLength(4)
  })

  it('uses readable event labels', () => {
    expect(positionClassificationLabel('combined')).toBe('周末 + 重开加仓')
  })

  it('sorts copies of the result list by profit, position or score', () => {
    const rows = [
      { account: '2', score: 80, netProfit: 50, marginRatio: 0.8 },
      { account: '1', score: 90, netProfit: 10, marginRatio: 0.3 },
    ]
    expect(sortPositionRiskResults(rows, 'profit').map(row => row.account)).toEqual(['2', '1'])
    expect(sortPositionRiskResults(rows, 'position').map(row => row.account)).toEqual(['2', '1'])
    expect(sortPositionRiskResults(rows, 'score').map(row => row.account)).toEqual(['1', '2'])
    expect(rows.map(row => row.account)).toEqual(['2', '1'])
  })

  it('keeps the ranking evidence and per-account analysis modal visible', () => {
    const source = readFileSync(new URL('./components/PositionRiskDiscoveryPanel.vue', import.meta.url), 'utf8')
    expect(source).toContain('峰值仓位')
    expect(source).toContain('反向疑似对锁')
    expect(source).toContain('重仓开赌订单')
    expect(source).toContain('保证金占权益（越高越满）')
    expect(source).toContain('估算保证金水平（越低越满）')
    expect(source).toContain('同步开平仓检索覆盖')
    expect(source).toContain('同步同向订单')
    expect(source).toContain('同步反向疑似对锁订单')
    expect(source).toContain('手数相似度')
    expect(source).toContain('较小手数不低于较大手数80%')
    expect(source).toContain('最低仓位（%）')
    expect(source).toContain('最低手数（峰值）')
    expect(source).toContain('最小盈利金额')
    expect(source).toContain('按盈利金额')
    expect(source).toContain('旧任务未验证同步平仓')
    expect(source).toContain('position-analysis-modal')
    expect(source).toContain('position-risk-conclusion')
  })
})
