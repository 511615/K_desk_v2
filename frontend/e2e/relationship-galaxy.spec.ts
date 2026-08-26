import { expect, test } from '@playwright/test'

type Group = {
  key: string
  type: string
  expanded: boolean
  members: number
  center: { x: number; y: number }
  radius: number
  start: number
  end: number
}

type Edge = {
  id: string
  type: string
  groupKey: string
  point: { x: number; y: number } | null
}

type Frame = {
  revision: number
  inProgress: boolean
  groups: Group[]
  edges: Edge[]
  edgeClickIds: string[]
}

declare global {
  interface Window {
    __kdeskGalaxyLiveFrame?: () => Frame
  }
}

test('Galaxy opens a populated relation table from an expanded same-CRM member line', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  const relationDisplayEdgeIds: string[] = []
  page.on('request', request => {
    const requestUrl = new URL(request.url())
    if (requestUrl.pathname.endsWith('/relationship-network/relation-display')) {
      relationDisplayEdgeIds.push(requestUrl.searchParams.get('edge_id') ?? '')
    }
  })
  await page.route('**/kuzu-risk*', async route => {
    const response = await route.fetch()
    const html = await response.text()
    const bridge = `<script>const kdeskGalaxyEdgeClickIds=[];window.addEventListener('click',event=>{if(event.target?.id!=='overview')return;const rect=event.target.getBoundingClientRect(),hit=galaxyPickHit({x:event.clientX-rect.left,y:event.clientY-rect.top});if(hit.kind==='edge')kdeskGalaxyEdgeClickIds.push(String(hit.target?.id||''))},true);window.__kdeskGalaxyLiveFrame=()=>{const project=point=>({x:view.x+point.x*view.scale,y:view.y+point.y*view.scale}),groups=(galaxyHitFrame?.groups||[]).map(hit=>({key:String(hit.group?.key||''),type:String(hit.group?.type||''),expanded:expandedRelationGroups.has(galaxyTrackToggleKey(hit.group)),members:Number(hit.group?.nodes?.length||0),center:hit.center,radius:Number(hit.radius||0),start:Number(hit.start||0),end:Number(hit.end||0)})),rawIds=new Set((data?.relationships||[]).map(edge=>String(edge.id||''))),edges=(relationHitEdges||[]).filter(edge=>rawIds.has(String(edge.id||''))).map(edge=>{const route=relationRoute(edge);if(!route)return null;const id=String(edge.id||''),groupKey=String(layout.get(edge.from?.id)?.groupKey||layout.get(edge.to?.id)?.groupKey||''),point=[.18,.32,.5,.68,.82].map(t=>project(quadraticPoint(route,t))).find(point=>{const hit=galaxyPickHit(point);return hit.kind==='edge'&&String(hit.target?.id||'')===id})||null;return{id,type:String(edge.type||''),groupKey,point}}).filter(Boolean);return{revision:Number(data?.revision||0),inProgress:Boolean(data?.inProgress),groups,edges,edgeClickIds:kdeskGalaxyEdgeClickIds}};</script>`
    await route.fulfill({ response, body: html.replace('</body>', `${bridge}</body>`) })
  })

  await page.goto('/kuzu-risk?account=216056&graph_type=galaxy')
  const overview = page.locator('#overview')
  await expect(overview).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__kdeskGalaxyLiveFrame?.().groups.some(group => group.type === 'same_crm_user' && !group.expanded && group.members > 1) ?? false), { timeout: 60_000 }).toBe(true)

  const collapsed = await page.evaluate(() => window.__kdeskGalaxyLiveFrame?.())
  const group = collapsed!.groups
    .filter(item => item.type === 'same_crm_user' && !item.expanded && item.members > 1)
    .sort((left, right) => right.radius - left.radius)[0]
  expect(group).toBeTruthy()
  const angle = (group!.start + group!.end) / 2
  await page.evaluate(({ center, radius, angle }) => {
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', {
      bubbles: true, cancelable: true,
      clientX: rect.left + center.x + radius * Math.cos(angle),
      clientY: rect.top + center.y + radius * Math.sin(angle),
    }))
  }, { center: group!.center, radius: group!.radius, angle })
  await expect.poll(() => page.evaluate(groupKey => window.__kdeskGalaxyLiveFrame?.().groups.some(item => item.key === groupKey && item.expanded) ?? false, group!.key)).toBe(true)
  await expect.poll(() => page.evaluate(() => window.__kdeskGalaxyLiveFrame?.().inProgress ?? true), { timeout: 50_000 }).toBe(false)

  await expect.poll(() => page.evaluate(groupKey => window.__kdeskGalaxyLiveFrame?.().edges.some(edge => edge.type === 'same_crm_user' && edge.groupKey === groupKey && edge.point !== null) ?? false, group!.key), { timeout: 15_000 }).toBe(true)
  const clicked = await page.evaluate(groupKey => {
    const rawIds = new Set((data?.relationships || []).map(edge => String(edge.id || '')))
    const candidate = (relationHitEdges || []).filter(edge => rawIds.has(String(edge.id || '')) && String(edge.type || '') === 'same_crm_user').map(edge => {
      const route = relationRoute(edge)
      const groupKeyForEdge = String(layout.get(edge.from?.id)?.groupKey || layout.get(edge.to?.id)?.groupKey || '')
      const point = route && [.18, .32, .5, .68, .82].map(t => ({ x: view.x + quadraticPoint(route, t).x * view.scale, y: view.y + quadraticPoint(route, t).y * view.scale })).find(point => {
        const hit = galaxyPickHit(point)
        return hit.kind === 'edge' && String(hit.target?.id || '') === String(edge.id || '')
      })
      return { edge, groupKeyForEdge, point }
    }).find(item => item.groupKeyForEdge === groupKey && item.point)
    if (!candidate) return null
    const canvas = document.getElementById('overview')!, rect = canvas.getBoundingClientRect()
    canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: rect.left + candidate.point!.x, clientY: rect.top + candidate.point!.y }))
    return { id: String(candidate.edge.id || ''), type: String(candidate.edge.type || '') }
  }, group!.key)
  expect(clicked?.type).toBe('same_crm_user')

  const display = page.locator('[aria-label="关系展示表"]')
  await expect(display).toBeVisible()
  expect((await page.evaluate(() => window.__kdeskGalaxyLiveFrame?.().edgeClickIds ?? []))).toEqual([clicked!.id])
  await expect.poll(() => relationDisplayEdgeIds.length, { timeout: 20_000 }).toBeGreaterThan(0)
  expect(relationDisplayEdgeIds).toEqual([clicked!.id])
  await expect(display.locator('h2')).toContainText('关系展示表', { timeout: 20_000 })
  await expect(display.locator('h2')).toContainText('同名账户')
  await expect(display.locator('h2')).not.toContainText('图谱已更新')
  await expect(display.locator('.relation-display-coverage')).toBeVisible()
  await expect(display.locator('.relation-display-error')).toHaveCount(0)
  const screenshot = testInfo.outputPath('galaxy-expanded-relation-table.png')
  await page.screenshot({ path: screenshot, fullPage: true })
  await testInfo.attach('galaxy-expanded-relation-table', { path: screenshot, contentType: 'image/png' })
})
