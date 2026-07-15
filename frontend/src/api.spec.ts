import { describe, expect, it } from 'vitest'
import { queryString } from './api'

describe('queryString', () => {
  it('preserves account filter parameters and omits empty values', () => {
    expect(queryString({ platform: 'MT5', server: 'DBG MT5', symbol: '' })).toBe('?platform=MT5&server=DBG+MT5')
  })
})
