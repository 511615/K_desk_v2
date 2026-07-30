import { describe, expect, it } from 'vitest'
import { bonusAccountHref, bonusHedgeFinding, bonusLevelRank, bonusPeakOrders, filterBonusResults } from './bonusDiscovery'

describe('bonus discovery presentation', () => {
  it('orders the account-cycle levels and filters the ranking', () => {
    const rows = [
      { account: '1', level: '关注' },
      { account: '2', level: '预警' },
      { account: '3', level: '高危形态' },
      { account: '4', level: '严重形态' },
    ]
    expect(bonusLevelRank('严重形态')).toBeGreaterThan(bonusLevelRank('预警'))
    expect(filterBonusResults(rows, 'high').map(row => row.account)).toEqual(['3', '4'])
  })

  it('preserves platform and server in account links', () => {
    expect(bonusAccountHref({ account: 621928, platform: 'MT5', server: 'AC GB MT5' }))
      .toBe('/account/621928?platform=MT5&server=AC+GB+MT5')
  })

  it('projects minimum-margin orders and visible suspected hedge evidence for the detail card', () => {
    const row = { bestCycle: {
      minimumMarginOrders: [{ tradeId: 'p1' }, { tradeId: 'p2' }],
      earlyPeakOrders: [{ tradeId: 'legacy' }],
      peerMatch: { matches: 1, lotCoverage: 0.75, accounts: [900001], details: [{ subjectTrade: 'p1', peerTrade: 'q1' }] },
    } }

    expect(bonusPeakOrders(row).map(order => order.tradeId)).toEqual(['p1', 'p2'])
    expect(bonusHedgeFinding(row)).toEqual({
      found: true, matches: 1, coverage: 0.75, accounts: ['900001'],
      details: [{ subjectTrade: 'p1', peerTrade: 'q1' }],
    })
    expect(bonusHedgeFinding({ bestCycle: {} }).found).toBe(false)
    expect(bonusPeakOrders({ bestCycle: { earlyPeakOrders: [{ tradeId: 'legacy' }] } })[0].tradeId).toBe('legacy')
  })
})
