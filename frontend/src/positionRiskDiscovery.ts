export function positionRiskAccountHref(row: any): string {
  const query = new URLSearchParams()
  if (row?.platform) query.set('platform', String(row.platform))
  if (row?.server) query.set('server', String(row.server))
  const suffix = query.toString()
  return `/account/${encodeURIComponent(String(row?.account || ''))}${suffix ? `?${suffix}` : ''}`
}

export function filterPositionRiskResults(rows: any[] | undefined, level: string): any[] {
  const minimum = ({ all: 0, concern: 40, warning: 60, high: 75, severe: 90 } as Record<string, number>)[level] ?? 60
  return (rows || []).filter(row => Number(row?.score || 0) >= minimum)
}

export function sortPositionRiskResults(rows: any[] | undefined, sortBy: string): any[] {
  const field = ({ profit: 'netProfit', position: 'marginRatio', score: 'score' } as Record<string, string>)[sortBy] || 'score'
  return [...(rows || [])].sort((left, right) => {
    const difference = Number(right?.[field] ?? Number.NEGATIVE_INFINITY) - Number(left?.[field] ?? Number.NEGATIVE_INFINITY)
    if (difference) return difference
    const scoreDifference = Number(right?.score || 0) - Number(left?.score || 0)
    if (scoreDifference) return scoreDifference
    return String(left?.account || '').localeCompare(String(right?.account || ''), 'zh-CN', { numeric: true })
  })
}

export function positionClassificationLabel(value: unknown): string {
  return ({
    weekend: '周末持仓',
    open: '开盘重仓',
    combined: '周末 + 重开加仓',
    none: '未形成事件',
  } as Record<string, string>)[String(value || '')] || String(value || '-')
}
