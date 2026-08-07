export type NumericRow = Record<string, unknown>

export const POOL_TIER_TABS = [
  'active',
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

export type CurrentCopyRow = Record<string, unknown> & {
  currentCopyKey: string
  accountLogin: string
  accountPlatform: string
  accountServer: string
  product: string
  sourcePositionId: string | number
  demoTicket: string | number | null
  sourceLots: unknown
  demoLots: unknown
  signedLots: number
  sourceOpenedAt: unknown
  sourceOpenPrice: unknown
  sourcePnlUsd: unknown
  demoPnlUsd: unknown
  entryDelaySeconds: unknown
  holdingSeconds: unknown
  status: unknown
  rejectReason: unknown
  detailPath: string
}

function firstPresent(row: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    const value = row[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return undefined
}

function copyPositionKey(row: Record<string, unknown>): string {
  return [
    String(row.accountLogin || ''),
    String(row.product || '').toUpperCase(),
    String(row.sourcePositionId ?? ''),
  ].join('|')
}

function copyRow(source: Record<string, unknown>, ticket: Record<string, unknown> | undefined): CurrentCopyRow {
  const ticketRow = ticket ?? {}
  const { clientAlias: _sourceAlias, ...publicSource } = source
  const { clientAlias: _ticketAlias, ...publicTicket } = ticketRow
  const sourceOpenedAt = firstPresent(source, ['sourceOpenedAt', 'source_opened_at', 'firstSignalAt', 'first_signal_at'])
  const demoOpenedAt = firstPresent(ticketRow, ['openTime', 'open_time', 'demoOpenedAt', 'demo_opened_at'])
  const explicitDelay = firstPresent(source, ['entryDelaySeconds', 'entry_delay_seconds'])
    ?? firstPresent(ticketRow, ['entryDelaySeconds', 'entry_delay_seconds'])
  const sourceOpenMs = Date.parse(String(sourceOpenedAt || ''))
  const demoOpenMs = Date.parse(String(demoOpenedAt || ''))
  const inferredDelay = Number.isFinite(sourceOpenMs) && Number.isFinite(demoOpenMs)
    ? Math.max(0, (demoOpenMs - sourceOpenMs) / 1000)
    : undefined
  const ticketLots = firstPresent(ticketRow, ['lots', 'demoLots', 'demo_lots'])
  const signedLots = Number(firstPresent(source, ['copiedSignedLots', 'copied_signed_lots']))
  const ticketSide = Number(ticket?.side)
  const direction = String(
    firstPresent(ticketRow, ['demoDirection', 'demo_direction'])
    ?? firstPresent(source, ['sourceDirection', 'source_direction'])
    ?? '',
  ).toUpperCase()
  const sign = Number.isFinite(signedLots) && signedLots !== 0
    ? Math.sign(signedLots)
    : ticketSide < 0 || direction === 'SELL' ? -1 : 1
  const sourcePositionId = firstPresent(source, ['sourcePositionId', 'source_position_id']) ?? ''
  const demoTicket = firstPresent(ticket || {}, ['demoTicket', 'demo_ticket', 'ticket'])
  return {
    ...publicSource,
    ...publicTicket,
    currentCopyKey: `${copyPositionKey(source)}|${String(demoTicket ?? 'source-only')}`,
    accountLogin: String(firstPresent(source, ['accountLogin']) ?? firstPresent(ticketRow, ['accountLogin']) ?? ''),
    accountPlatform: String(firstPresent(source, ['accountPlatform']) ?? firstPresent(ticketRow, ['accountPlatform']) ?? ''),
    accountServer: String(firstPresent(source, ['accountServer']) ?? firstPresent(ticketRow, ['accountServer']) ?? ''),
    product: String(firstPresent(source, ['product']) ?? firstPresent(ticketRow, ['product']) ?? ''),
    sourcePositionId: sourcePositionId as string | number,
    demoTicket: demoTicket == null || demoTicket === '' ? null : demoTicket as string | number,
    sourceLots: firstPresent(source, ['sourceLots', 'source_lots']),
    demoLots: firstPresent(source, ['copiedLots', 'copied_lots']) ?? ticketLots,
    signedLots: sign * Math.abs(Number(ticketLots ?? firstPresent(source, ['copiedLots', 'copied_lots'])) || 0),
    sourceOpenedAt,
    sourceOpenPrice: firstPresent(source, ['sourceOpenPrice', 'source_open_price']),
    sourcePnlUsd: firstPresent(source, ['sourceTotalPnlUsd', 'source_total_pnl_usd', 'sourceFloatingPnlUsd', 'source_floating_pnl_usd', 'sourcePnlUsd', 'source_pnl_usd', 'sourceProfitUsd', 'source_profit_usd', 'currentSourcePnlUsd']),
    demoPnlUsd: firstPresent(ticketRow, ['demoTotalPnlUsd', 'demo_total_pnl_usd', 'demoPnlUsd', 'demo_pnl_usd', 'profitUsd', 'profit_usd', 'currentDemoPnlUsd'])
      ?? firstPresent(source, ['demoTotalPnlUsd', 'demo_total_pnl_usd', 'demoPnlUsd', 'demo_pnl_usd', 'copiedPnlUsd', 'copied_pnl_usd']),
    entryDelaySeconds: explicitDelay ?? inferredDelay,
    holdingSeconds: firstPresent(source, ['sourceHoldingSeconds', 'source_holding_seconds', 'holdingSeconds', 'holding_seconds']),
    status: firstPresent(source, ['copyStatus', 'copy_status', 'status']) ?? firstPresent(ticketRow, ['status']) ?? 'monitor',
    rejectReason: firstPresent(source, ['rejectReason', 'reject_reason']) ?? '',
    detailPath: String(firstPresent(source, ['detailPath']) ?? firstPresent(ticket || {}, ['detailPath']) ?? ''),
  }
}

/**
 * The runtime's public contract currently exposes source positions and Demo-ticket mappings
 * separately. Keep rows at ticket granularity so independent ownership is visible to operators.
 * `currentCopies` is accepted additively for a future producer snapshot without changing the UI.
 */
export function currentCopyRows(
  copyPositions: Record<string, unknown>[],
  ticketMappings: Record<string, unknown>[],
  currentCopies: Record<string, unknown>[] = [],
): CurrentCopyRow[] {
  if (currentCopies.length) return currentCopies.map(row => copyRow(row, row))
  const mappingsByPosition = new Map<string, Record<string, unknown>[]>()
  ticketMappings.forEach(mapping => {
    const key = copyPositionKey(mapping)
    const rows = mappingsByPosition.get(key) || []
    rows.push(mapping)
    mappingsByPosition.set(key, rows)
  })
  return copyPositions.flatMap(position => {
    const mappings = mappingsByPosition.get(copyPositionKey(position)) || []
    return mappings.length ? mappings.map(mapping => copyRow(position, mapping)) : [copyRow(position, undefined)]
  }).sort((left, right) => {
    const account = left.accountLogin.localeCompare(right.accountLogin)
    if (account) return account
    return String(left.sourcePositionId).localeCompare(String(right.sourcePositionId))
      || Number(left.demoTicket || 0) - Number(right.demoTicket || 0)
  })
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
    let currentTier = clientRiskTier(clientRisk || undefined) || dynamicTier
      || normalizePoolTier(row.poolTier || row.tier || row.poolStatus)
    const finalWeight = Number(dynamicState?.effectiveWeight ?? row.effectiveWeight)
    if (currentTier === 'active' && (!Number.isFinite(finalWeight) || finalWeight <= 0)) {
      currentTier = 'execution_suspended'
    }
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
  const text = String(value || '')
  const labels = {
    active: '已进入复制执行',
    closed: '来源仓已平仓',
    monitor: '仅监控，未复制',
    legacy_monitor_only: '旧仓仅监控，未追单',
    signal_expired: '信号已过期，未复制',
    risk_rejected: '风控拒绝，未复制',
    risk_allowed: '风控通过',
    source_closed: '来源仓已平仓',
    old_or_shadow_position: '旧仓或影子期仓位不追单',
    client_loss_pause: '客户亏损额度冷却中',
    client_recovery_shadow: '客户恢复前影子观察',
    source_position_over_24h: '来源持仓超过24小时',
    zero_effective_weight: '当前有效权重为零',
    below_minimum_risk_lot: '客户独立风险手数低于产品最小手',
    event_detail_unavailable: '执行器未保存更细子原因',
    'execution_gate_blocked:external_position_conflict': '该产品存在人工或其他 EA 持仓冲突',
    'execution_gate_blocked:pending_order_conflict': '该产品存在未完成挂单，暂不新增跟单仓位',
    'execution_gate_blocked:invalid_quote': '报价无效',
    'execution_gate_blocked:stale_quote': '报价过期',
    'execution_gate_blocked:spread': '点差超过开仓上限',
    'execution_gate_blocked:database_stale': '该客户所在交易服务器的数据超过 3 秒未更新',
    'execution_gate_blocked:operational_gates': '启动对账、来源覆盖或重复事件检查尚未通过',
    'execution_gate_blocked:source_coverage': '全数据库来源覆盖尚未完成',
    'execution_gate_blocked:duplicate_events': '检测到重复来源事件，已暂停新增仓位',
    'execution_gate_blocked:source_reconcile': '来源持仓快照正在对账，尚未完成启动确认',
    'execution_gate_blocked:latency_warmup': '延迟样本不足或最近轮询 P95 超过 2 秒',
    'execution_gate_blocked:manual_or_terminal': '自动交易开关或 MT5 终端权限未就绪',
    'execution_gate_blocked:manual_control': '前端“自动交易”开关已关闭',
    'execution_gate_blocked:friday_reduce_only': '周五收盘保护已进入只减仓阶段',
    'execution_gate_blocked:terminal_autotrading': 'MT5 终端 AutoTrading 已关闭',
    'execution_gate_blocked:not_live': '服务当前不在实时下单阶段',
    'execution_gate_blocked:open_rate_limit': '60 秒开仓请求达到限速上限；本单保留等待重试',
    'execution_gate_blocked:broker_error': 'MT5 订单检查、发送或成交对账失败；本单保留等待核对',
    signal_expired_no_copy: '信号到达执行器时已超过该账户允许延迟',
    client_not_in_current_pool: '客户已不在当前池中',
  } as Record<string, string>
  return labels[text] || text || '已通过'
}

export function eventExecutionLabel(row: Record<string, unknown>): string {
  const decision = String(row.decision || '').trim()
  const reasonCode = String(row.reasonCode || '').trim()
  const phase = String(row.phase || '').trim()
  if (phase === 'pool_rebuild_failed') {
    return '未跟单：客户池重建失败，执行暂停，目标手数为 0'
  }
  if (phase === 'pool_rebuilding') {
    return '未跟单：客户池正在重建，执行暂停，目标手数为 0'
  }
  if (['shadow', 'recovery_shadow'].includes(phase)) {
    return `未跟单：${phaseLabel(phase)}阶段禁止新增仓位，目标手数为 0`
  }
  if (phase === 'armed_waiting_autotrading') {
    return '未跟单：MT5 自动交易未就绪，目标手数为 0'
  }
  if (decision === 'active' && Math.abs(Number(row.desiredTargetLots) || 0) > 1e-9) {
    return '跟单成功'
  }
  if (reasonCode) {
    return `未跟单：${copyReasonLabel(reasonCode)}`
  }
  if (decision === 'risk_rejected'
    && Math.abs(Number(row.desiredTargetLots) || 0) <= 1e-9
    && Math.abs(Number(row.rawTargetLots) || 0) > 1e-9
    && Math.abs(Number(row.rawTargetLots) || 0) < 0.01) {
    return '未跟单：目标手数低于最小手'
  }
  if (decision === 'monitor') {
    return '未跟单：当时仅监控；旧事件未保存具体子原因'
  }
  if (!decision) {
    return '未跟单：旧事件未保存执行结果'
  }
  return `未跟单：${copyReasonLabel(decision)}`
}

export function eventPoolTier(row: Record<string, unknown>, currentTier: PoolTierTab): PoolTierTab {
  const decision = String(row.decision || '').trim()
  const phase = String(row.phase || '').trim()
  if (['pool_rebuild_failed', 'pool_rebuilding', 'shadow', 'recovery_shadow', 'armed_waiting_autotrading'].includes(phase)) {
    return phase === 'recovery_shadow' ? 'recovery_shadow' : 'execution_suspended'
  }
  if (decision === 'monitor' || decision === 'legacy_monitor_only') return 'monitor'
  if (decision === 'risk_rejected') return 'hard_rejected'
  return currentTier
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
