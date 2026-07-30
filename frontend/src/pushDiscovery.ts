export const PUSH_JOB_STORAGE_KEY = 'kdesk.pushDiscovery.jobId'

export function recoverPushPollingState(current: any, error: unknown, attempt: number): any {
  const message = error instanceof Error && error.message ? error.message : '无法连接任务服务'
  return {
    ...(current || {}),
    status: current?.status === 'queued' ? 'queued' : 'running',
    error: '',
    connectionError: `连接暂时中断，正在重试（${attempt}）`,
    connectionDetail: message,
  }
}

export function pushPollRetryDelay(attempt: number): number {
  return Math.min(1200 + Math.max(attempt - 1, 0) * 800, 5000)
}

export function loadPushJobId(storage: Pick<Storage, 'getItem'>): string {
  try {
    return String(storage.getItem(PUSH_JOB_STORAGE_KEY) || '').trim()
  } catch {
    return ''
  }
}

export function savePushJobId(storage: Pick<Storage, 'setItem'>, id: unknown): void {
  const value = String(id || '').trim()
  if (!value) return
  try {
    storage.setItem(PUSH_JOB_STORAGE_KEY, value)
  } catch {
    // The durable server job still runs when browser storage is unavailable.
  }
}
