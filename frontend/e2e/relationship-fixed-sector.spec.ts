import { expect, test } from '@playwright/test'

type FixedSectorFrame = {
  revision: number
  inProgress: boolean
  focusAccountId: string
  expandedSector: string
  nodes: Array<{ accountId: string; nodeType: string; sector: string; x: number; y: number }>
  edges: Array<{ id: string; type: string; sector: string }>
  sectors: Array<{ id: string; accounts: number; accountIds: string[]; evidence: number; x: number; y: number; expanded: boolean }>
  locatorAccountIds: string[]
}

declare global {
  interface Window {
    __kdeskFixedSectorTestFrame?: () => FixedSectorFrame
  }
}

test('fixed-sector account route activates the fixed-area relationship projection', async ({ page }, testInfo) => {
  test.setTimeout(90_000)

  await page.goto('/kuzu-risk?account=216056&platform=MT5&server=AC%20CN%20MT5&graph_type=fixed-sector')
  await expect(page.locator('#overview')).toBeVisible()
  await expect.poll(
    () => page.evaluate(() => {
      const frame = window.__kdeskFixedSectorTestFrame?.()
      return Boolean(frame && frame.focusAccountId && frame.nodes.some(node => node.sector !== 'center'))
    }),
    { timeout: 60_000 },
  ).toBe(true)

  const frame = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())
  const subjectId = await page.evaluate(() => String((data?.entities ?? []).find((node: { isSubject?: boolean }) => node.isSubject)?.id ?? ''))
  expect(frame?.focusAccountId).toBe(subjectId)
  expect(frame?.nodes.some(node => node.sector === 'center')).toBe(true)
  const allAccountIds = await page.evaluate(() => [...new Set((data?.entities ?? []).filter((node: { type: string }) => node.type === 'account').map((node: { id: string }) => String(node.id)))])
  expect(new Set(frame?.locatorAccountIds).size).toBe(allAccountIds.length)
  const accountEntityIds = new Set(await page.evaluate(() => (data?.entities ?? []).filter((node: { type: string }) => node.type === 'account').map((node: { id: string }) => String(node.id))))
  const sector = frame!.sectors.find(item => item.evidence > 0 && item.accountIds.some(id => accountEntityIds.has(id)))
  expect(sector).toBeTruthy()

  await page.evaluate(({ x, y }) => {
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: rect.left + x, clientY: rect.top + y }))
  }, sector!)
  await expect.poll(() => page.evaluate(() => window.__kdeskFixedSectorTestFrame?.().expandedSector ?? '')).toBe(sector!.id)
  await expect.poll(() => page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().nodes.some(node => node.sector === id) ?? false, sector!.id)).toBe(true)

  const child = await page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().nodes.find(node => node.sector === id && node.nodeType === 'account'), sector!.id)
  expect(child).toBeTruthy()
  const childLabel = await page.evaluate(id => String((data?.entities ?? []).find((node: { id: string }) => String(node.id) === id)?.label ?? ''), child!.accountId)
  await page.evaluate(({ x, y }) => {
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: rect.left + x, clientY: rect.top + y }))
  }, child!)
  await expect.poll(() => page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().focusAccountId ?? '', child!.accountId)).toBe(child!.accountId)
  await expect(page.locator('#selected')).toContainText(childLabel)
  await expect(page.locator('#overviewNote')).toContainText('点击扇区')

  const screenshot = testInfo.outputPath('fixed-sector-relationship-network.png')
  await page.screenshot({ path: screenshot, fullPage: true })
  await testInfo.attach('fixed-sector-relationship-network', { path: screenshot, contentType: 'image/png' })
})
