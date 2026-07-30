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
      },
    },
    isLoading: { value: false },
    error: { value: null },
  }),
}))

vi.mock('../api', () => ({ api: vi.fn() }))
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
})
