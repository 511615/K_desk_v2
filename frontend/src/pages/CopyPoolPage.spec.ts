// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({
    data: {
      value: {
        available: true,
        stale: false,
        status: {},
        demoAccount: {
          updatedAt: '2026-08-05T10:05:00+08:00',
          account: { login: '33304642', server: 'ACCMGlobal-Demo', balanceUsd: 9818.24, equityUsd: 9821.44, marginUsd: 120, freeMarginUsd: 9701.44, marginLevelPercent: 8184.53 },
          positions: [
            { ticket: 90001, product: 'XAUUSD', side: 'BUY', lots: 0.01, openPrice: 4080.5, currentPrice: 4083.1, floatingPnlUsd: 2.6, swapUsd: -0.1, openedAt: '2026-08-05T09:10:00+08:00', strategyOwned: true, positionId: 89005 },
            { ticket: 90002, product: 'EURUSD', side: 'BUY', lots: 0.02, openPrice: 1.1, currentPrice: 1.102, floatingPnlUsd: 3.4, swapUsd: -0.2, openedAt: '2026-08-05T09:20:00+08:00', strategyOwned: true, positionId: 89002 },
          ],
          deals: [
            { dealTicket: 80001, positionId: 89001, time: '2026-08-05T00:40:00Z', product: 'XAUUSD', entry: 'OUT', side: 'SELL', lots: 0.01, price: 4082, netPnlUsd: 2.1, strategyOwned: true },
            { dealTicket: 80005, positionId: 89001, time: '2026-08-05T00:45:00Z', product: 'XAUUSD', entry: 'OUT_BY', side: 'SELL', lots: 0.01, price: 4083, netPnlUsd: 1.5, strategyOwned: true },
            { dealTicket: 80000, positionId: 89001, time: '2026-08-05T00:30:00Z', product: 'XAUUSD', entry: 'IN', side: 'BUY', lots: 0.01, price: 4080, netPnlUsd: 0, strategyOwned: true },
            { dealTicket: 80002, positionId: 89002, time: '2026-08-05T01:00:00Z', product: 'EURUSD', entry: 'IN', side: 'BUY', lots: 0.02, price: 1.1, netPnlUsd: 0, strategyOwned: true },
            { dealTicket: 80003, positionId: 89003, time: '2026-08-05T01:10:00Z', product: 'GBPUSD', entry: 'IN', side: 'BUY', lots: 0.03, price: 1.3, netPnlUsd: 0, strategyOwned: true },
            { dealTicket: 80004, positionId: 89004, time: '2026-08-05T01:20:00Z', product: 'USDJPY', entry: 'OUT', side: 'SELL', lots: 0.04, price: 150, netPnlUsd: 4.5, strategyOwned: true },
          ],
        },
        pool: [
          {
            clientAlias: 'C001',
            clientProductKey: 'C001|XAUUSD',
            accountLogin: '3054777',
            accountServer: 'DBG GB MT5 Live2',
            product: 'XAUUSD',
            poolTier: 'monitor',
            baseWeight: 0.1,
            effectiveWeight: 0.08,
            detailPath: '/copy-pool/accounts/C001',
          },
          {
            clientAlias: 'C002',
            clientProductKey: 'C002|EURUSD',
            accountLogin: '5200101',
            accountServer: 'AC MT5 Live',
            product: 'EURUSD',
            poolTier: 'active',
            baseWeight: 0.08,
            effectiveWeight: 0,
            detailPath: '/copy-pool/accounts/C002',
          },
        ],
        dynamicSleeves: [
          { clientAlias: 'C001', product: 'XAUUSD', tier: 'active' },
          { clientAlias: 'C002', product: 'EURUSD', tier: 'active' },
        ],
        clientRisks: [{ clientAlias: 'C002', status: 'risk_rejected', reductionReason: '当前综合收益为负' }],
        events: [
          { eventId: 1, time: '2026-08-05T01:30:00Z', accountLogin: '3054777', product: 'XAUUSD', sourceSide: 'BUY', sourceLots: 0.2, sourceEntry: 'IN', decision: '已更新独立来源仓', dbLatencySeconds: 0.4 },
          { eventId: 2, time: '2026-08-05T01:31:00Z', accountLogin: '5200101', product: 'EURUSD', sourceSide: 'SELL', sourceLots: 0.1, sourceEntry: 1, decision: '仅监控', dbLatencySeconds: 0.5 },
        ],
        orders: [],
        copyPositions: [{ clientAlias: 'C001', accountLogin: '3054777', accountServer: 'DBG GB MT5 Live2', accountPlatform: 'MT5', product: 'XAUUSD', sourcePositionId: 135826468, sourceLots: 0.2, copiedLots: 0.01, copiedSignedLots: 0.01, sourceOpenedAt: '2026-07-31T15:12:07+08:00', status: 'active', detailPath: '/copy-pool/accounts/C001' }],
        ticketMappings: [{ clientAlias: 'C001', accountLogin: '3054777', product: 'XAUUSD', sourcePositionId: 135826468, demoTicket: 90001, lots: 0.01, side: 1, openTime: '2026-07-31T15:12:08+08:00' }],
      },
    },
    isLoading: { value: false },
    error: { value: null },
  }),
}))

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }))
vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../frontendUpdate', () => ({ startFrontendUpdateMonitor: () => () => undefined }))

import CopyPoolPage from './CopyPoolPage.vue'

afterEach(() => {
  vi.useRealTimers()
})

describe('CopyPoolPage tier tabs', () => {
  it('advances the header clock once per second independently of dashboard refreshes', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-05T10:06:56+08:00'))
    const wrapper = mount(CopyPoolPage)
    const clock = wrapper.get('[data-testid="runtime-clock"]')
    const accountClock = wrapper.get('[data-testid="demo-account-clock"]')

    expect(clock.text()).toBe('北京时间 2026/8/5 10:06:56')
    expect(accountClock.text()).toBe(clock.text())

    await vi.advanceTimersByTimeAsync(1000)

    expect(clock.text()).toBe('北京时间 2026/8/5 10:06:57')
    expect(accountClock.text()).toBe(clock.text())
    wrapper.unmount()
  })

  it('shows the current Demo account positions and real deal history at the top', () => {
    const wrapper = mount(CopyPoolPage)

    const accountPanel = wrapper.get('[data-testid="demo-account-panel"]')
    expect(accountPanel.text()).toContain('33304642')
    expect(accountPanel.text()).toContain('当前持仓')
    expect(accountPanel.text()).toContain('90001')
    expect(accountPanel.text()).toContain('历史成交')
    expect(accountPanel.text()).toContain('89001')
    expect(accountPanel.text()).toContain('2026/8/5 08:45:00')
    expect(accountPanel.text()).toContain('本策略')
    expect(wrapper.html().indexOf('data-testid="demo-account-panel"')).toBeLessThan(wrapper.html().indexOf('data-testid="risk-controls"'))
  })

  it('shows one history row per closed Position and omits open or incomplete Positions', () => {
    const wrapper = mount(CopyPoolPage)
    const table = wrapper.get('[data-testid="demo-deals-table"]')

    const rows = table.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(table.text()).toContain('89001')
    expect(table.text()).toContain('89004')
    expect(table.text()).toContain('0.02 手')
    expect(table.text()).toContain('+3.60')
    expect(table.text()).not.toContain('80000')
    expect(table.text()).not.toContain('89002')
    expect(table.text()).not.toContain('89003')
  })

  it('switches account lists by current tier without exposing aliases or source-only closes', async () => {
    const wrapper = mount(CopyPoolPage)

    expect(wrapper.get('[role="tablist"]').text()).toContain('活动跟单池1')
    expect(wrapper.text()).toContain('3054777')
    expect(wrapper.text()).not.toContain('C001')
    expect(wrapper.get('[data-testid="tier-event-stream"]').text()).toContain('3054777')
    expect(wrapper.get('[data-testid="tier-event-stream"]').text()).not.toContain('5200101')

    await wrapper.findAll('[role="tab"]').find(tab => tab.text().includes('硬门拒绝'))!.trigger('click')

    expect(wrapper.text()).toContain('5200101')
    expect(wrapper.text()).toContain('当前综合收益为负')
    expect(wrapper.text()).not.toContain('C002')
    expect(wrapper.get('[data-testid="tier-event-stream"]').text()).not.toContain('5200101')
    expect(wrapper.get('[data-testid="tier-event-stream"]').text()).toContain('当前层级暂无事件')
    expect(wrapper.get('[data-testid="tier-event-stream"]').text()).not.toContain('3054777')
  })

  it('moves the event stream into scheduling and lets event tabs drive the shared pool tier', async () => {
    const wrapper = mount(CopyPoolPage)
    const scheduling = wrapper.get('.schedule-events-panel')
    expect(scheduling.text()).toContain('调度节奏')
    expect(scheduling.text()).toContain('实时事件流')
    expect(wrapper.findAll('h2').filter(node => node.text() === '实时事件流')).toHaveLength(0)

    const hardReject = wrapper.get('[data-testid="event-tier-tabs"]').findAll('button').find(button => button.text().includes('硬门拒绝'))!
    await hardReject.trigger('click')
    expect(wrapper.get('[data-testid="tier-event-stream"]').text()).not.toContain('5200101')
    expect(wrapper.get('[data-testid="tier-event-stream"]').text()).toContain('当前层级暂无事件')
    expect(wrapper.get('[aria-label="客户池层级"]').find('[aria-selected="true"]').text()).toContain('硬门拒绝')
  })

  it('shows current-copy ownership, quantities, and unavailable P/L explicitly', () => {
    const wrapper = mount(CopyPoolPage)

    const table = wrapper.get('.current-copy-table')
    expect(table.text()).toContain('单主账号')
    expect(table.text()).toContain('3054777')
    expect(table.text()).toContain('135826468')
    expect(table.text()).toContain('90001')
    expect(table.text()).toContain('单主浮盈亏')
    expect(table.text()).not.toContain('C001')
    expect(table.get('a').attributes('href')).toBe('/copy-pool/accounts/C001')
  })

  it('shows manual risk controls and sends an audited control update', async () => {
    const wrapper = mount(CopyPoolPage)

    expect(wrapper.get('[data-testid="risk-controls"]').text()).toContain('权益地板')
    await wrapper.get('[data-testid="equity-floor-toggle"]').setValue(false)
    await wrapper.get('[data-testid="apply-risk-controls"]').trigger('click')

    expect(apiMock).toHaveBeenCalledWith('/api/copy-pool/controls', expect.objectContaining({
      method: 'PUT',
      body: expect.stringContaining('"equityFloorEnabled":false'),
    }))
  })
})
