import { describe, expect, it } from 'vitest'
import {
  loadPushJobId,
  PUSH_JOB_STORAGE_KEY,
  pushPollRetryDelay,
  recoverPushPollingState,
  savePushJobId,
} from './pushDiscovery'

describe('push discovery polling recovery', () => {
  it('preserves the durable job identity and progress after a transient fetch failure', () => {
    const state = recoverPushPollingState(
      { id: 'job-123', status: 'running', progress: 72, events: [{ message: '深检 28/100' }] },
      new Error('Failed to fetch'),
      2,
    )

    expect(state.id).toBe('job-123')
    expect(state.progress).toBe(72)
    expect(state.status).toBe('running')
    expect(state.error).toBe('')
    expect(state.connectionError).toContain('正在重试')
    expect(state.connectionDetail).toBe('Failed to fetch')
  })

  it('uses a bounded retry delay', () => {
    expect(pushPollRetryDelay(1)).toBe(1200)
    expect(pushPollRetryDelay(20)).toBe(5000)
  })

  it('persists the durable job id for navigation recovery', () => {
    const values = new Map<string, string>()
    const storage = {
      getItem: (key: string) => values.get(key) || null,
      setItem: (key: string, value: string) => values.set(key, value),
    }

    savePushJobId(storage, 'job-456')

    expect(values.get(PUSH_JOB_STORAGE_KEY)).toBe('job-456')
    expect(loadPushJobId(storage)).toBe('job-456')
  })
})
