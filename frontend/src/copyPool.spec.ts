import { describe, expect, it } from 'vitest'
import { accountPrimaryLabel, accountSecondaryLabel, copyReasonLabel, copyStatusLabel, currentCopyRows, delayGateLabel, eventExecutionLabel, eventPoolTier, formatDuration, linePath, orderActionLabel, phaseLabel, POOL_TIER_TABS, poolTierLabel, poolTierReason, resolvePoolTierRows, schedulerStateLabel, sourceActionLabel, sourceEntryLabel, sourceSideLabel, sourceStateFailed, sourceStateLabel, stepPath, weightReason, weightStateLabel } from './copyPool'

describe('copy pool presentation helpers', () => {
  it('localizes operational states and events', () => {
    expect(phaseLabel('live')).toBe('实时运行')
    expect(phaseLabel('pool_rebuild_failed')).toBe('客户池重建失败')
    expect(orderActionLabel('TARGET_RECONCILE')).toBe('目标仓位调整')
    expect(orderActionLabel('INDEPENDENT_OPEN')).toBe('客户独立开仓 / 加仓')
    expect(copyStatusLabel('risk_rejected')).toBe('风控拒绝')
    expect(poolTierLabel('entry_shadow')).toBe('入池影子观察')
    expect(schedulerStateLabel('running')).toBe('执行中')
    expect(delayGateLabel('incomplete')).toBe('报价覆盖不完整')
    expect(copyReasonLabel('below_minimum_risk_lot')).toBe('客户独立风险手数低于产品最小手')
    expect(eventExecutionLabel({ decision: 'active', desiredTargetLots: 0.01 })).toBe('跟单成功')
    expect(eventExecutionLabel({ decision: 'risk_rejected', rawTargetLots: 0.0045, desiredTargetLots: 0 })).toBe('未跟单：目标手数低于最小手')
    expect(eventExecutionLabel({ decision: 'signal_expired', desiredTargetLots: 0 })).toBe('未跟单：信号已过期，未复制')
    expect(eventExecutionLabel({ decision: 'monitor', reasonCode: 'below_minimum_risk_lot', desiredTargetLots: 0 })).toBe('未跟单：客户独立风险手数低于产品最小手')
    expect(eventExecutionLabel({ decision: 'risk_rejected', reasonCode: 'execution_gate_blocked:spread', desiredTargetLots: 0 })).toBe('未跟单：点差超过开仓上限')
    expect(eventExecutionLabel({ decision: 'monitor', desiredTargetLots: 0 })).toBe('未跟单：当时仅监控；旧事件未保存具体子原因')
    expect(eventExecutionLabel({ desiredTargetLots: 0 })).toBe('未跟单：旧事件未保存执行结果')
    expect(eventExecutionLabel({ decision: 'monitor', phase: 'pool_rebuild_failed', desiredTargetLots: 0 })).toBe('未跟单：客户池重建失败，执行暂停，目标手数为 0')
    expect(eventExecutionLabel({ phase: 'pool_rebuild_failed', desiredTargetLots: 0 })).toBe('未跟单：客户池重建失败，执行暂停，目标手数为 0')
    expect(eventPoolTier({ decision: 'monitor', phase: 'pool_rebuild_failed' }, 'active')).toBe('execution_suspended')
    expect(eventPoolTier({ decision: 'monitor', phase: 'live' }, 'active')).toBe('monitor')
    expect(sourceActionLabel('reverse')).toBe('反转')
    expect(sourceSideLabel('BUY')).toBe('买入')
    expect(sourceEntryLabel(1)).toBe('平仓')
    expect(sourceStateLabel({ state: 'idle', subscriptionState: 'unsubscribed' })).toBe('已接入，当前无订阅账号')
    expect(sourceStateFailed({ state: 'idle' })).toBe(false)
    expect(sourceStateLabel({ state: 'error' })).toBe('读取失败')
    expect(sourceStateFailed({ state: 'error' })).toBe(true)
    expect(formatDuration(3725)).toBe('1小时2分')
    expect(accountPrimaryLabel({ accountLogin: '5200101', clientAlias: 'C001' })).toBe('5200101')
    expect(accountSecondaryLabel({ clientAlias: 'C001', accountServer: 'DBG GB MT5 Live2' })).toBe('DBG GB MT5 Live2')
    expect(accountPrimaryLabel({ clientAlias: 'C001' })).toBe('-')
    expect(weightStateLabel({ weightState: 'removed' })).toBe('移出 · 下调 100%')
    expect(weightReason({ weightState: 'removed', dynamicEvaluationUsd: -11.28 })).toBe('下调 100% · 动态评估 -11.28 USD')
    expect(weightReason({ weightState: 'reduced', weightAdjustment: -0.5, dynamicEvaluationUsd: -3 })).toBe('下调 50% · 动态评估 -3.00 USD')
  })

  it('builds bounded line and stepped position paths', () => {
    const rows = [{ equityUsd: 10000, actualStrategyLots: 0 }, { equityUsd: 9990, actualStrategyLots: 0.05 }]
    expect(linePath(rows, 'equityUsd', 200, 100)).toMatch(/^M/)
    expect(stepPath(rows, 'actualStrategyLots', 0.05, 200, 100)).toContain(' H')
    expect(linePath([], 'equityUsd', 200, 100)).toBe('')
  })

  it('keeps legacy entry-shadow snapshots compatible without exposing an entry-shadow tab', () => {
    const rows = resolvePoolTierRows(
      [
        { clientAlias: 'C001', clientProductKey: 'C001|XAUUSD', accountLogin: '3054777', product: 'XAUUSD', poolTier: 'monitor' },
        { clientAlias: 'C002', clientProductKey: 'C002|EURUSD', accountLogin: '5200101', product: 'EURUSD', poolTier: 'active' },
      ],
      [
        { clientAlias: 'C001', product: 'XAUUSD', tier: 'entry_shadow' },
        { clientAlias: 'C002', product: 'EURUSD', tier: 'active' },
      ],
      [{ clientAlias: 'C002', status: 'paused', reductionReason: '客户亏损额度冷却中' }],
    )

    expect(POOL_TIER_TABS).not.toContain('entry_shadow')
    expect(rows.map(row => row.currentTier)).toEqual(['monitor', 'execution_suspended'])
    expect(rows[0].accountLogin).toBe('3054777')
    expect(poolTierLabel('entry_shadow')).toBe('入池影子观察')
    expect(poolTierReason(rows[0])).toContain('未下调')
    expect(poolTierReason(rows[1])).toBe('客户亏损额度冷却中')
  })

  it('does not expose a zero-weight dynamic sleeve as active', () => {
    const rows = resolvePoolTierRows(
      [{ clientAlias: 'C001', clientProductKey: 'C001|XAUUSD', product: 'XAUUSD', poolTier: 'active' }],
      [{ clientAlias: 'C001', clientProductKey: 'C001|XAUUSD', product: 'XAUUSD', tier: 'active', effectiveWeight: 0 }],
      [],
    )

    expect(rows[0].currentTier).toBe('execution_suspended')
  })

  it('joins independent source positions to Demo tickets without exposing aliases', () => {
    const rows = currentCopyRows(
      [{ clientAlias: 'C001', accountLogin: '3054777', accountServer: 'DBG CN MT4 Live2', accountPlatform: 'MT4', product: 'XAUUSD', sourcePositionId: 135826468, sourceLots: 0.2, copiedSignedLots: -0.01, sourceOpenedAt: '2026-07-31T15:12:07+08:00', detailPath: '/copy-pool/accounts/C001', status: 'active' }],
      [{ clientAlias: 'C001', accountLogin: '3054777', product: 'XAUUSD', sourcePositionId: 135826468, demoTicket: 90001, lots: 0.01, side: -1, openTime: '2026-07-31T15:12:08+08:00' }],
    )

    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ accountLogin: '3054777', sourcePositionId: 135826468, demoTicket: 90001, signedLots: -0.01, entryDelaySeconds: 1 })
    expect(rows[0]).not.toHaveProperty('clientAlias')
  })
})
