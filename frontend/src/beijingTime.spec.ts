import { describe, expect, it } from 'vitest'
import { formatBeijingDateTime, formatBeijingTime } from './beijingTime'

describe('Beijing time formatting', () => {
  it('converts UTC instants to Asia/Shanghai', () => {
    expect(formatBeijingDateTime('2026-08-05T00:28:29Z')).toBe('2026/8/5 08:28:29')
    expect(formatBeijingTime('2026-08-05T00:28:29Z')).toBe('08:28:29')
  })

  it('preserves instants already expressed with the Beijing offset', () => {
    expect(formatBeijingDateTime('2026-08-05T10:06:56+08:00')).toBe('2026/8/5 10:06:56')
  })

  it('returns a placeholder for invalid values', () => {
    expect(formatBeijingDateTime('')).toBe('-')
    expect(formatBeijingTime('not-a-time')).toBe('-')
  })
})
