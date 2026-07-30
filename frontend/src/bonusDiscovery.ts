export function bonusLevelRank(value: unknown): number {
  return ({
    '无明显风险': 0,
    '关注': 1,
    '预警': 2,
    '高危形态': 3,
    '严重形态': 4,
  } as Record<string, number>)[String(value || '')] ?? 0
}

export function filterBonusResults(rows: unknown, minimum: string): any[] {
  const values = Array.isArray(rows) ? rows : []
  const threshold = ({ all: 0, concern: 1, warning: 2, high: 3, severe: 4 } as Record<string, number>)[minimum] ?? 2
  return values.filter(row => bonusLevelRank(row?.level) >= threshold)
}

export function bonusAccountHref(row: any): string {
  const query = new URLSearchParams()
  if (row?.platform) query.set('platform', String(row.platform))
  if (row?.server) query.set('server', String(row.server))
  const suffix = query.toString()
  return `/account/${encodeURIComponent(String(row?.account || ''))}${suffix ? `?${suffix}` : ''}`
}

export function bonusPeakOrders(row: any): any[] {
  if (Array.isArray(row?.bestCycle?.minimumMarginOrders)) return row.bestCycle.minimumMarginOrders
  return Array.isArray(row?.bestCycle?.earlyPeakOrders) ? row.bestCycle.earlyPeakOrders : []
}

export function bonusHedgeFinding(row: any): { found: boolean; matches: number; coverage: number; accounts: string[]; details: any[] } {
  const peer = row?.bestCycle?.peerMatch || {}
  const matches = Math.max(Number(peer.matches) || 0, 0)
  return {
    found: matches > 0,
    matches,
    coverage: Math.max(Number(peer.lotCoverage) || 0, 0),
    accounts: Array.isArray(peer.accounts) ? peer.accounts.map(String) : [],
    details: Array.isArray(peer.details) ? peer.details : [],
  }
}
