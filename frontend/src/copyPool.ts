export type NumericRow = Record<string, unknown>

export const POOL_TIER_TABS = [
  'active',
  'entry_shadow',
  'monitor',
  'reserve',
  'recovery_shadow',
  'execution_suspended',
  'hard_rejected',
] as const

export type PoolTierTab = typeof POOL_TIER_TABS[number]
export type PoolTierRow = Record<string, unknown> & {
  currentTier: PoolTierTab
  dynamicState: Record<string, unknown> | null
  clientRisk: Record<string, unknown> | null
}

export function accountPrimaryLabel(row: Record<string, unknown>): string {
  return String(row.accountLogin || '-')
}

export function accountSecondaryLabel(row: Record<string, unknown>): string {
  const source = String(row.accountServer || row.accountPlatform || '').trim()
  return source
}

export function phaseLabel(value: unknown): string {
  return ({
    starting: '正在启动',
    shadow: '影子核对',
    armed: '等待实盘授权',
    armed_waiting_autotrading: '等待自动交易开关',
    live: '实时运行',
    cooldown: '风险冷却',
    recovery_shadow: '恢复核对',
    daily_stop: '当日停止',
    equity_floor_stop: '权益地板停止',
    margin_hard_stop: '保证金硬限制停止',
    execution_hard_stop: '执行故障停止',
    pool_rebuilding: '正在重建客户池',
    pool_rebuild_failed: '客户池重建失败',
    stopped: '已停止',
  } as Record<string, string>)[String(value || '')] || '状态未知'
}

export function orderActionLabel(value: unknown): string {
  return ({
    STAGED_START: '分阶段开仓',
    TARGET_RECONCILE: '目标仓位调整',
    FLATTEN: '策略平仓',
    CYCLE_LOSS_STOP: '周期止损',
    DAILY_LOSS_STOP: '当日止损',
    DB_TIMEOUT_FLATTEN: '数据库中断平仓',
    FRIDAY_FLATTEN: '周五收盘平仓',
    INDEPENDENT_OPEN: '客户独立开仓 / 加仓',
    INDEPENDENT_REDUCE: '客户独立减仓 / 平仓',
  } as Record<string, string>)[String(value || '')] || String(value || '订单事件')
}

export function copyStatusLabel(value: unknown): string {
  return ({
    active: '活动跟单',
    reduced: '动态降权',
    monitor: '仅监控',
    shadow_monitor: '影子监控',
    risk_rejected: '风控拒绝',
    paused: '客户暂停',
    recovery_shadow: '恢复影子观察',
    risk_flattened: '组合风控平仓',
    closed: '已平仓',
  } as Record<string, string>)[String(value || '')] || String(value || '状态未知')
}

export function poolTierLabel(value: unknown): string {
  return ({
    reserve: '候补池',
    monitor: '监控池',
    entry_shadow: '入池影子观察',
    active: '活动跟单池',
    recovery_shadow: '恢复影子观察',
    execution_suspended: '执行已暂停',
    hard_rejected: '硬门槛拒绝',
  } as Record<string, string>)[String(value || '')] || '层级未提供'
}

export function poolTierTabLabel(value: PoolTierTab): string {
  return ({
    active: '活动跟单池',
    entry_shadow: '入场观察',
    monitor: '监控池',
    reserve: '候补池',
    recovery_shadow: '恢复观察',
    execution_suspended: '执行暂停',
    hard_rejected: '硬门拒绝',
  } as Record<PoolTierTab, string>)[value]
}

function normalizePoolTier(value: unknown): PoolTierTab {
  const tier = String(value || '').trim().toLowerCase()
  return (POOL_TIER_TABS as readonly string[]).includes(tier)
    ? tier as PoolTierTab
    : 'monitor'
}

function sleeveKey(row: Record<string, unknown>): string {
  const direct = String(row.clientProductKey || '').trim()
  if (direct) return direct
  const alias = String(row.clientAlias || '').trim()
  const product = String(row.product || '').trim().toUpperCase()
  return alias && product ? `${alias}|${product}` : ''
}

function clientRiskTier(row: Record<string, unknown> | undefined): PoolTierTab | null {
  switch (String(row?.status || '').trim().toLowerCase()) {
    case 'recovery_shadow': return 'recovery_shadow'
    case 'paused':
    case 'risk_flattened': return 'execution_suspended'
    case 'risk_rejected': return 'hard_rejected'
    default: return null
  }
}

export function resolvePoolTierRows(
  pool: Record<string, unknown>[],
  dynamicSleeves: Record<string, unknown>[],
  clientRisks: Record<string, unknown>[],
): PoolTierRow[] {
  const dynamicBySleeve = new Map(dynamicSleeves.map(row => [sleeveKey(row), row]))
  const riskByAlias = new Map(clientRisks.map(row => [String(row.clientAlias || ''), row]))
  return pool.map(row => {
    const dynamicState = dynamicBySleeve.get(sleeveKey(row)) || null
    const clientRisk = riskByAlias.get(String(row.clientAlias || '')) || null
    const dynamicTier = dynamicState ? normalizePoolTier(dynamicState.tier) : null
    const currentTier = clientRiskTier(clientRisk || undefined) || dynamicTier
      || normalizePoolTier(row.poolTier || row.tier || row.poolStatus)
    return { ...row, currentTier, dynamicState, clientRisk }
  })
}

export function poolTierReason(row: PoolTierRow): string {
  const riskReason = String(row.clientRisk?.reductionReason || '').trim()
  if (riskReason) return riskReason
  const gates = Array.isArray(row.factorGateReasons)
    ? row.factorGateReasons.map(String).filter(Boolean)
    : String(row.factorGateReasons || '').split(/[|,;]/).map(value => value.trim()).filter(Boolean)
  if (gates.length) return gates.join('、')
  if (row.currentTier === 'active') return '已满足当前执行与风险条件'
  if (row.currentTier === 'entry_shadow') return '等待影子观察连续健康通过'
  if (row.currentTier === 'recovery_shadow') return '恢复前影子观察中'
  if (row.currentTier === 'execution_suspended') return '执行已暂停，保留监控'
  if (row.currentTier === 'hard_rejected') return '当前未通过硬门槛'
  return weightReason(row)
}

export function schedulerStateLabel(value: unknown): string {
  return ({
    due: '待执行',
    running: '执行中',
    completed: '已完成',
    idle: '等待下个周期',
  } as Record<string, string>)[String(value || '')] || '未提供'
}

export function delayGateLabel(value: unknown): string {
  return ({
    passed: '通过',
    failed: '未通过',
    unavailable: '数据不足',
    incomplete: '报价覆盖不完整',
  } as Record<string, string>)[String(value || '')] || '未提供'
}

export function copyReasonLabel(value: unknown): string {
  return ({
    risk_allowed: '风控通过',
    source_closed: '来源仓已平仓',
    old_or_shadow_position: '旧仓或影子期仓位不追单',
    client_loss_pause: '客户亏损额度冷却中',
    client_recovery_shadow: '客户恢复前影子观察',
    source_position_over_24h: '来源持仓超过24小时',
    zero_effective_weight: '当前有效权重为零',
    below_minimum_risk_lot: '风险额度不足最小手',
    execution_gate_blocked: '点差、延迟或外部仓位闸门阻止开仓',
    client_not_in_current_pool: '客户已不在当前池中',
  } as Record<string, string>)[String(value || '')] || String(value || '已通过')
}

export function sourceActionLabel(value: unknown): string {
  return ({
    open: '开仓',
    increase: '加仓',
    reduce: '减仓',
    close: '平仓',
    reverse: '反转',
    monitor: '监控',
  } as Record<string, string>)[String(value || '')] || String(value || '-')
}

export function sourceSideLabel(value: unknown): string {
  return String(value || '').toUpperCase() === 'BUY' ? '买入' : String(value || '').toUpperCase() === 'SELL' ? '卖出' : '-'
}

export function sourceEntryLabel(value: unknown): string {
  return ({ 0: '开仓', 1: '平仓', 2: '反向成交', 3: '对手平仓' } as Record<number, string>)[Number(value)] || '其他成交'
}

export function sourceStateLabel(row: Record<string, unknown>): string {
  if (row.state === 'idle' || row.subscriptionState === 'unsubscribed') return '已接入，当前无订阅账号'
  if (row.state === 'ok' && Number(row.ageSeconds) <= 3) return '正常'
  if (row.state === 'ok') return '数据陈旧'
  if (row.state === 'error') return '读取失败'
  return '等待运行时状态'
}

export function sourceStateFailed(row: Record<string, unknown>): boolean {
  return row.state === 'error' || (row.state === 'ok' && Number(row.ageSeconds) > 3)
}

export function formatDuration(seconds: unknown): string {
  const value = Math.max(0, Number(seconds) || 0)
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = Math.floor(value % 60)
  if (hours) return `${hours}小时${minutes}分`
  if (minutes) return `${minutes}分${secs}秒`
  return `${secs}秒`
}

export function weightStateLabel(row: Record<string, unknown>): string {
  if (row.weightState === 'removed') return '移出 · 下调 100%'
  if (row.weightState === 'reduced') return `下调 ${Math.abs(Number(row.weightAdjustment) * 100).toFixed(0)}%`
  return '权重不变'
}

export function weightReason(row: Record<string, unknown>): string {
  const evaluation = Number(row.dynamicEvaluationUsd ?? row.intradayNetUsd)
  const pnl = Number.isFinite(evaluation) ? `${evaluation.toFixed(2)} USD` : '-'
  if (row.weightState === 'removed') return `下调 100% · 动态评估 ${pnl}`
  if (row.weightState === 'reduced') {
    return `下调 ${Math.abs(Number(row.weightAdjustment) * 100).toFixed(0)}% · 动态评估 ${pnl}`
  }
  if (evaluation < 0) return `未触发降权 · 动态评估 ${pnl}`
  return `未下调 · 动态评估 ${pnl}`
}

export function linePath(
  rows: NumericRow[],
  key: string,
  width: number,
  height: number,
  padX = 48,
  padY = 18,
): string {
  if (!rows.length) return ''
  const values = rows.map(row => Number(row[key])).filter(Number.isFinite)
  if (!values.length) return ''
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  const span = maximum - minimum || Math.max(Math.abs(maximum), 1) * 0.01
  const availableWidth = Math.max(1, width - padX * 2)
  const availableHeight = Math.max(1, height - padY * 2)
  return rows.map((row, index) => {
    const value = Number(row[key])
    const x = padX + availableWidth * index / Math.max(rows.length - 1, 1)
    const y = padY + availableHeight * (maximum - value) / span
    return `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
}

export function stepPath(
  rows: NumericRow[],
  key: string,
  maximum: number,
  width: number,
  height: number,
  padX = 48,
  padY = 18,
): string {
  if (!rows.length) return ''
  const cap = Math.max(Math.abs(maximum), 0.01)
  const availableWidth = Math.max(1, width - padX * 2)
  const availableHeight = Math.max(1, height - padY * 2)
  const point = (row: NumericRow, index: number) => ({
    x: padX + availableWidth * index / Math.max(rows.length - 1, 1),
    y: padY + availableHeight * (cap - Number(row[key])) / (cap * 2),
  })
  const first = point(rows[0], 0)
  let path = `M${first.x.toFixed(1)} ${first.y.toFixed(1)}`
  rows.slice(1).forEach((row, offset) => {
    const next = point(row, offset + 1)
    path += ` H${next.x.toFixed(1)} V${next.y.toFixed(1)}`
  })
  return path
}
