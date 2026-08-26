import { expect, test } from '@playwright/test'

type CanvasArc = {
  x: number
  y: number
  radius: number
  start: number
  end: number
  stroke: string
  transform: { a: number; b: number; c: number; d: number; e: number; f: number }
}

type CanvasCurve = {
  from: { x: number; y: number } | null
  control: { x: number; y: number }
  to: { x: number; y: number }
  stroke: string
  transform: { a: number; b: number; c: number; d: number; e: number; f: number }
}

type CanvasText = {
  text: string
  x: number
  y: number
  curveIndex: number
}

type GalaxyProbe = {
  arcs: CanvasArc[]
  curves: CanvasCurve[]
  texts: CanvasText[]
  cursor: { x: number; y: number } | null
}

type GalaxyTestFrame = {
  revision: number
  inProgress: boolean
  edges: Array<{
    id: string
    type: string
    from: { x: number; y: number }
    control: { x: number; y: number }
    to: { x: number; y: number }
  }>
}

declare global {
  interface Window {
    __kdeskGalaxyProbe?: GalaxyProbe
    __kdeskGalaxyTestFrame?: () => GalaxyTestFrame
  }
}

function cssPoint(
  point: { x: number; y: number },
  transform: CanvasArc['transform'],
  devicePixelRatio: number,
): { x: number; y: number } {
  return {
    x: (transform.a * point.x + transform.c * point.y + transform.e) / devicePixelRatio,
    y: (transform.b * point.x + transform.d * point.y + transform.f) / devicePixelRatio,
  }
}

test('Galaxy keeps cross-community relationships collapsed while a same-CRM band is expanded', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  await page.route('**/kuzu-risk*', async route => {
    const response = await route.fetch()
    const html = await response.text()
    const testBridge = `<script>window.__kdeskGalaxyTestFrame=()=>{const project=point=>({x:view.x+point.x*view.scale,y:view.y+point.y*view.scale}),edges=(relationHitEdges||[]).map(edge=>{const route=relationRoute(edge);return route?{id:String(edge.id||''),type:String(edge.type||''),from:project(route.from),control:project(route.control),to:project(route.to)}:null}).filter(Boolean);return{revision:Number(data?.revision||0),inProgress:Boolean(data?.inProgress),edges}};</script>`
    await route.fulfill({ response, body: html.replace('</body>', `${testBridge}</body>`) })
  })
  await page.addInitScript(() => {
    const probeWindow = window as Window
    const newProbe = (): GalaxyProbe => ({ arcs: [], curves: [], texts: [], cursor: null })
    probeWindow.__kdeskGalaxyProbe = newProbe()
    const context = CanvasRenderingContext2D.prototype
    const originalFillRect = context.fillRect
    const originalMoveTo = context.moveTo
    const originalArc = context.arc
    const originalQuadraticCurveTo = context.quadraticCurveTo
    const originalFillText = context.fillText
    context.fillRect = function (...args: Parameters<CanvasRenderingContext2D['fillRect']>) {
      if (this.canvas.id === 'overview' && args[0] === 0 && args[1] === 0) {
        probeWindow.__kdeskGalaxyProbe = newProbe()
      }
      return originalFillRect.apply(this, args)
    }
    context.moveTo = function (...args: Parameters<CanvasRenderingContext2D['moveTo']>) {
      if (this.canvas.id === 'overview') {
        const probe = probeWindow.__kdeskGalaxyProbe ?? newProbe()
        probe.cursor = { x: args[0], y: args[1] }
        probeWindow.__kdeskGalaxyProbe = probe
      }
      return originalMoveTo.apply(this, args)
    }
    context.arc = function (...args: Parameters<CanvasRenderingContext2D['arc']>) {
      if (this.canvas.id === 'overview') {
        const probe = probeWindow.__kdeskGalaxyProbe ?? newProbe()
        const matrix = this.getTransform()
        probe.arcs.push({
          x: args[0],
          y: args[1],
          radius: args[2],
          start: args[3],
          end: args[4],
          stroke: String(this.strokeStyle),
          transform: { a: matrix.a, b: matrix.b, c: matrix.c, d: matrix.d, e: matrix.e, f: matrix.f },
        })
        probeWindow.__kdeskGalaxyProbe = probe
      }
      return originalArc.apply(this, args)
    }
    context.quadraticCurveTo = function (...args: Parameters<CanvasRenderingContext2D['quadraticCurveTo']>) {
      if (this.canvas.id === 'overview') {
        const probe = probeWindow.__kdeskGalaxyProbe ?? newProbe()
        const matrix = this.getTransform()
        probe.curves.push({
          from: probe.cursor,
          control: { x: args[0], y: args[1] },
          to: { x: args[2], y: args[3] },
          stroke: String(this.strokeStyle),
          transform: { a: matrix.a, b: matrix.b, c: matrix.c, d: matrix.d, e: matrix.e, f: matrix.f },
        })
        probe.cursor = { x: args[2], y: args[3] }
        probeWindow.__kdeskGalaxyProbe = probe
      }
      return originalQuadraticCurveTo.apply(this, args)
    }
    context.fillText = function (...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.id === 'overview') {
        const probe = probeWindow.__kdeskGalaxyProbe ?? newProbe()
        probe.texts.push({ text: String(args[0]), x: args[1], y: args[2], curveIndex: probe.curves.length - 1 })
        probeWindow.__kdeskGalaxyProbe = probe
      }
      return originalFillText.apply(this, args)
    }
  })

  const response = await page.goto('/kuzu-risk?account=216056&graph_type=galaxy')
  expect(response?.status()).toBe(200)
  const overview = page.locator('#overview')
  await expect(overview).toBeVisible()
  await expect
    .poll(
      async () => Number((await page.locator('#galaxyLocatorCount').textContent())?.match(/\d+/)?.[0] ?? 0),
      { timeout: 60_000 },
    )
    .toBeGreaterThanOrEqual(15)
  await expect
    .poll(
      () => page.evaluate(() => (window.__kdeskGalaxyProbe?.arcs ?? []).filter(arc =>
        arc.stroke === '#60a5fa' && arc.radius > 30 && Math.abs(arc.end - arc.start) > 0.2 && Math.abs(arc.end - arc.start) < 6,
      ).length),
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0)

  const before = await page.evaluate(() => window.__kdeskGalaxyProbe)
  const initialScreenshot = testInfo.outputPath('galaxy-collapsed-community.png')
  await page.screenshot({ path: initialScreenshot, fullPage: true })
  await testInfo.attach('galaxy-collapsed-community', { path: initialScreenshot, contentType: 'image/png' })
  expect(before?.curves.length ?? 0).toBeGreaterThan(0)
  const devicePixelRatio = await page.evaluate(() => window.devicePixelRatio)
  const initialAccountLabels = (before?.texts ?? []).filter(item => /^\d+$/.test(item.text)).length
  const sameCrmBand = [...(before?.arcs ?? [])]
    .filter(arc => arc.stroke === '#60a5fa' && arc.radius > 30 && Math.abs(arc.end - arc.start) > 0.2 && Math.abs(arc.end - arc.start) < 6)
    .sort((left, right) => right.radius - left.radius)[0]
  expect(sameCrmBand).toBeTruthy()
  const bandMidpoint = {
    x: sameCrmBand!.x + sameCrmBand!.radius * Math.cos((sameCrmBand!.start + sameCrmBand!.end) / 2),
    y: sameCrmBand!.y + sameCrmBand!.radius * Math.sin((sameCrmBand!.start + sameCrmBand!.end) / 2),
  }
  await overview.click({ position: cssPoint(bandMidpoint, sameCrmBand!.transform, devicePixelRatio) })
  await expect
    .poll(() => page.evaluate(() => (window.__kdeskGalaxyProbe?.texts ?? []).filter(item => /^\d+$/.test(item.text)).length))
    .toBeGreaterThan(initialAccountLabels)

  const expanded = await page.evaluate(() => window.__kdeskGalaxyProbe)
  // The clicked five-account CRM community contributes its four internal
  // same-CRM links.  No LastIP, IB, rebate, EA, or copy lines are emitted.
  expect((expanded?.curves.length ?? 0) - (before?.curves.length ?? 0)).toBeLessThanOrEqual(4)
  const expandedScreenshot = testInfo.outputPath('galaxy-expanded-community.png')
  await page.screenshot({ path: expandedScreenshot, fullPage: true })
  await testInfo.attach('galaxy-expanded-community', { path: expandedScreenshot, contentType: 'image/png' })

  await expect
    .poll(async () => {
      const response = await page.request.get('/api/accounts/by-login/216056/relationship-network?threshold=20')
      return Boolean((await response.json()).inProgress)
    }, { timeout: 50_000 })
    .toBe(false)
  const completedGraph = await (await page.request.get('/api/accounts/by-login/216056/relationship-network?threshold=20')).json()
  const completedAccounts = (completedGraph.entities ?? []).filter((entity: { type: string }) => entity.type === 'account').length
  await expect
    .poll(
      async () => Number((await page.locator('#galaxyLocatorCount').textContent())?.match(/\d+/)?.[0] ?? 0),
      { timeout: 15_000 },
    )
    .toBe(completedAccounts)
  await expect
    .poll(async () => {
      const frame = await page.evaluate(() => window.__kdeskGalaxyTestFrame?.())
      return frame?.revision === completedGraph.revision && !frame.inProgress && frame.edges.some(edge => edge.type === 'ib_direct_account')
    }, { timeout: 15_000 })
    .toBe(true)
  const relationCurve = await page.evaluate(() => window.__kdeskGalaxyTestFrame?.().edges.find(edge => edge.type === 'ib_direct_account'))
  expect(relationCurve).toBeTruthy()
  const curvePoint = {
    x: 0.25 * relationCurve!.from.x + 0.5 * relationCurve!.control.x + 0.25 * relationCurve!.to.x,
    y: 0.25 * relationCurve!.from.y + 0.5 * relationCurve!.control.y + 0.25 * relationCurve!.to.y,
  }
  const edgeClick = curvePoint
  // The canvas is panned/scaled by the browser while this graph is polling.
  // Dispatch at the rendered canvas coordinate so the app's normal canvas
  // event handlers receive the exact relationship-line click without a page
  // scroll or an unrelated document overlay intercepting it.
  await page.evaluate(({ x, y }) => {
    const canvas = document.getElementById('overview')!
    const rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', {
      bubbles: true,
      cancelable: true,
      clientX: rect.left + x,
      clientY: rect.top + y,
    }))
  }, edgeClick)
  const relationDisplay = page.locator('[aria-label="关系展示表"]')
  await expect(relationDisplay).toBeVisible()
  await expect(relationDisplay.locator('h2')).toContainText('关系展示表', { timeout: 20_000 })
  await expect(relationDisplay.locator('h2')).not.toContainText('图谱已更新')
  await expect(relationDisplay.locator('.relation-display-error')).toHaveCount(0)
  const tableScreenshot = testInfo.outputPath('galaxy-relation-display.png')
  await page.screenshot({ path: tableScreenshot, fullPage: true })
  await testInfo.attach('galaxy-relation-display', { path: tableScreenshot, contentType: 'image/png' })
})
