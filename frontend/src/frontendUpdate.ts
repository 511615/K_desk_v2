const ENTRY_ASSET_PATTERN = /assets\/(index-[A-Za-z0-9_-]+\.js)/

export function frontendEntryAsset(html: string): string {
  return ENTRY_ASSET_PATTERN.exec(String(html || ''))?.[1] || ''
}

export function frontendNeedsReload(currentAsset: string, latestHtml: string): boolean {
  const latestAsset = frontendEntryAsset(latestHtml)
  return Boolean(currentAsset && latestAsset && currentAsset !== latestAsset)
}

export function startFrontendUpdateMonitor(reload: () => void, intervalMs = 15_000): () => void {
  const currentAsset = frontendEntryAsset(document.documentElement.outerHTML)
  if (!currentAsset) return () => undefined
  let stopped = false
  let checking = false
  const check = async () => {
    if (stopped || checking) return
    checking = true
    try {
      const response = await fetch('/?frontend-version=1', { cache: 'no-store' })
      if (response.ok && frontendNeedsReload(currentAsset, await response.text())) reload()
    } catch {
      // The job polling layer handles service downtime; version checks are best-effort.
    } finally {
      checking = false
    }
  }
  const timer = window.setInterval(check, intervalMs)
  window.addEventListener('focus', check)
  return () => {
    stopped = true
    window.clearInterval(timer)
    window.removeEventListener('focus', check)
  }
}
