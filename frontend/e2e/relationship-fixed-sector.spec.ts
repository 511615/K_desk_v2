import { expect, test } from '@playwright/test'

type FixedSectorFrame = {
  revision: number
  inProgress: boolean
  nodes: Array<{ accountId: string; sector: string }>
  edges: Array<{ id: string; type: string; sector: string }>
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
      return Boolean(frame && frame.nodes.length > 0)
    }),
    { timeout: 60_000 },
  ).toBe(true)

  const frame = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())
  expect(frame?.nodes.some(node => node.sector === 'center')).toBe(true)
  expect(frame?.nodes.some(node => node.sector !== 'center')).toBe(true)
  expect(frame?.edges.every(edge => Boolean(edge.id) && Boolean(edge.sector))).toBe(true)
  await expect(page.locator('#overviewNote')).toContainText('固定区域关系网')

  const screenshot = testInfo.outputPath('fixed-sector-relationship-network.png')
  await page.screenshot({ path: screenshot, fullPage: true })
  await testInfo.attach('fixed-sector-relationship-network', { path: screenshot, contentType: 'image/png' })
})
