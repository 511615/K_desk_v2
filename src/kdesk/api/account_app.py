from __future__ import annotations

import json
import logging
import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from kdesk import __version__
from kdesk.api.common import legacy_filters, request_context
from kdesk.application.ledger_service import LedgerService
from kdesk.infrastructure.database import Database
from kdesk.infrastructure.excel_io import export_audit_json
from kdesk.infrastructure.legacy_bridge import LegacyBridge
from kdesk.settings import Settings
from kdesk.settings import settings as default_settings

logger = logging.getLogger("kdesk.account")


def _safe_login(login: str) -> str:
    login = str(login or "").strip()
    if not login or len(login) > 64 or not re.fullmatch(r"[0-9A-Za-z_.-]+", login):
        raise HTTPException(status_code=400, detail="账号格式无效")
    return login


def _frontend_file(settings: Settings, relative: str = "index.html") -> Path | None:
    candidate = (settings.frontend_dist / relative).resolve()
    if settings.frontend_dist.exists() and candidate.is_file() and settings.frontend_dist in candidate.parents:
        return candidate
    return None


def _legacy_job_view(job: dict) -> dict:
    """Expose a persistent job through the legacy page polling contract."""
    stored_result = job.get("result") if isinstance(job.get("result"), dict) else {}
    view = dict(job)
    percent = stored_result.get("percent", job.get("progress", 0))
    events = job.get("events") if isinstance(job.get("events"), list) else []
    last_event = events[-1].get("message", "") if events and isinstance(events[-1], dict) else ""
    view["percent"] = min(max(int(percent or 0), 0), 100)
    view["message"] = str(stored_result.get("message") or last_event or job.get("error") or "")
    for key in ("elapsedSeconds", "cached", "chart", "summary", "results", "outputDir", "stage"):
        if key in stored_result:
            view[key] = stored_result[key]
    if job.get("kind") == "toxic_check" and isinstance(stored_result.get("result"), dict):
        view["result"] = stored_result["result"]
    else:
        view["result"] = stored_result
    return view


def _fallback_page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title><style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:40px;background:#07111f;color:#d9e7f5}}a{{color:#53b9ff}}.card{{max-width:760px;padding:24px;background:#0d1d31;border:1px solid #24415f;border-radius:10px}}</style></head><body><div class='card'>{body}</div></body></html>"""


def _charts_for_account(config: Settings, legacy: LegacyBridge, login: str, limit: int = 30) -> list[dict]:
    charts: list[dict] = []
    seen: set[str] = set()
    parser = legacy.function("parse_chart_file")
    for root in (config.artifact_dir, config.legacy_output):
        if not root.exists():
            continue
        for path in sorted(root.glob(f"{login}_*_trade_kline.html"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                item = parser(path)
            except Exception:
                item = {"account": login, "name": path.name, "path": str(path), "size": path.stat().st_size}
            item["url"] = f"/chart-file/{path.name}"
            charts.append(item)
            if len(charts) >= limit:
                return charts
    return charts


def create_account_app(app_settings: Settings | None = None) -> FastAPI:
    config = app_settings or default_settings
    config.ensure_runtime()
    database = Database(config.database_path)
    compat_workbook = config.legacy_compat_dir / "problematic_accounts.xlsx"
    ledger = LedgerService(database, compatibility_workbook=compat_workbook)
    legacy = LegacyBridge(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.create_schema()
        if database.count_accounts() == 0 and config.bootstrap_xlsx.exists():
            result = ledger.import_excel(config.bootstrap_xlsx)
            export_audit_json(config.runtime_dir / "import" / "last_import.json", result)
        yield

    app = FastAPI(title="K_desk Account API", version=__version__, lifespan=lifespan)
    app.middleware("http")(request_context)
    app.state.settings = config
    app.state.database = database
    app.state.ledger = ledger
    app.state.legacy = legacy

    assets = config.frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/health/live")
    def health_live() -> dict:
        return {"ok": True, "status": "live", "service": "account", "version": __version__}

    @app.get("/health/ready")
    def health_ready() -> dict:
        database.create_schema()
        return {"ok": True, "status": "ready", "database": str(config.database_path), "profile": config.profile}

    @app.get("/api/meta")
    def api_meta() -> dict:
        return {
            "ok": True,
            "service": "K_desk v2",
            "version": __version__,
            "profile": config.profile,
            "ports": {"account": config.account_port, "kline": config.kline_port},
            "storage": {"database": str(config.database_path), "artifacts": str(config.artifact_dir)},
            "legacyCompatibility": True,
        }

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if request.query_params.get("legacy") == "1" or config.ui_mode == "legacy":
            return HTMLResponse(await run_in_threadpool(legacy.workbench_page))
        index = _frontend_file(config)
        if index:
            return FileResponse(index)
        return HTMLResponse(_fallback_page("K_desk v2", "<h1>K_desk v2</h1><p>前端尚未构建。兼容工作台：<a href='/?legacy=1'>打开</a></p>"))

    @app.get("/account/{login}", response_class=HTMLResponse)
    async def account_page(login: str, request: Request):
        login = _safe_login(login)
        if request.query_params.get("legacy") == "1" or config.ui_mode == "legacy":
            return HTMLResponse(await run_in_threadpool(legacy.account_page, login))
        index = _frontend_file(config)
        if index:
            return FileResponse(index)
        return RedirectResponse(f"/account/{login}?legacy=1")

    @app.get("/api/accounts")
    def accounts() -> dict:
        return ledger.list_payload()

    @app.get("/api/accounts/by-login/{login}/ledger")
    def account_ledger(login: str) -> dict:
        return ledger.ledger_for_login(_safe_login(login))

    @app.post("/api/accounts/mark")
    def mark_account(payload: dict = Body(default_factory=dict)) -> dict:
        login = _safe_login(str(payload.get("account", "")))
        existing = database.find_by_login(login)
        translated = {
            "账号": login,
            "建议动作": payload.get("action", ""),
            "当前分组": payload.get("group", ""),
            "风险标签": payload.get("tags", ""),
            "风险/问题备注": payload.get("note", ""),
            "状态": payload.get("status", ""),
            "处理人/来源": payload.get("owner", ""),
        }
        return ledger.save(translated, existing.record_id if existing else None)

    @app.post("/api/accounts/mark-batch")
    def mark_accounts(payload: dict = Body(default_factory=dict)) -> dict:
        accounts = payload.get("accounts")
        if not isinstance(accounts, list):
            raise HTTPException(status_code=400, detail="批量账号格式无效")
        normalized = {
            "建议动作": payload.get("action", ""),
            "当前分组": payload.get("group", ""),
            "风险标签": payload.get("tags", ""),
            "风险/问题备注": payload.get("note", ""),
            "状态": payload.get("status", ""),
            "处理人/来源": payload.get("owner", ""),
        }
        result = ledger.save_many(normalized, accounts)
        result["savedCount"] = len(result["records"])
        return result

    @app.put("/api/accounts/{record_id}")
    def update_account(record_id: str, payload: dict = Body(default_factory=dict)) -> dict:
        if not database.get_account(record_id):
            raise HTTPException(status_code=404, detail="记录不存在")
        return ledger.save(payload, record_id)

    @app.delete("/api/accounts/{record_id}")
    def delete_account(record_id: str) -> dict:
        result = ledger.delete(record_id)
        if not result["ok"]:
            raise HTTPException(status_code=404, detail="记录不存在")
        return result

    @app.get("/api/accounts/{record_id}/history")
    def account_history(record_id: str) -> dict:
        return {"ok": True, "history": database.history(record_id)}

    @app.get("/api/quick-actions")
    def quick_actions() -> dict:
        return {"ok": True, "actions": database.quick_actions(), "protected": ["自定义"]}

    @app.post("/api/quick-actions")
    def add_quick_action(payload: dict = Body(default_factory=dict)) -> dict:
        try:
            actions = database.add_quick_action(payload.get("action") or payload.get("name"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "actions": actions, "protected": ["自定义"]}

    @app.delete("/api/quick-actions/{name}")
    def delete_quick_action(name: str) -> dict:
        return {"ok": True, "actions": database.delete_quick_action(unquote(name)), "protected": ["自定义"]}

    @app.get("/api/accounts/by-login/{login}/detail")
    async def account_detail(login: str, request: Request):
        login = _safe_login(login)
        filters = legacy_filters(request.query_params)
        data = await run_in_threadpool(legacy.call, "account_detail_payload", login, filters)
        local = ledger.ledger_for_login(login)
        charts = await run_in_threadpool(_charts_for_account, config, legacy, login)
        data.update({"marked": local["marked"], "record": local["record"], "actions": local["actions"], "statuses": local["statuses"], "charts": charts})
        return data

    @app.get("/api/accounts/by-login/{login}/risk-panels")
    async def risk_panels(login: str, request: Request):
        return await run_in_threadpool(legacy.call, "account_risk_panels_payload", _safe_login(login), legacy_filters(request.query_params))

    @app.get("/api/accounts/by-login/{login}/automation-analysis")
    async def automation(login: str, request: Request):
        return await run_in_threadpool(legacy.call, "account_automation_payload", _safe_login(login), legacy_filters(request.query_params))

    @app.get("/api/accounts/by-login/{login}/copy-origins")
    async def copy_origins(login: str, request: Request):
        return await run_in_threadpool(legacy.call, "account_copy_origins_payload", _safe_login(login), legacy_filters(request.query_params))

    @app.get("/api/accounts/by-login/{login}/copy-group-profit")
    async def copy_group_profit(login: str, request: Request):
        return await run_in_threadpool(legacy.call, "account_copy_group_profit_payload", _safe_login(login), legacy_filters(request.query_params))

    @app.get("/api/accounts/by-login/{login}/login-ips")
    async def login_ips(login: str):
        return await run_in_threadpool(legacy.call, "account_login_ips_payload", _safe_login(login))

    @app.get("/api/accounts/by-login/{login}/orders")
    async def orders(login: str, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
        return await run_in_threadpool(legacy.call, "account_orders_payload", _safe_login(login), page, page_size)

    @app.get("/api/account-lookup")
    async def account_lookup(account: str):
        login = _safe_login(account)
        databases = await run_in_threadpool(legacy.call, "account_lookup_databases", login)
        local = ledger.ledger_for_login(login)
        if databases:
            database_payload = databases[0]
        else:
            database_payload = {
                "exists": False,
                "account": login,
                "orderCount": 0,
                "chartableOrderCount": 0,
                "symbols": [],
                "latestSource": {},
                "accountMeta": {},
            }
        return {
            "ok": True,
            "account": login,
            "marked": local["marked"],
            "record": local["record"],
            "database": database_payload,
            "databases": databases,
        }

    @app.get("/api/account-lookup-finance")
    async def account_lookup_finance(account: str, platform: str = "", server: str = ""):
        return await run_in_threadpool(legacy.call, "account_lookup_finance_payload", _safe_login(account), platform, server)

    @app.get("/api/account-logs")
    async def account_logs(account: str, start: str, end: str):
        return await run_in_threadpool(legacy.call, "account_logs_payload", _safe_login(account), start, end)

    @app.get("/api/hierarchy-products")
    async def hierarchy_products():
        return await run_in_threadpool(legacy.call, "hierarchy_products_payload")

    @app.get("/api/hierarchy-net-deposit")
    async def hierarchy_net_deposit(target: str, start: str, end: str, product: str = "", activityRules: bool = False):
        return await run_in_threadpool(legacy.call, "hierarchy_net_deposit_payload", target, start, end, product, activityRules)

    @app.get("/api/trades/summary")
    async def trade_summary(request: Request, account: str):
        return await run_in_threadpool(legacy.call, "trade_summary_for_account", _safe_login(account), legacy_filters(request.query_params))

    @app.post("/api/kline/generate-from-db")
    def generate_kline(payload: dict = Body(default_factory=dict)) -> dict:
        login = _safe_login(str(payload.get("account", "")))
        clean_payload = {
            "account": login,
            "platform": str(payload.get("platform", "")),
            "server": str(payload.get("server", "")),
            "symbol": str(payload.get("symbol", "")),
            "start": str(payload.get("start", "")),
            "end": str(payload.get("end", "")),
        }
        key = "kline:" + json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("kline_from_database", clean_payload, idempotency_key=key)
        return {"ok": True, "job": job}

    @app.post("/api/push-discovery/start")
    def start_push_discovery(payload: dict = Body(default_factory=dict)) -> dict:
        try:
            days = int(payload.get("days", 7))
            max_orders = int(payload.get("maxOrders", 200))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="扫描参数格式无效") from exc
        if not 1 <= days <= 30:
            raise HTTPException(status_code=400, detail="扫描天数必须在1到30之间")
        if not 20 <= max_orders <= 1000:
            raise HTTPException(status_code=400, detail="最大订单数必须在20到1000之间")
        clean_payload = {
            "days": days,
            "maxOrders": max_orders,
            "smallOrderPriority": min(max_orders, 200),
            "deepLimit": 50,
            "workers": 4,
        }
        key = "push-discovery:" + json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("push_discovery", clean_payload, idempotency_key=key, max_attempts=1)
        return {"ok": True, "job": job}

    @app.get("/api/kline/jobs/{job_id}")
    @app.get("/api/toxic/jobs/{job_id}")
    @app.get("/api/push-discovery/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = database.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        legacy_job = _legacy_job_view(job)
        return {
            "ok": True,
            **job,
            "percent": legacy_job["percent"],
            "message": legacy_job["message"],
            "job": legacy_job,
        }

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = database.request_job_cancel(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"ok": True, **job}

    @app.get("/api/toxic/check-types")
    def toxic_check_types() -> dict:
        types = getattr(legacy.module(), "TOXIC_CHECK_TYPES", [])
        return {"ok": True, "types": types}

    @app.post("/api/accounts/by-login/{login}/toxic-checks")
    def toxic_checks(login: str, payload: dict = Body(default_factory=dict)) -> dict:
        login = _safe_login(login)
        task_payload = {"account": login, **payload}
        key = "toxic:" + json.dumps(task_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("toxic_check", task_payload, idempotency_key=key)
        types = getattr(legacy.module(), "TOXIC_CHECK_TYPES", [])
        return {"ok": True, "job": job, "types": types}

    @app.get("/download/problematic_accounts.xlsx")
    def download_accounts():
        path = ledger.export_excel(config.runtime_dir / "exports" / "problematic_accounts.xlsx")
        return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/chart-file/{name}")
    def chart_file(name: str):
        safe_name = Path(name).name
        for root in (config.artifact_dir, config.legacy_output):
            candidate = (root / safe_name).resolve()
            if candidate.parent == root.resolve() and candidate.is_file() and candidate.name.endswith("_trade_kline.html"):
                return FileResponse(candidate, media_type=mimetypes.guess_type(candidate.name)[0] or "text/html")
        raise HTTPException(status_code=404, detail="图表不存在")

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse({"ok": False, "error": str(exc.detail)}, status_code=exc.status_code)

    return app


app = create_account_app()
