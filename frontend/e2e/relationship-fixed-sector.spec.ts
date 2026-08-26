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
    availableRadius: number
    fitsHost: boolean
    geometryScale: number
  }>
  nodes: Array<{ layer: number; accountId: string; instanceId: string; nodeType: string; sector: string; role: string; x: number; y: number; radius: number; visualRadius: number; drillable: boolean }>
  edges: Array<{ layer: number; id: string; type: string; sector: string; visualWidth: number }>
  sectors: Array<{ layer: number; id: string; accounts: number; evidence: number; x: number; y: number; safeX: number; safeY: number; expanded: boolean; visualStroke: number }>
  locatorAccountIds: string[]
}

declare global {
  interface Window {
    __kdeskFixedSectorTestFrame?: () => FixedSectorFrame
    __kdeskFixedSectorTestExpand?: (layer: number, sectorId: string) => void
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
  }, { x: sector!.safeX, y: sector!.safeY })
  await expect.poll(() => page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().sectors.some(item => item.layer === 0 && item.id === id && item.expanded) ?? false, sector!.id)).toBe(true)
  await expect.poll(() => page.evaluate(() => (window.__kdeskFixedSectorTestFrame?.().edges ?? []).some(edge => edge.layer === 0))).toBe(true)

  const direct = await page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().nodes.find(node => node.layer === 0 && node.sector === id && node.role === 'direct' && node.nodeType === 'account'), sector!.id)
  expect(direct).toBeTruthy()
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

  let nested = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())
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
  expect(nested?.layers[1]?.geometryScale ?? 1).toBeLessThan(nested?.layers[0]?.geometryScale ?? 0)
  const outerRadius = Math.max(...(nested?.nodes ?? []).filter(node => node.layer === 0 && node.role === 'direct').map(node => node.visualRadius))
  const childRadius = Math.max(...(nested?.nodes ?? []).filter(node => node.layer === 1 && node.role === 'direct').map(node => node.visualRadius))
  expect(childRadius).toBeLessThan(outerRadius)
  for (const layer of nested?.layers ?? []) {
    const directNodes = (nested?.nodes ?? []).filter(node => node.layer === layer.index && node.role === 'direct')
    for (let left = 0; left < directNodes.length; left += 1) {
      for (let right = left + 1; right < directNodes.length; right += 1) {
        const a = directNodes[left], b = directNodes[right]
        if (a.sector !== b.sector) continue
        // Nested maps may be deliberately tiny and inspected through canvas
        // zoom, so the invariant is visible non-overlap rather than a fixed
        // screen-pixel distance.
        expect(Math.hypot(a.x - b.x, a.y - b.y) - a.visualRadius - b.visualRadius).toBeGreaterThanOrEqual(0)
      }
    }
  }

  // Expand one non-empty child sector so its concrete evidence edges are
  // painted before checking the common canvas zoom transform.
  const nestedEvidenceSector = (nested?.sectors ?? []).find(item => item.layer === 1 && item.evidence > 0)
  expect(nestedEvidenceSector).toBeTruthy()
  await page.evaluate(({ layer, sectorId }) => window.__kdeskFixedSectorTestExpand?.(layer, sectorId), {
    layer: nestedEvidenceSector!.layer,
    sectorId: nestedEvidenceSector!.id,
  })
  await expect.poll(() => page.evaluate(id => window.__kdeskFixedSectorTestFrame?.().sectors.some(item => item.layer === 1 && item.id === id && item.expanded) ?? false, nestedEvidenceSector!.id)).toBe(true)
  await expect.poll(() => page.evaluate(() => (window.__kdeskFixedSectorTestFrame?.().edges ?? []).some(edge => edge.layer === 1))).toBe(true)
  nested = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())

  // A second direct account click keeps both existing spaces and creates the
  // next local scale, unless this account has genuinely stopped at threshold.
  // The canvas zoom is one affine transform: sector borders, relation lines,
  // account marks and their hit targets must grow/shrink together.
  const zoomProbe = (nested?.nodes ?? []).find(node => node.layer === 1 && node.role === 'direct')
  const strokeProbe = (nested?.sectors ?? []).find(item => item.layer === 1)
  const edgeProbe = (nested?.edges ?? []).find(item => item.layer === 1)
  // Zoom around a real next-layer account. This matches ordinary pointer
  // zooming: the intended target remains under the pointer and must still be
  // selectable after all geometry has been scaled.
  const nestedDirect = (nested?.nodes ?? [])
    .filter(node => node.layer === 1 && node.role === 'direct' && node.nodeType === 'account' && node.drillable)
    .sort((left, right) => right.y - left.y)[0]
  expect(zoomProbe).toBeTruthy()
  expect(strokeProbe).toBeTruthy()
  expect(edgeProbe).toBeTruthy()
  expect(nestedDirect).toBeTruthy()
  const zoomBefore = nested!.zoom.scale
  await page.evaluate(({ x, y }) => {
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    for (let index = 0; index < 5; index += 1) canvas.dispatchEvent(new WheelEvent('wheel', {
      bubbles: true, cancelable: true, deltaY: -120, clientX: rect.left + x, clientY: rect.top + y,
    }))
  }, nestedDirect!)
  const zoomed = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())
  const zoomRatio = zoomed!.zoom.scale / zoomBefore
  const zoomedProbe = zoomed!.nodes.find(node => node.instanceId === zoomProbe!.instanceId)!
  const zoomedStroke = zoomed!.sectors.find(item => item.layer === strokeProbe!.layer && item.id === strokeProbe!.id)!
  const zoomedEdge = zoomed!.edges.find(item => item.layer === edgeProbe!.layer && item.id === edgeProbe!.id)!
  expect(zoomed!.zoom.scale).toBeGreaterThan(zoomBefore)
  expect(zoomedProbe.visualRadius / zoomProbe!.visualRadius).toBeCloseTo(zoomRatio, 1)
  expect(zoomedStroke.visualStroke / strokeProbe!.visualStroke).toBeCloseTo(zoomRatio, 1)
  expect(zoomedEdge.visualWidth / edgeProbe!.visualWidth).toBeCloseTo(zoomRatio, 1)

  const zoomedNestedDirect = zoomed!.nodes.find(node => node.instanceId === nestedDirect!.instanceId)
  expect(zoomedNestedDirect).toBeTruthy()
  await page.evaluate(({ x, y }) => {
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: rect.left + x, clientY: rect.top + y }))
  }, zoomedNestedDirect!)
  await expect.poll(() => page.evaluate(id => {
    const frame = window.__kdeskFixedSectorTestFrame?.()
    return Boolean(frame && frame.layers.length === 3 && frame.layers[2]?.focusAccountId === id && frame.nodes.some(node => node.layer === 2))
  }, nestedDirect!.accountId)).toBe(true)
  const deeper = await page.evaluate(() => window.__kdeskFixedSectorTestFrame?.())
  expect(deeper?.layers[2]?.geometryScale ?? 1).toBeLessThan(deeper?.layers[1]?.geometryScale ?? 0)
  expect(deeper?.nodes.some(node => node.layer === 0)).toBe(true)
  expect(deeper?.nodes.some(node => node.layer === 1)).toBe(true)
  const nestedChildLabel = await page.evaluate(id => String((data?.entities ?? []).find((node: { id: string }) => String(node.id) === id)?.label ?? ''), nestedDirect!.accountId)
  await expect(page.locator('#selected')).toContainText(nestedChildLabel)
  await expect(page.locator('#overviewNote')).toContainText('子扇区嵌入母扇区')

  const screenshot = testInfo.outputPath('fixed-sector-nested-relationship-network.png')
  await page.screenshot({ path: screenshot, fullPage: true })
  await testInfo.attach('fixed-sector-nested-relationship-network', { path: screenshot, contentType: 'image/png' })
})
