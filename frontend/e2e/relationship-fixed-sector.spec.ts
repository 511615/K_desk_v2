import { expect, test } from '@playwright/test'

type FixedSectorFrame = {
  revision: number
  inProgress: boolean
  zoom: { scale: number; min: number; max: number }
  path: string[]
  layers: Array<{
    index: number
    focusAccountId: string
    scale: number
    nested: boolean
    hostSector: string
    centerX: number
    centerY: number
    anchorX: number
    anchorY: number
    localRadius: number
    fitsHost: boolean
  }>
  nodes: Array<{ layer: number; accountId: string; nodeType: string; sector: string; role: string; x: number; y: number; radius: number; visualRadius: number }>
  edges: Array<{ layer: number; id: string; type: string; sector: string }>
  sectors: Array<{ layer: number; id: string; accounts: number; evidence: number; x: number; y: number; expanded: boolean }>
  locatorAccountIds: string[]
}

declare global {
  interface Window {
    __kdeskFixedSectorTestFrame?: () => FixedSectorFrame
  }
}

test('fixed-sector preserves outer layer while a direct account opens a scaled nested layer', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  const relationshipRequests: string[] = []
  page.on('request', request => {
    if (request.url().includes('/relationship-network?')) relationshipRequests.push(request.url())
  })

  await page.goto('/kuzu-risk?account=216056&platform=MT5&server=AC%20CN%20MT5&graph_type=fixed-sector')
  await expect(page.locator('#overview')).toBeVisible()
  await expect.poll(
    () => page.evaluate(() => {
      const frame = window.__kdeskFixedSectorTestFrame?.()
      return Boolean(frame && !frame.inProgress && frame.layers.length === 1 && frame.nodes.some(node => node.layer === 0 && node.role === 'direct'))
    }),
    { timeout: 60_000 },
  ).toBe(true)

  const before = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())
  const subjectId = await page.evaluate(() => String((data?.entities ?? []).find((node: { isSubject?: boolean }) => node.isSubject)?.id ?? ''))
  expect(before?.layers[0]?.focusAccountId).toBe(subjectId)
  const allAccountIds = await page.evaluate(() => [...new Set((data?.entities ?? []).filter((node: { type: string }) => node.type === 'account').map((node: { id: string }) => String(node.id)))])
  expect(new Set(before?.locatorAccountIds).size).toBe(allAccountIds.length)

  // The fixed-area renderer is a navigable world, not a bounded magnifier.
  // Both directions must pass the legacy Galaxy 10%-250% limits while every
  // sector/node keeps the same world-space projection.
  await page.evaluate(() => {
    const canvas = document.getElementById('overview')!
    const rect = canvas.getBoundingClientRect()
    for (let index = 0; index < 18; index += 1) {
      canvas.dispatchEvent(new WheelEvent('wheel', {
        bubbles: true, cancelable: true, deltaY: -120,
        clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2,
      }))
    }
  })
  await expect.poll(() => page.evaluate(() => window.__kdeskFixedSectorTestFrame?.().zoom.scale ?? 0)).toBeGreaterThan(2.5)
  await page.evaluate(() => {
    const canvas = document.getElementById('overview')!
    const rect = canvas.getBoundingClientRect()
    for (let index = 0; index < 48; index += 1) {
      canvas.dispatchEvent(new WheelEvent('wheel', {
        bubbles: true, cancelable: true, deltaY: 120,
        clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2,
      }))
    }
  })
  await expect.poll(() => page.evaluate(() => window.__kdeskFixedSectorTestFrame?.().zoom.scale ?? 1)).toBeLessThan(0.1)
  await page.evaluate(() => {
    const canvas = document.getElementById('overview')!
    canvas.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }))
  })
  await expect.poll(() => page.evaluate(() => window.__kdeskFixedSectorTestFrame?.().zoom.scale ?? 0)).toBeGreaterThan(0.1)

  const sector = before!.sectors.find(item => item.layer === 0 && item.evidence > 0 && item.accounts > 0)
  expect(sector).toBeTruthy()
  await page.evaluate(({ x, y }) => {
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: rect.left + x, clientY: rect.top + y }))
  }, sector!)
  await expect.poll(() => page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().sectors.some(item => item.layer === 0 && item.id === id && item.expanded) ?? false, sector!.id)).toBe(true)
  await expect.poll(() => page.evaluate(() => (window.__kdeskFixedSectorTestFrame?.().edges ?? []).some(edge => edge.layer === 0))).toBe(true)

  const direct = await page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().nodes.find(node => node.layer === 0 && node.sector === id && node.role === 'direct' && node.nodeType === 'account'), sector!.id)
  expect(direct).toBeTruthy()
  const childLabel = await page.evaluate(id => String((data?.entities ?? []).find((node: { id: string }) => String(node.id) === id)?.label ?? ''), direct!.accountId)
  const requestCountBeforeDrill = relationshipRequests.length
  await page.evaluate(({ x, y }) => {
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: rect.left + x, clientY: rect.top + y }))
  }, direct!)
  await expect.poll(() => page.evaluate(id => {
    const frame = window.__kdeskFixedSectorTestFrame?.()
    return Boolean(frame && frame.layers.length === 2 && frame.layers[0]?.focusAccountId && frame.layers[1]?.focusAccountId === id && frame.nodes.some(node => node.layer === 0) && frame.nodes.some(node => node.layer === 1))
  }, direct!.accountId)).toBe(true)
  expect(relationshipRequests).toHaveLength(requestCountBeforeDrill)

  const nested = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())
  expect(nested?.layers[0]?.focusAccountId).toBe(subjectId)
  expect(nested?.layers[1]?.scale ?? 1).toBeLessThan(nested?.layers[0]?.scale ?? 0)
  expect(nested?.layers[1]?.nested).toBe(true)
  expect(nested?.layers[1]?.hostSector).toBe(sector!.id)
  expect(nested?.path).toEqual([subjectId, direct!.accountId])
  // A drilled account is the centre of its own local relationship space.
  // It must not inherit the original problem account's canvas centre.
  expect(nested?.layers[1]?.centerX).toBeCloseTo(direct!.x, 0)
  expect(nested?.layers[1]?.centerY).toBeCloseTo(direct!.y, 0)
  expect(nested?.layers[1]?.anchorX).toBeCloseTo(direct!.x, 0)
  expect(nested?.layers[1]?.anchorY).toBeCloseTo(direct!.y, 0)
  expect(nested?.layers[1]?.localRadius ?? 0).toBeGreaterThan(10)
  expect(nested?.layers[1]?.fitsHost).toBe(true)
  for (const layer of nested?.layers ?? []) {
    const directNodes = (nested?.nodes ?? []).filter(node => node.layer === layer.index && node.role === 'direct')
    for (let left = 0; left < directNodes.length; left += 1) {
      for (let right = left + 1; right < directNodes.length; right += 1) {
        const a = directNodes[left], b = directNodes[right]
        if (a.sector !== b.sector) continue
        expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(10)
        expect(Math.hypot(a.x - b.x, a.y - b.y) - a.visualRadius - b.visualRadius).toBeGreaterThanOrEqual(0)
      }
    }
  }
  await expect(page.locator('#selected')).toContainText(childLabel)
  await expect(page.locator('#overviewNote')).toContainText('子扇区嵌入母扇区')

  const screenshot = testInfo.outputPath('fixed-sector-nested-relationship-network.png')
  await page.screenshot({ path: screenshot, fullPage: true })
  await testInfo.attach('fixed-sector-nested-relationship-network', { path: screenshot, contentType: 'image/png' })
})
