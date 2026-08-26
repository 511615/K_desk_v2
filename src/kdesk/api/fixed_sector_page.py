from __future__ import annotations

# ACC-REL-001 / ACC-REL-003: presentation-only nested fixed-sector projection.


def fixed_sector_assets() -> str:
    return r'''<script>
const fixedSectorDefinitions=[
  {id:'ip',label:'同 IP',color:'#60a5fa'}, {id:'cid',label:'CID',color:'#a78bfa'},
  {id:'ea',label:'EA',color:'#22d3ee'}, {id:'copy',label:'跟单',color:'#f472b6'},
  {id:'rebate',label:'返佣',color:'#fbbf24'}, {id:'ib',label:'IB / CRM 归属',color:'#818cf8'},
  {id:'sync',label:'开平仓同步',color:'#fb7185'}, {id:'hedge',label:'反向对锁',color:'#f43f5e'},
];
const fixedSectorTypes={same_crm_user:'center',same_name:'center',login_ip:'ip',client_id:'cid',ea_feature:'ea',copy_order:'copy',copy_group:'copy',rebate:'rebate',crm_owner:'ib',direct_ib:'ib',ib_owned_account:'ib',ib_direct_account:'ib',ib_identity:'ib',ib_direct_rebate:'ib',top_ib_group:'ib',toxic_sync_same:'sync',toxic_sync_opposite:'hedge'};
let fixedSectorActive=false,fixedSectorHit={nodes:[],edges:[],sectors:[]},fixedSectorLocatorHits=[],fixedSectorPath=[],fixedSectorExpanded=new Map(),fixedSectorNeedsFit=true,fixedSectorLastLayers=[];
// The fixed-sector graph is a continuous relationship world. Panning has no
// boundary; the broad numeric range only avoids Canvas precision collapse.
const fixedSectorZoomRange={min:.002,max:256};
function fixedSectorZoomBounds(){return fixedSectorZoomRange}

function fixedSectorNodes(){return(data?.entities||[]).filter(node=>node.type==='account'||node.type==='ib_user')}
function fixedSectorRoot(){return fixedSectorNodes().find(node=>node.isSubject)||fixedSectorNodes()[0]||null}
function fixedSectorEnsurePath(){
  if(!data)return;
  const root=fixedSectorRoot(),entities=byId();
  if(!root)return;
  if(!fixedSectorPath.length||!entities.has(fixedSectorPath[0]))fixedSectorPath=[root.id];
  fixedSectorPath=fixedSectorPath.filter(id=>entities.has(id));
  if(!fixedSectorPath.length)fixedSectorPath=[root.id];
}
function fixedSectorCenterIds(focus){
  const entities=byId(),ids=new Set(focus?[focus.id]:[]),queue=focus?[focus.id]:[];
  while(queue.length){
    const id=queue.shift();
    for(const edge of data?.relationships||[]){
      const key=relationKey(edge.type);
      if(key!=='same_crm_user'&&key!=='same_name')continue;
      const other=edge.source===id?edge.target:edge.target===id?edge.source:'';
      const node=entities.get(other);
      if(node?.type==='account'&&!ids.has(other)){ids.add(other);queue.push(other)}
    }
  }
  return ids;
}
function fixedSectorEvidence(focusId){
  const entities=byId(),focus=entities.get(focusId)||fixedSectorRoot(),center=fixedSectorCenterIds(focus);
  const sectors=fixedSectorDefinitions.map(item=>({...item,items:new Map(),accounts:new Set(),evidence:0}));
  const sectorById=new Map(sectors.map(item=>[item.id,item]));
  for(const raw of data?.relationships||[]){
    const sectorId=fixedSectorTypes[relationKey(raw.type)],sector=sectorById.get(sectorId);
    if(!sector||sectorId==='center')continue;
    const left=entities.get(raw.source),right=entities.get(raw.target);
    if(!left||!right)continue;
    let from=null,to=null;
    if(center.has(left.id)&&!center.has(right.id)){from=left;to=right}
    else if(center.has(right.id)&&!center.has(left.id)){from=right;to=left}
    if(!from||!to||!['account','ib_user'].includes(to.type))continue;
    const item=sector.items.get(to.id)||{node:to,edges:[]};
    if(!item.edges.some(edge=>String(edge.raw.id)===String(raw.id)))item.edges.push({raw,from});
    sector.items.set(to.id,item);sector.accounts.add(to.id);sector.evidence++;
  }
  return{focus,center,sectors};
}
function fixedSectorRootProjection(w,h,focusId,expandedId){
  const evidence=fixedSectorEvidence(focusId),outer=Math.min(w,h)*.49,inner=outer*.22,cx=w/2,cy=h/2;
  evidence.sectors.forEach((sector,index)=>{
    sector.start=-Math.PI/2+index*Math.PI/4+.025;
    sector.end=-Math.PI/2+(index+1)*Math.PI/4-.025;
    sector.inner=inner;sector.outer=outer;
  });
  const centerMembers=fixedSectorNodes().filter(node=>evidence.center.has(node.id)&&node.id!==evidence.focus?.id);
  const centerPoints=new Map();
  if(evidence.focus)centerPoints.set(evidence.focus.id,{x:cx,y:cy});
  centerMembers.forEach((node,index)=>{
    const angle=-Math.PI/2+index*Math.PI*2/Math.max(1,centerMembers.length);
    centerPoints.set(node.id,{x:cx+Math.cos(angle)*inner*.67,y:cy+Math.sin(angle)*inner*.67});
  });
  const projection={...evidence,cx,cy,inner,outer,scale:1,nested:false,centerMembers,centerPoints,occurrences:[],edges:[]};
  fixedSectorPlaceRootItems(projection,expandedId);
  return projection;
}
function fixedSectorPlaceRootItems(projection,expandedId){
  for(const sector of projection.sectors){
    const expanded=expandedId===sector.id,items=[...sector.items.values()],span=sector.end-sector.start;
    const columns=Math.max(1,Math.min(4,Math.ceil(Math.sqrt(items.length))));
    items.forEach((item,index)=>{
      const column=index%columns,row=Math.floor(index/columns),rows=Math.ceil(items.length/columns);
      const angle=sector.start+span*(column+.5)/columns,progress=(row+.5)/rows;
      const radius=sector.inner+(sector.outer-sector.inner)*((expanded?.64:.70)+(expanded?.29:.23)*progress);
      const point={id:'fixed-sector-instance|'+projection.focus.id+'|'+sector.id+'|'+item.node.id,node:item.node,x:projection.cx+Math.cos(angle)*radius,y:projection.cy+Math.sin(angle)*radius,sector:sector.id,detail:expanded,size:expanded?7.2:5.8};
      projection.occurrences.push(point);
      if(expanded)item.edges.forEach(({raw,from})=>projection.edges.push({id:String(raw.id),raw,from:{node:from,...(projection.centerPoints.get(from.id)||{x:projection.cx,y:projection.cy})},to:point,sector:sector.id,directed:isDirectedRelation(raw.type)}));
    });
  }
}
function fixedSectorNestedRadius(parent,host,anchor){
  // A child world must fit inside the sector cell that contains its anchor.
  // The angular and radial clearances are both measured from that *local*
  // anchor, so sibling expansions cannot collapse back onto the root centre.
  const anchorRadius=Math.hypot(anchor.x-parent.cx,anchor.y-parent.cy);
  const halfSpan=Math.max(.045,(host.end-host.start)*.5-.025);
  const angularClearance=anchorRadius*Math.sin(halfSpan)*.72;
  const radialClearance=Math.min(
    Math.max(0,anchorRadius-host.inner),
    Math.max(0,host.outer-anchorRadius),
  )*.72;
  const sectorScale=Math.max(14,(host.outer-host.inner)*.34);
  return Math.max(14,Math.min(angularClearance,radialClearance,sectorScale));
}
function fixedSectorPlaceNestedItems(projection,expandedId){
  for(const sector of projection.sectors){
    const expanded=expandedId===sector.id,items=[...sector.items.values()],span=sector.end-sector.start;
    const columns=Math.max(1,Math.min(4,Math.ceil(Math.sqrt(items.length))));
    const rows=Math.max(1,Math.ceil(items.length/columns));
    items.forEach((item,index)=>{
      const column=index%columns,row=Math.floor(index/columns);
      // Keep a margin around the local centre and sector boundaries.  The
      // columns fan across the business-sector angle; rows occupy distinct
      // radial bands, which guarantees a stable, non-overlapping placement.
      const angle=sector.start+span*(column+.5)/columns;
      const radius=sector.inner+(sector.outer-sector.inner)*(.24+.66*(row+.5)/rows);
      const point={id:'fixed-sector-instance|'+projection.focus.id+'|'+sector.id+'|'+item.node.id,node:item.node,x:projection.cx+Math.cos(angle)*radius,y:projection.cy+Math.sin(angle)*radius,sector:sector.id,detail:expanded,size:Math.max(2.35,Math.min(4.5,projection.localRadius*.052/Math.sqrt(Math.max(1,rows))))};
      projection.occurrences.push(point);
      if(expanded)item.edges.forEach(({raw,from})=>projection.edges.push({id:String(raw.id),raw,from:{node:from,...(projection.centerPoints.get(from.id)||{x:projection.cx,y:projection.cy})},to:point,sector:sector.id,directed:isDirectedRelation(raw.type)}));
    });
  }
}
function fixedSectorNestedProjection(focusId,parent,anchor,expandedId){
  const evidence=fixedSectorEvidence(focusId),host=parent.sectors.find(item=>item.id===anchor.sector);
  if(!host)return null;
  const localRadius=fixedSectorNestedRadius(parent,host,anchor),inner=Math.max(4,localRadius*.22);
  evidence.sectors.forEach((sector,index)=>{
    sector.start=-Math.PI/2+index*Math.PI/4+.035;
    sector.end=-Math.PI/2+(index+1)*Math.PI/4-.035;
    sector.inner=inner;sector.outer=localRadius;
  });
  // Each drill-down becomes a new local centre at the clicked account.  The
  // original layer remains painted underneath; this projection is a compact
  // radial child map constrained by the available mother-sector clearance.
  const projection={...evidence,cx:anchor.x,cy:anchor.y,inner,outer:localRadius,localRadius,scale:parent.scale*.72,nested:true,hostSector:host.id,anchor,centerMembers:[],centerPoints:new Map([[focusId,{x:anchor.x,y:anchor.y}]]),occurrences:[],edges:[]};
  fixedSectorPlaceNestedItems(projection,expandedId);
  return projection;
}
function fixedSectorBuildLayers(w,h){
  if(!data)return[];
  fixedSectorEnsurePath();
  const root=fixedSectorRoot();if(!root)return[];
  const layers=[],rootProjection=fixedSectorRootProjection(w,h,root.id,fixedSectorExpanded.get(0)||'');
  layers.push({index:0,focusId:root.id,projection:rootProjection});
  for(let index=1;index<fixedSectorPath.length;index++){
    const parent=layers[layers.length-1],targetId=fixedSectorPath[index];
    const anchor=parent.projection.occurrences.find(item=>item.node.id===targetId);
    if(!anchor)break;
    const projection=fixedSectorNestedProjection(targetId,parent.projection,anchor,fixedSectorExpanded.get(index)||'');
    if(!projection)break;
    layers.push({index,focusId:targetId,projection});
  }
  return layers;
}
function fixedSectorFitLayers(layers,rect){
  if(!fixedSectorNeedsFit||!layers.length)return;
  const root=layers[0].projection;
  const scale=Math.min(1,(rect.width-64)/(root.outer*2),(rect.height-64)/(root.outer*2));
  view={scale:Math.max(.1,scale),x:rect.width/2-root.cx*scale,y:rect.height/2-root.cy*scale};
  fixedSectorNeedsFit=false;
}
function fixedSectorScreenPoint(point){return{x:view.x+point.x*view.scale,y:view.y+point.y*view.scale}}
function fixedSectorCompactBadge(node,x,y,size){
  if(node.type!=='account')return;
  const action=localAction(node),radius=Math.max(2,Math.min(4.2,size*.62));
  ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fillStyle='rgba(11,18,32,.92)';ctx.fill();ctx.strokeStyle=actionTheme(action);ctx.lineWidth=.8;ctx.stroke();
  ctx.fillStyle=actionTheme(action);ctx.font='600 '+Math.max(4,Math.min(7,size*.8))+'px Microsoft YaHei';ctx.textAlign='center';ctx.fillText(action,x,y+Math.max(1,size*.2));ctx.textAlign='start';
}
function fixedSectorRenderLocator(){
  const locator=document.getElementById('galaxyLocator'),context=locator?.getContext('2d');if(!locator||!context)return;
  const rect=locator.getBoundingClientRect(),w=Math.max(1,rect.width),h=Math.max(1,rect.height),d=devicePixelRatio||1;
  const nodeMap=new Map(fixedSectorNodes().filter(node=>node.type==='account').map(node=>[node.id,node]));
  const nodes=[...nodeMap.values()].sort((a,b)=>Number(a.hops||0)-Number(b.hops||0)||String(a.label).localeCompare(String(b.label),undefined,{numeric:true}));
  const cx=w/2,cy=h/2,radius=Math.min(w,h)*.31;
  locator.width=Math.round(w*d);locator.height=Math.round(h*d);context.setTransform(d,0,0,d,0,0);context.fillStyle='#071426';context.fillRect(0,0,w,h);fixedSectorLocatorHits=[];
  nodes.forEach((node,index)=>{
    const point=node.isSubject?{x:cx,y:cy}:{x:cx+Math.cos(index*2.4)*radius,y:cy+Math.sin(index*2.4)*radius};
    context.beginPath();context.arc(point.x,point.y,node.isSubject?7:4.5,0,Math.PI*2);context.fillStyle=galaxyLocatorStatusColor(node);context.fill();
    if(node.id===selectedId||node.isSubject){context.strokeStyle='#fff';context.lineWidth=2;context.stroke()}
    fixedSectorLocatorHits.push({node,x:point.x,y:point.y,radius:12});
  });
  const count=document.getElementById('galaxyLocatorCount');if(count)count.textContent=nodes.length+'个账户 · 全部显示';
}
function fixedSectorRenderControls(layers){
  const active=layers[layers.length-1]?.projection.focus,note=document.getElementById('overviewNote');
  if(note){
    note.replaceChildren();
    const text=document.createElement('span');
    text.textContent='无限画布 · 滚轮连续缩放 · 拖拽平移 · 双击适配全图。当前中心：'+(active?.label||'-')+'；外层保留，子扇区嵌入母扇区。';
    note.append(text);
    if(layers.length>1){
      const back=document.createElement('button');back.type='button';back.textContent='返回上一层';back.style.cssText='margin-left:10px;padding:3px 8px;border:1px solid #4da3ff;border-radius:4px;background:#102b48;color:#cfe9ff;cursor:pointer';
      back.addEventListener('click',()=>{fixedSectorPath.pop();fixedSectorExpanded.delete(fixedSectorPath.length);selectedId=fixedSectorPath[fixedSectorPath.length-1];activeType='';selectedEdgeKey='';renderOverview();renderDetail()});note.append(back);
    }
  }
  const head=document.querySelector('.galaxy-center .galaxy-panel-head');if(head?.firstChild)head.firstChild.textContent='固定区域关系网 ';
  const meta=document.getElementById('galaxyGalaxyMeta');if(meta)meta.textContent='嵌套 '+layers.length+' 层 · 当前：'+(active?.label||'-');
}
function fixedSectorPaintNode(layer,node,point,radius,sector,role){
  if(!node)return;
  drawNode(node,point.x,point.y,radius);ctx.fillStyle=color(node);ctx.fill();ctx.strokeStyle=node.id===selectedId?'#fff':'#bde7ff';ctx.lineWidth=1.2;ctx.stroke();
  if(layer.projection.nested)fixedSectorCompactBadge(node,point.x,point.y,radius);else drawActionBadge(node,point.x,point.y,radius);
  const screen=fixedSectorScreenPoint(point);
  fixedSectorHit.nodes.push({layer:layer.index,node,x:screen.x,y:screen.y,radius:Math.max(7,(radius+5)*view.scale),sector,role});
}
function fixedSectorRenderOverview(){
  if(!data)return;
  const rect=canvas.getBoundingClientRect(),layers=fixedSectorBuildLayers(Math.max(1,rect.width),Math.max(1,rect.height));
  fixedSectorFitLayers(layers,rect);fixedSectorActive=true;fixedSectorLastLayers=layers;
  ctx.fillStyle='#101826';ctx.fillRect(0,0,rect.width,rect.height);ctx.save();ctx.translate(view.x,view.y);ctx.scale(view.scale,view.scale);fixedSectorHit={nodes:[],edges:[],sectors:[]};
  for(const layer of layers){
    const p=layer.projection;
    for(const sector of p.sectors){
      const expanded=fixedSectorExpanded.get(layer.index)===sector.id,inner=sector.inner,outer=sector.outer;
      ctx.beginPath();ctx.arc(p.cx,p.cy,outer,sector.start,sector.end);ctx.arc(p.cx,p.cy,inner,sector.end,sector.start,true);ctx.closePath();
      ctx.fillStyle=sector.evidence?(expanded?'rgba(40,94,190,.34)':p.nested?'rgba(30,58,138,.28)':'rgba(30,58,138,.16)'):'rgba(51,65,85,.08)';ctx.fill();ctx.strokeStyle=sector.color;ctx.lineWidth=(expanded?2.2:1.15)/Math.max(.35,p.scale);ctx.stroke();
      if(!p.nested&&p.scale*view.scale>=.46){
        const angle=(sector.start+sector.end)/2,labelPoint={x:p.cx+Math.cos(angle)*(outer+20),y:p.cy+Math.sin(angle)*(outer+20)};
        ctx.fillStyle=sector.evidence?sector.color:'#64748b';ctx.font='700 11px Microsoft YaHei';ctx.textAlign='center';ctx.fillText(sector.label+' · '+sector.accounts.size+'账户 / '+sector.evidence+'关系'+(expanded?' · 已展开':''),labelPoint.x,labelPoint.y);ctx.textAlign='start';
      }
      const angle=(sector.start+sector.end)/2,hitPoint=fixedSectorScreenPoint({x:p.cx+Math.cos(angle)*(inner+outer)*.5,y:p.cy+Math.sin(angle)*(inner+outer)*.5});
      fixedSectorHit.sectors.push({layer:layer.index,id:sector.id,accounts:sector.accounts.size,evidence:sector.evidence,x:hitPoint.x,y:hitPoint.y,expanded,start:sector.start,end:sector.end,inner,outer,cx:p.cx,cy:p.cy,nested:p.nested});
    }
    for(const edge of p.edges){
      ctx.beginPath();ctx.moveTo(edge.from.x,edge.from.y);ctx.lineTo(edge.to.x,edge.to.y);ctx.strokeStyle=p.sectors.find(item=>item.id===edge.sector)?.color||'#93c5fd';ctx.lineWidth=2/Math.max(.35,p.scale);ctx.stroke();
      fixedSectorHit.edges.push({layer:layer.index,edge,points:[fixedSectorScreenPoint(edge.from),fixedSectorScreenPoint(edge.to)],tolerance:Math.max(5,Math.min(16,8*view.scale))});
    }
    if(!p.nested){
      fixedSectorPaintNode(layer,p.focus,{x:p.cx,y:p.cy},14,'center','focus');
      p.centerMembers.forEach(node=>fixedSectorPaintNode(layer,node,p.centerPoints.get(node.id),8,'center','center'));
    }else{
      // Do not create a second selectable account instance.  This halo makes
      // the clicked account visibly serve as the local centre of its child
      // sectors while the original outer-layer node remains the hit target.
      ctx.beginPath();ctx.arc(p.cx,p.cy,Math.max(3,p.inner*.7),0,Math.PI*2);
      ctx.strokeStyle='#d9f3ff';ctx.lineWidth=1.1/Math.max(.35,p.scale);ctx.stroke();
    }
    p.occurrences.forEach(item=>fixedSectorPaintNode(layer,item.node,item,item.size,item.sector,'direct'));
  }
  ctx.restore();fixedSectorRenderControls(layers);fixedSectorRenderLocator();
}
function fixedSectorPointInSector(point,sector){
  const x=(point.x-view.x)/view.scale-sector.cx,y=(point.y-view.y)/view.scale-sector.cy,radius=Math.hypot(x,y);let angle=Math.atan2(y,x);if(angle<sector.start)angle+=Math.PI*2;
  return radius>=sector.inner&&radius<=sector.outer&&angle>=sector.start&&angle<=sector.end;
}
function fixedSectorSelectNode(hit){
  selectedId=hit.node.id;activeType='';selectedEdgeKey='';
  if(hit.role==='direct'){
    fixedSectorPath=fixedSectorPath.slice(0,hit.layer+1);
    if(fixedSectorPath[fixedSectorPath.length-1]!==hit.node.id)fixedSectorPath.push(hit.node.id);
    for(const index of [...fixedSectorExpanded.keys()])if(index>=fixedSectorPath.length)fixedSectorExpanded.delete(index);
  }
  renderOverview();renderDetail();
}
function galaxyFixedSectorDispatch(event){
  if(!fixedSectorActive)return false;
  const rect=galaxyCanvas.getBoundingClientRect(),point={x:event.clientX-rect.left,y:event.clientY-rect.top};
  for(const hit of [...fixedSectorHit.nodes].reverse())if(Math.hypot(point.x-hit.x,point.y-hit.y)<=hit.radius){fixedSectorSelectNode(hit);return true}
  for(const hit of [...fixedSectorHit.edges].reverse())if(galaxyScreenDistanceToSegment(point,hit.points[0],hit.points[1])<=hit.tolerance){selectedEdgeKey=hit.edge.id;activeType='';inspectionSkipNextRefresh=true;renderOverview();renderDetail();inspectionLoadRelation(hit.edge.raw);return true}
  for(const sector of [...fixedSectorHit.sectors].reverse())if(fixedSectorPointInSector(point,sector)){fixedSectorExpanded.set(sector.layer,fixedSectorExpanded.get(sector.layer)===sector.id?'':sector.id);renderOverview();renderDetail();return true}
  return true;
}
const fixedSectorLocator=document.getElementById('galaxyLocator');
fixedSectorLocator?.addEventListener('click',event=>{
  if(!fixedSectorActive)return;
  const rect=fixedSectorLocator.getBoundingClientRect(),point={x:event.clientX-rect.left,y:event.clientY-rect.top},hit=fixedSectorLocatorHits.find(item=>Math.hypot(point.x-item.x,point.y-item.y)<=item.radius);
  if(!hit)return;event.preventDefault();event.stopImmediatePropagation();selectedId=hit.node.id;activeType='';selectedEdgeKey='';renderOverview();renderDetail();
},true);
window.__kdeskFixedSectorTestFrame=()=>({
  revision:Number(data?.revision||0),inProgress:Boolean(data?.inProgress),path:[...fixedSectorPath],
  layers:fixedSectorLastLayers.map(layer=>({
    index:layer.index,focusAccountId:String(layer.focusId),scale:layer.projection.scale,nested:Boolean(layer.projection.nested),hostSector:layer.projection.hostSector||'',
    centerX:fixedSectorScreenPoint({x:layer.projection.cx,y:layer.projection.cy}).x,
    centerY:fixedSectorScreenPoint({x:layer.projection.cx,y:layer.projection.cy}).y,
    anchorX:fixedSectorScreenPoint(layer.projection.anchor||{x:layer.projection.cx,y:layer.projection.cy}).x,
    anchorY:fixedSectorScreenPoint(layer.projection.anchor||{x:layer.projection.cx,y:layer.projection.cy}).y,
    localRadius:Number(layer.projection.localRadius||0),
  })),
  nodes:fixedSectorHit.nodes.map(item=>({layer:item.layer,accountId:String(item.node.id),nodeType:String(item.node.type),sector:item.sector,role:item.role,x:item.x,y:item.y,radius:item.radius})),
  edges:fixedSectorHit.edges.map(item=>({layer:item.layer,id:item.edge.id,type:String(item.edge.raw.type),sector:item.edge.sector})),
  sectors:fixedSectorHit.sectors.map(item=>({layer:item.layer,id:item.id,accounts:item.accounts,evidence:item.evidence,x:item.x,y:item.y,expanded:item.expanded,inner:item.inner,outer:item.outer,nested:item.nested})),
  locatorAccountIds:fixedSectorLocatorHits.map(item=>String(item.node.id)),
  zoom:{scale:Number(view.scale||0),min:fixedSectorZoomRange.min,max:fixedSectorZoomRange.max},
});
if(params.get('graph_type')==='fixed-sector'){
  canvas.setAttribute('aria-label','可平移连续缩放的固定区域关系图');
  fitMapToBoard=function(){fixedSectorNeedsFit=true};
  renderOverview=fixedSectorRenderOverview;
  const fixedDetailBase=renderDetail;
  renderDetail=function(){fixedDetailBase();groups?.querySelectorAll('.group-toggle').forEach(item=>item.remove())};
}
</script>'''
