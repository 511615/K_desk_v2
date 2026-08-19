from __future__ import annotations


def render_kuzu_graph_type_page() -> str:
    """Render the graph-type chooser without changing the underlying graph API."""
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Kuzu 关系网络图类型</title>
  <style>
    :root{color-scheme:dark;font-family:"Microsoft YaHei","Segoe UI",sans-serif;background:#061326;color:#dcecff}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 50% -10%,#123f72,transparent 45%),#061326}
    main{width:min(1080px,calc(100% - 36px));margin:0 auto;padding:64px 0}
    .head{display:flex;align-items:center;gap:16px;margin-bottom:38px}.head h1{margin:0;font-size:30px}.head p{margin:0;color:#88a9cf}
    .back{color:#a9d4ff;text-decoration:none;border:1px solid #2e75ba;border-radius:8px;padding:10px 14px}
    .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}
    .card{display:flex;flex-direction:column;min-height:360px;padding:26px;border:1px solid #235685;border-radius:14px;background:#0a1d36;box-shadow:0 18px 40px #0005}
    .card h2{margin:0 0 8px;font-size:23px}.card p{color:#91acd0;line-height:1.7;min-height:88px}
    .preview{height:150px;margin:12px 0 20px;border:1px solid #1f4d78;border-radius:10px;background:#07172b;position:relative;overflow:hidden}
    .preview:before{content:"";position:absolute;inset:25px;border:1px dashed #2c5c89;border-radius:50%;box-shadow:0 0 0 30px #0a1d36,0 0 0 31px #2c5c89,0 0 0 66px #0a1d36,0 0 0 67px #2c5c89}
    .preview .dot{position:absolute;width:18px;height:18px;border-radius:50%;background:#ff4051;left:50%;top:50%;transform:translate(-50%,-50%);box-shadow:0 0 0 7px #1b527d}
    .preview .peer{position:absolute;width:12px;height:12px;border-radius:50%;background:#f5a623}.preview .p1{left:28%;top:32%}.preview .p2{left:73%;top:64%}.preview .p3{left:65%;top:25%}
    .preview.force:before{inset:18px;border-radius:50%;box-shadow:none}.preview.force .dot{left:50%;top:50%}.preview.force .peer{width:15px;height:15px}.preview.force .p1{left:28%;top:38%}.preview.force .p2{left:74%;top:57%}.preview.force .p3{left:59%;top:26%}
    .choose{margin-top:auto;text-align:center;text-decoration:none;color:#fff;background:#087fdd;border:1px solid #38a1ff;border-radius:8px;padding:12px 16px;font-weight:700}.choose:hover{background:#0b9bff}
    .legacy{background:#32265d;border-color:#7958cf}.legacy:hover{background:#4b3592}.note{margin-top:22px;color:#7895b8;font-size:13px}
    @media(max-width:760px){.grid{grid-template-columns:1fr}.head{align-items:flex-start;flex-direction:column}}
  </style>
</head>
<body>
<main data-graph-type-selector="true">
  <div class="head"><a class="back" href="javascript:history.back()">← 返回</a><div><h1>选择关系网络图类型</h1><p>数据、扩散评分和关联证据不变，仅切换展示方式。</p></div></div>
  <div class="grid">
    <section class="card"><h2>星系图（原版）</h2><p>保留现有的同心圈层布局。适合快速查看账户所在扩散层级和整体范围，兼容原有使用习惯。</p><div class="preview"><i class="dot"></i><i class="peer p1"></i><i class="peer p2"></i><i class="peer p3"></i></div><a class="choose legacy" data-type="galaxy" href="?graph_type=galaxy">使用星系图</a></section>
    <section class="card"><h2>中心约束力导向图</h2><p>问题账户固定在中心，相关账户按关系和扩散层级自然分散；直接关系用连线标注，点击节点可查看其关系证据和回到中心的链路。</p><div class="preview force"><i class="dot"></i><i class="peer p1"></i><i class="peer p2"></i><i class="peer p3"></i></div><a class="choose" data-type="focus-force" href="?graph_type=focus-force">使用中心约束力导向图</a></section>
  </div>
  <div class="note">提示：图类型只影响前端布局和交互，不会改变数据库查询口径；原版星系图始终保留。</div>
</main>
<script>
  document.querySelectorAll('[data-type]').forEach((link)=>link.addEventListener('click',(event)=>{
    event.preventDefault();const url=new URL(location.href);url.searchParams.set('graph_type',link.dataset.type);location.assign(url.toString());
  }));
</script>
</body></html>'''
