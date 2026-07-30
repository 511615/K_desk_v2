import { describe, expect, it } from 'vitest'
import { frontendEntryAsset, frontendNeedsReload } from './frontendUpdate'

describe('frontend deployment update detection', () => {
  it('extracts the hashed Vue entry asset', () => {
    expect(frontendEntryAsset('<script src="/assets/index-Ab_12-CD.js"></script>')).toBe('index-Ab_12-CD.js')
  })

  it('reloads only when the deployed entry hash changes', () => {
    expect(frontendNeedsReload('index-old.js', '<script src="/assets/index-new.js"></script>')).toBe(true)
    expect(frontendNeedsReload('index-same.js', '<script src="/assets/index-same.js"></script>')).toBe(false)
    expect(frontendNeedsReload('index-old.js', '<html></html>')).toBe(false)
  })
})
