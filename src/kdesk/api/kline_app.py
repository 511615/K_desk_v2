from __future__ import annotations

import json
import mimetypes
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from kdesk import __version__
from kdesk.api.common import request_context
from kdesk.infrastructure.database import Database
from kdesk.settings import Settings
from kdesk.settings import settings as default_settings


def _safe_artifact(name: str, roots: tuple[Path, ...]) -> Path | None:
    safe_name = Path(name).name
    for root in roots:
        candidate = (root / safe_name).resolve()
        if candidate.parent == root.resolve() and candidate.is_file():
            return candidate
    return None


def _index_html(account_port: int, theme_css: str = "") -> str:
    return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>K_desk v2 K线任务</title><style>
{theme_css}
*{{box-sizing:border-box}}body{{margin:0;background:var(--kdesk-bg,#04111f);color:var(--kdesk-text,#dcecff);font-family:var(--kdesk-font,Arial,sans-serif)}}header{{padding:18px 24px;background:#071d37;border-bottom:1px solid var(--kdesk-border,#17466d)}}main{{width:100%;padding:24px;max-width:1100px;margin:auto}}.panel{{min-width:0;background:var(--kdesk-surface,#06192c);border:1px solid var(--kdesk-border,#17466d);border-radius:6px;padding:18px;margin-bottom:16px}}button{{background:#0b5683;color:white;border:1px solid var(--kdesk-border-strong,#1d5b85);padding:9px 14px;border-radius:5px;cursor:pointer}}input{{max-width:100%;background:var(--kdesk-bg,#04111f);color:#fff;border:1px solid var(--kdesk-border-strong,#1d5b85);border-radius:5px;padding:9px}}pre{{white-space:pre-wrap;background:#030b14;border:1px solid var(--kdesk-border,#17466d);padding:12px;border-radius:5px}}a{{color:#54c2ff}}#recent p,#recent a{{overflow-wrap:anywhere;word-break:break-word}}@media(max-width:600px){{main{{padding:10px}}header{{display:flex;flex-wrap:wrap;gap:6px;padding:14px 12px}}.panel{{padding:14px}}}}</style></head>
<body><header><b>K_desk v2 · K线/AI任务</b>　<a href='http://127.0.0.1:{account_port}'>返回账户工作台</a></header><main>
<section class='panel'><h2>上传报表</h2><form id='upload'><input type='file' name='statement' accept='.htm,.html' required> <button>上传并解析</button></form><p id='status'></p></section>
<section class='panel'><h2>最近图表</h2><div id='recent'>读取中...</div></section><section class='panel'><h2>任务日志</h2><pre id='logs'>暂无任务</pre></section>
<script>
const statusEl=document.getElementById('status'),logs=document.getElementById('logs');
async function api(url,opt){{const r=await fetch(url,opt),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||`HTTP ${{r.status}}`);return d}}
async function recent(){{try{{const d=await api('/api/recent');document.getElementById('recent').innerHTML=d.charts.length?d.charts.map(x=>`<p><a target='_blank' href='${{x.url}}'>${{x.name}}</a> · ${{x.mtime}}</p>`).join(''):'暂无图表'}}catch(e){{document.getElementById('recent').textContent=e.message}}}}
function showChart(result){{const href=result.html_url||'';statusEl.textContent='生成完成 · 100%';if(href){{const link=document.createElement('a');link.href=href;link.target='_blank';link.textContent='打开生成图表';statusEl.append(' · ',link)}}}}
async function startGeneration(inspect){{const preview=inspect.result?.preview||{{}},symbols=(preview.symbols||[]).map(item=>item.symbol).filter(Boolean);if(!symbols.length)throw new Error('解析完成但没有可生成的品种');statusEl.textContent='解析完成 · 正在生成图表...';const generated=await api('/api/jobs/'+inspect.id+'/generate',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{symbols,start:preview.start||'',end:preview.end||'',runAi:false}})}});poll(generated.job.id,'generate')}}
async function poll(id,phase='inspect'){{try{{const d=await api('/api/jobs/'+id),result=d.result||{{}},failures=result.failures||[];statusEl.textContent=`${{d.status}} · ${{d.progress}}%${{result.partial?' · 部分成功':''}}`;const events=(d.events||[]).map(x=>`[${{x.at}}] ${{x.message}}`),details=failures.map(x=>`${{x.symbol}} · ${{x.stage}}/${{x.code}} · ${{x.reason}}`);logs.textContent=[...events,...details].join('\\n')||d.error||'';if(!['done','failed','cancelled'].includes(d.status))setTimeout(()=>poll(id,phase),1200);else if(phase==='inspect'&&d.status==='done'){{try{{await startGeneration(d)}}catch(error){{statusEl.textContent='解析完成，但生成提交失败：'+error.message}}}}else{{if(phase==='generate'&&d.status==='done')showChart(result);recent()}}}}catch(error){{statusEl.textContent='任务状态读取失败：'+error.message}}}}
document.getElementById('upload').addEventListener('submit',async e=>{{e.preventDefault();try{{const d=await api('/api/uploads',{{method:'POST',body:new FormData(e.target)}});poll(d.job.id)}}catch(err){{statusEl.textContent=err.message}}}});recent();
</script></main></body></html>"""


def create_kline_app(app_settings: Settings | None = None) -> FastAPI:
    config = app_settings or default_settings
    config.ensure_runtime()
    database = Database(config.database_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.create_schema()
        yield

    app = FastAPI(title="K_desk Kline API", version=__version__, lifespan=lifespan)
    app.middleware("http")(request_context)

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        theme_path = config.root / "frontend" / "src" / "kdesk-theme.css"
        theme_css = theme_path.read_text(encoding="utf-8") if theme_path.is_file() else ""
        return _index_html(config.account_port, theme_css)

    @app.get("/health/live")
    def health_live() -> dict:
        return {"ok": True, "status": "live", "service": "kline", "version": __version__}

    @app.get("/health/ready")
    def health_ready() -> dict:
        database.create_schema()
        return {"ok": True, "status": "ready", "workerQueue": str(config.database_path)}

    @app.get("/api/recent")
    def recent() -> dict:
        charts: list[dict] = []
        seen: set[str] = set()
        for root, writable in ((config.artifact_dir, True), (config.legacy_output, False)):
            if not root.exists():
                continue
            for path in sorted(root.glob("*_trade_kline.html"), key=lambda item: item.stat().st_mtime, reverse=True):
                if path.name in seen:
                    continue
                seen.add(path.name)
                charts.append(
                    {
                        "name": path.name,
                        "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "size": path.stat().st_size,
                        "url": f"/output/{path.name}",
                        "writable": writable,
                    }
                )
                if len(charts) >= 30:
                    break
            if len(charts) >= 30:
                break
        return {"ok": True, "charts": charts}

    @app.get("/output/{name}")
    def output(name: str):
        path = _safe_artifact(name, (config.artifact_dir, config.legacy_output))
        if not path:
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    @app.post("/api/uploads")
    async def upload(statement: UploadFile = File(...)) -> dict:
        filename = Path(statement.filename or "statement.html").name
        if not re.search(r"\.html?$", filename, flags=re.IGNORECASE):
            raise HTTPException(status_code=400, detail="只支持 .htm 或 .html 报表")
        target = config.upload_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{filename}"
        max_bytes = 100 * 1024 * 1024
        written = 0
        try:
            with target.open("wb") as output:
                while chunk := await statement.read(1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise HTTPException(status_code=413, detail="报表超过100MB限制")
                    output.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        job = database.create_job("kline_inspect", {"statement": str(target)}, idempotency_key=f"inspect:{target}")
        return {"ok": True, "job": job}

    @app.post("/api/jobs/{job_id}/generate")
    def generate(job_id: str, payload: dict = Body(default_factory=dict)) -> dict:
        source = database.get_job(job_id)
        if not source or source["kind"] != "kline_inspect":
            raise HTTPException(status_code=404, detail="解析任务不存在")
        statement = source["payload"].get("statement", "")
        task_payload = {
            "statement": statement,
            "symbols": payload.get("symbols") or [],
            "start": str(payload.get("start", "")),
            "end": str(payload.get("end", "")),
            "run_ai": bool(payload.get("runAi", False)),
        }
        job = database.create_job("kline_generate", task_payload, idempotency_key="generate:" + json.dumps(task_payload, sort_keys=True, ensure_ascii=False))
        return {"ok": True, "job": job}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = database.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"ok": True, **job}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = database.request_job_cancel(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"ok": True, **(database.get_job(job_id) or {})}

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse({"ok": False, "error": str(exc.detail)}, status_code=exc.status_code)

    return app


app = create_kline_app()
