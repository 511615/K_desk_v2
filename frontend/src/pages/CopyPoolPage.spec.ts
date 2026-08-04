// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({
    data: {
      value: {
        available: true,
        stale: false,
        status: {},
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

describe('CopyPoolPage tier tabs', () => {
  it('switches account lists by current tier without exposing aliases', async () => {
    const wrapper = mount(CopyPoolPage)

    expect(wrapper.get('[role="tablist"]').text()).toContain('活动跟单池1')
    expect(wrapper.text()).toContain('3054777')
    expect(wrapper.text()).not.toContain('C001')

    await wrapper.findAll('[role="tab"]').find(tab => tab.text().includes('硬门拒绝'))!.trigger('click')

    expect(wrapper.text()).toContain('5200101')
    expect(wrapper.text()).toContain('当前综合收益为负')
    expect(wrapper.text()).not.toContain('C002')
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
