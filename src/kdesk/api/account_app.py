from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from kdesk import __version__
from kdesk.api.common import legacy_filters, request_context
from kdesk.api.kuzu_3d_preview_page import render_kuzu_3d_preview_page
from kdesk.api.kuzu_demo_page import render_kuzu_demo_page
from kdesk.api.kuzu_focus_workspace_page import render_kuzu_focus_workspace_page
from kdesk.api.kuzu_graph_type_page import render_kuzu_graph_type_page
from kdesk.api.kuzu_risk_page import render_kuzu_risk_page
from kdesk.application.bonus_arbitrage_scan import normalize_bonus_scan_options
from kdesk.application.copy_pool_monitor import CopyPoolMonitorService
from kdesk.application.historical_funds import HistoricalFundsService
from kdesk.application.ledger_service import LedgerService
from kdesk.application.position_risk_scan import normalize_position_scan_options
from kdesk.application.relationship_expansion import AccountRelationshipExpansionCoordinator
from kdesk.application.relationship_inspection import RelationshipInspectionService
from kdesk.application.relationship_network import AccountRelationshipNetworkService
from kdesk.application.relationship_process import IsolatedRelationshipRiskBuilder
from kdesk.application.relationship_risk import AccountRelationshipRiskService
from kdesk.application.trade_relationship_detection import TradeRelationshipDetectionService
from kdesk.build_info import build_metadata
from kdesk.domain.rebate_churning import normalize_scan_options
from kdesk.infrastructure.automation_reports import (
    XLSX_MEDIA_TYPE,
    build_copy_profit_report,
    build_ea_profit_report,
)
from kdesk.infrastructure.copy_pool_monitor import CopyPoolFileSnapshotRepository
from kdesk.infrastructure.database import Database
from kdesk.infrastructure.excel_io import export_audit_json
from kdesk.infrastructure.kuzu_relationship_demo import KuzuRelationshipDemoRepository
from kdesk.infrastructure.kuzu_risk_graph import KuzuRiskGraphRepository
from kdesk.infrastructure.legacy_bridge import LegacyBridge
from kdesk.infrastructure.position_risk import LegacyPositionRiskRepository
from kdesk.settings import Settings
from kdesk.settings import settings as default_settings

logger = logging.getLogger("kdesk.account")

# Relationship discovery runs behind a single-flight background coordinator. Do
# not impose a request-wide deadline: slow, valid database reads may take minutes
# and must be allowed to finish while the HTTP/UI thread remains responsive. A
# generous per-source hard ceiling still prevents one permanently stuck adapter
# from blocking the sole relationship worker forever.
RELATIONSHIP_DISCOVERY_TIMEOUT_SECONDS: float | None = None
RELATIONSHIP_SOURCE_TIMEOUT_SECONDS = 120.0
# The expansion is isolated so a single investigation cannot retain native/Kuzu
# or provider allocations in 8777. This is a process wall-clock ceiling, not a
# source timeout: it returns the newest partial snapshot and reclaims the child.
RELATIONSHIP_PROCESS_TIMEOUT_SECONDS = 45.0


class CopyPoolControlsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autoTradingEnabled: bool
    equityFloorEnabled: bool
    dailyLossEnabled: bool
    cycleLossEnabled: bool
    resumeRequested: bool = False


class CopyPoolRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str


def _require_local_same_origin(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="运行恢复仅允许从本机操作")
    host = request.headers.get("host", "").strip().lower()
    host_name = (urlsplit(f"//{host}").hostname or "").lower()
    if host_name not in {"127.0.0.1", "::1", "localhost", "testserver"}:
        raise HTTPException(status_code=403, detail="运行恢复仅允许本机同源请求")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc.lower() != host:
        raise HTTPException(status_code=403, detail="运行恢复仅允许本机同源请求")


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _safe_login(login: str) -> str:
    login = str(login or "").strip()
    if not login or len(login) > 64 or not re.fullmatch(r"[0-9A-Za-z_.-]+", login):
        raise HTTPException(status_code=400, detail="账号格式无效")
    return login


def _toxic_sync_payload(legacy: LegacyBridge, login: str, filters: dict[str, str]) -> dict:
    """Return principal-order synchronization and suspected opposite-lock evidence."""
    return TradeRelationshipDetectionService(LegacyPositionRiskRepository(legacy)).analyze(login, filters)


def _payload_bool(payload: dict, key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"{key} 必须是布尔值")


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
    if not view["message"] and job.get("status") == "queued":
        view["message"] = "已提交，等待后台执行"
    elif not view["message"] and job.get("status") == "running":
        view["message"] = "任务执行中"
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
    historical_funds = HistoricalFundsService(legacy.call)
    kuzu_demo = KuzuRelationshipDemoRepository(config.kuzu_demo_path) if config.kuzu_demo_path else None
    kuzu_risk = KuzuRiskGraphRepository(config.kuzu_risk_path or config.runtime_dir / "relationship_risk_graph.kuzu")
    if config.profile == "prod":
        relationship_runtime: Any = IsolatedRelationshipRiskBuilder(
            config,
            discovery_timeout_seconds=RELATIONSHIP_DISCOVERY_TIMEOUT_SECONDS,
            source_timeout_seconds=RELATIONSHIP_SOURCE_TIMEOUT_SECONDS,
            process_timeout_seconds=RELATIONSHIP_PROCESS_TIMEOUT_SECONDS,
        )
        relationship_network = relationship_runtime
        relationship_risk = relationship_runtime
    else:
        relationship_network = AccountRelationshipNetworkService(
            legacy.call,
            source_timeout_seconds=RELATIONSHIP_SOURCE_TIMEOUT_SECONDS,
        )
        relationship_risk = AccountRelationshipRiskService(
            relationship_network,
            kuzu_risk.score_projection,
            lambda login, filters: legacy.call("account_shared_last_ip_payload", login, filters),
            lambda login, filters: _toxic_sync_payload(legacy, login, filters),
            shared_cid_lookup=lambda login, filters: legacy.call("account_shared_cid_payload", login, filters),
            discovery_timeout_seconds=RELATIONSHIP_DISCOVERY_TIMEOUT_SECONDS,
        )
    relationship_expansion = AccountRelationshipExpansionCoordinator(relationship_risk)
    relationship_inspection = RelationshipInspectionService()

    copy_pool = CopyPoolMonitorService(
        CopyPoolFileSnapshotRepository(
            config.copy_pool_output_dir or config.legacy_output / "copy_live_demo_capital10k"
        )
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.create_schema()
        if database.count_accounts() == 0 and config.bootstrap_xlsx.exists():
            result = ledger.import_excel(config.bootstrap_xlsx)
            export_audit_json(config.runtime_dir / "import" / "last_import.json", result)
        try:
            yield
        finally:
            relationship_expansion.close()
            close_relationship_network = getattr(relationship_network, "close", None)
            if callable(close_relationship_network):
                close_relationship_network()

    app = FastAPI(title="K_desk Account API", version=__version__, lifespan=lifespan)
    app.middleware("http")(request_context)
    app.state.settings = config
    app.state.database = database
    app.state.ledger = ledger
    app.state.legacy = legacy
    app.state.relationship_network = relationship_network
    app.state.relationship_risk = relationship_risk
    app.state.relationship_expansion = relationship_expansion
    app.state.relationship_inspection = relationship_inspection
    app.state.historical_funds = historical_funds
    app.state.kuzu_demo = kuzu_demo
    app.state.kuzu_risk = kuzu_risk
    app.state.copy_pool = copy_pool

    assets = config.frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/health/live")
    def health_live() -> dict:
        return {"ok": True, "status": "live", "service": "account", "version": __version__}

    @app.get("/health/ready")
    def health_ready() -> dict:
        database.create_schema()
        return {
            "ok": True,
            "status": "ready",
            "database": str(config.database_path),
            "profile": config.profile,
            "relationshipExpansion": relationship_expansion.stats(),
        }

    @app.get("/api/meta")
    def api_meta() -> dict:
        return {
            "ok": True,
            "service": "K_desk v2",
            **build_metadata(config),
            "profile": config.profile,
            "ports": {"account": config.account_port, "kline": config.kline_port},
            "storage": {"database": str(config.database_path), "artifacts": str(config.artifact_dir)},
            "legacyCompatibility": True,
        }

    @app.get("/", response_class=HTMLResponse)
    @app.get("/copy-pool", response_class=HTMLResponse)
    async def home(request: Request):
        if request.query_params.get("legacy") == "1" or config.ui_mode == "legacy":
            return HTMLResponse(await run_in_threadpool(legacy.workbench_page))
        index = _frontend_file(config)
        if index:
            return FileResponse(index, headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            })
        return HTMLResponse(_fallback_page("K_desk v2", "<h1>K_desk v2</h1><p>前端尚未构建。兼容工作台：<a href='/?legacy=1'>打开</a></p>"))

    @app.get("/api/copy-pool/dashboard")
    async def copy_pool_dashboard(
        timeline_limit: int = Query(720, ge=30, le=5000),
        event_limit: int = Query(100, ge=10, le=1000),
        order_limit: int = Query(100, ge=10, le=1000),
    ):
        return await run_in_threadpool(
            copy_pool.dashboard,
            timeline_limit=timeline_limit,
            event_limit=event_limit,
            order_limit=order_limit,
        )

    @app.put("/api/copy-pool/controls")
    async def update_copy_pool_controls(request: Request, body: CopyPoolControlsRequest):
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="风控控制仅允许从本机操作")
        controls = await run_in_threadpool(
            copy_pool.update_controls,
            {
                "auto_trading_enabled": body.autoTradingEnabled,
                "equity_floor_enabled": body.equityFloorEnabled,
                "daily_loss_enabled": body.dailyLossEnabled,
                "cycle_loss_enabled": body.cycleLossEnabled,
                "resume_requested": body.resumeRequested,
            },
        )
        return {"ok": True, "controls": controls}

    @app.post("/api/copy-pool/runtime/recovery")
    async def request_copy_pool_recovery(request: Request, body: CopyPoolRecoveryRequest):
        _require_local_same_origin(request)
        if body.action != "reconnect_and_sync":
            raise HTTPException(status_code=422, detail="不支持的恢复动作")
        recovery = await run_in_threadpool(copy_pool.request_recovery, wait_seconds=10.0)
        status_code = 200 if recovery["state"] in {"synchronized", "failed"} else 202
        return JSONResponse(
            status_code=status_code,
            content={"ok": recovery["state"] == "synchronized", "recovery": recovery},
        )

    @app.get("/copy-pool/accounts/{alias}")
    async def copy_pool_account(alias: str):
        target = await run_in_threadpool(copy_pool.account_target, alias)
        if not target:
            raise HTTPException(status_code=404, detail="客户池账户映射不存在")
        return RedirectResponse(target, status_code=307)

    @app.get("/account/{login}", response_class=HTMLResponse)
    async def account_page(login: str):
        login = _safe_login(login)
        return HTMLResponse(await run_in_threadpool(legacy.account_page, login))

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

    @app.get("/api/accounts/by-login/{login}/historical-funds")
    async def historical_funds_payload(login: str, request: Request):
        try:
            data = await run_in_threadpool(
                historical_funds.build,
                _safe_login(login),
                legacy_filters(request.query_params),
            )
            return {"ok": True, **data}
        except (RuntimeError, ValueError) as exc:
            logger.warning("Historical funds query failed for account %s: %s", login, exc)
            return JSONResponse(
                {
                    "ok": False,
                    "available": False,
                    "account": str(login),
                    "error": "历史资金数据查询失败，请检查数据库连接",
                    "reason": "历史资金数据查询失败，请检查数据库连接",
                },
                status_code=503,
            )

    @app.get("/api/accounts/by-login/{login}/automation-analysis")
    async def automation(login: str, request: Request):
        return await run_in_threadpool(legacy.call, "account_automation_payload", _safe_login(login), legacy_filters(request.query_params))

    @app.get("/api/accounts/by-login/{login}/relationship-network")
    async def relationship_network_payload(
        login: str,
        request: Request,
        threshold: float = Query(12, ge=1, le=100),
        include_toxic: bool = Query(False),
    ):
        payload = relationship_expansion.get_or_start(
            _safe_login(login),
            legacy_filters(request.query_params),
            threshold,
            include_toxic,
        )
        return payload

    @app.get("/api/accounts/by-login/{login}/relationship-network/node-profile")
    async def relationship_node_profile(
        login: str,
        request: Request,
        node_id: str = Query(..., min_length=1, max_length=180),
        threshold: float = Query(12, ge=1, le=100),
        include_toxic: bool = Query(False),
        job_id: str | None = Query(None, max_length=120),
        snapshot_version: int | None = Query(None, ge=0),
    ):
        root = _safe_login(login)
        filters = legacy_filters(request.query_params)
        snapshot = relationship_expansion.get_or_start(root, filters, threshold, include_toxic)
        if snapshot_version is not None and int(snapshot.get("revision") or 0) != snapshot_version:
            raise HTTPException(status_code=409, detail="调查快照已更新，请刷新关系图后重试")
        entities = [item for item in snapshot.get("entities", []) if isinstance(item, dict)]
        node = next(
            (
                item
                for item in entities
                if str(item.get("id") or "") == node_id or str(item.get("label") or "") == node_id
            ),
            None,
        )
        if node is None or str(node.get("type") or "") != "account":
            raise HTTPException(status_code=404, detail="当前调查快照中不存在该账户节点")

        now = datetime.now()
        start = filters.get("start") or (now - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        end = filters.get("end") or now.strftime("%Y-%m-%d %H:%M:%S")
        node_filters = {
            **filters,
            "platform": str(node.get("platform") or filters.get("platform") or ""),
            "server": str(node.get("server") or filters.get("server") or ""),
            "start": start,
            "end": end,
        }
        node_login = _safe_login(str(node.get("label") or ""))
        results = await asyncio.gather(
            run_in_threadpool(legacy.call, "account_risk_panels_payload", node_login, node_filters),
            run_in_threadpool(legacy.call, "account_automation_payload", node_login, node_filters),
            return_exceptions=True,
        )
        source_names = ("账户行为画像", "自动化识别")
        limitations = list(snapshot.get("limitations") or [])
        payloads: list[dict[str, Any] | None] = []
        for source_name, result in zip(source_names, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Relationship node profile source failed source=%s login=%s: %s", source_name, node_login, result)
                limitations.append(f"{source_name}暂时不可用，已返回其余画像结果。")
                payloads.append(None)
            else:
                payloads.append(result if isinstance(result, dict) else None)
        safe_snapshot = {**snapshot, "limitations": list(dict.fromkeys(limitations))}
        try:
            payload = relationship_inspection.build_node_profile(
                root,
                str(node.get("id") or node_id),
                safe_snapshot,
                payloads[0],
                payloads[1],
                start=start,
                end=end,
            )
            payload["job_id"] = job_id
            return payload
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/accounts/by-login/{login}/relationship-network/relation-detail")
    async def relationship_relation_detail(
        login: str,
        request: Request,
        edge_id: str = Query(..., min_length=1, max_length=220),
        threshold: float = Query(12, ge=1, le=100),
        include_toxic: bool = Query(False),
        detail_page: int = Query(1, ge=1),
        detail_limit: int = Query(50, ge=1, le=200),
        job_id: str | None = Query(None, max_length=120),
        snapshot_version: int | None = Query(None, ge=0),
    ):
        filters = legacy_filters(request.query_params)
        snapshot = relationship_expansion.get_or_start(
            _safe_login(login),
            filters,
            threshold,
            include_toxic,
        )
        if snapshot_version is not None and int(snapshot.get("revision") or 0) != snapshot_version:
            raise HTTPException(status_code=409, detail="调查快照已更新，请刷新关系图后重试")
        try:
            payload = relationship_inspection.build_relation_detail(
                edge_id,
                {
                    **snapshot,
                    "filters": {
                        **(snapshot.get("filters") if isinstance(snapshot.get("filters"), dict) else {}),
                        **filters,
                    },
                },
                detail_page=detail_page,
                detail_limit=detail_limit,
            )
            payload["job_id"] = job_id
            return payload
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/kuzu-demo", response_class=HTMLResponse)
    async def kuzu_demo_page() -> HTMLResponse:
        return HTMLResponse(render_kuzu_demo_page(), headers={"Cache-Control": "no-store"})

    @app.get("/api/kuzu-demo/graph")
    async def kuzu_demo_graph(depth: int = Query(2, ge=1, le=3)) -> dict:
        if kuzu_demo is None:
            raise HTTPException(status_code=404, detail="Kuzu 图谱试用未配置")
        try:
            return await run_in_threadpool(kuzu_demo.graph, depth)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Kuzu 图谱试用数据不存在") from exc
        except (RuntimeError, ValueError):
            logger.exception("Kuzu demo graph read failed")
            raise HTTPException(status_code=503, detail="Kuzu 图谱暂时不可用") from None

    @app.get("/kuzu-risk", response_class=HTMLResponse)
    async def kuzu_risk_page(graph_type: str = Query("focus-force")) -> HTMLResponse:
        renderer = {
            "choose": render_kuzu_graph_type_page,
            "focus-3d": render_kuzu_3d_preview_page,
            "focus-force": render_kuzu_focus_workspace_page,
            "galaxy": render_kuzu_risk_page,
        }.get((graph_type or "focus-force").strip().lower(), render_kuzu_focus_workspace_page)
        return HTMLResponse(renderer(), headers={"Cache-Control": "no-store"})

    @app.get("/api/kuzu-risk/graph")
    async def kuzu_risk_graph(threshold: float = Query(12, ge=1, le=100)) -> dict:
        if kuzu_risk is None:
            raise HTTPException(status_code=404, detail="Kuzu 风险图谱未配置")
        try:
            payload = await run_in_threadpool(kuzu_risk.graph, threshold)
            return payload
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Kuzu 风险图谱数据不存在") from exc
        except (RuntimeError, ValueError):
            logger.exception("Kuzu risk graph read failed")
            raise HTTPException(status_code=503, detail="Kuzu 风险图谱暂时不可用") from None

    @app.get("/api/accounts/by-login/{login}/copy-origins")
    async def copy_origins(login: str, request: Request):
        try:
            return await run_in_threadpool(
                legacy.call, "account_copy_origins_payload", _safe_login(login), legacy_filters(request.query_params)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/accounts/by-login/{login}/copy-group-profit")
    async def copy_group_profit(login: str, request: Request):
        try:
            return await run_in_threadpool(
                legacy.call, "account_copy_group_profit_payload", _safe_login(login), legacy_filters(request.query_params)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/accounts/by-login/{login}/ea-comment-profit")
    async def ea_comment_profit(login: str, request: Request):
        return await run_in_threadpool(legacy.call, "account_ea_comment_profit_payload", _safe_login(login), legacy_filters(request.query_params))

    @app.get("/api/accounts/by-login/{login}/copy-report.xlsx")
    async def copy_profit_report(login: str, request: Request):
        login = _safe_login(login)
        filters = legacy_filters(request.query_params)
        try:
            copy_payload = await run_in_threadpool(
                legacy.call,
                "account_copy_origins_payload",
                login,
                filters,
            )
        except Exception as exc:
            logger.warning("Copy report query failed for account %s: %s", login, exc)
            raise HTTPException(status_code=503, detail="跟单收益数据查询失败，无法生成报表") from exc
        exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = await run_in_threadpool(
            build_copy_profit_report,
            copy_payload,
            None,
            filters,
            exported_at=exported_at,
        )
        filename = f"copy_profit_{login}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return _xlsx_response(content, filename)

    @app.get("/api/accounts/by-login/{login}/ea-report.xlsx")
    async def ea_profit_report(login: str, request: Request):
        login = _safe_login(login)
        filters = legacy_filters(request.query_params)
        try:
            payload = await run_in_threadpool(
                legacy.call,
                "account_ea_comment_profit_payload",
                login,
                filters,
            )
        except Exception as exc:
            logger.warning("EA report query failed for account %s: %s", login, exc)
            raise HTTPException(status_code=503, detail="EA 收益数据查询失败，无法生成报表") from exc
        exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = await run_in_threadpool(
            build_ea_profit_report,
            payload,
            filters,
            exported_at=exported_at,
        )
        filename = f"ea_profit_{login}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return _xlsx_response(content, filename)

    @app.get("/api/accounts/by-login/{login}/login-ips")
    async def login_ips(login: str):
        return await run_in_threadpool(legacy.call, "account_login_ips_payload", _safe_login(login))

    @app.get("/api/accounts/by-login/{login}/orders")
    async def orders(login: str, request: Request, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
        filters = legacy_filters(request.query_params)
        return await run_in_threadpool(
            legacy.call,
            "account_orders_payload",
            _safe_login(login),
            page,
            page_size,
            filters.get("platform", ""),
            filters.get("server", ""),
        )

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

    @app.get("/api/rebate-churning/accounts/{account}")
    async def rebate_churning_account_audit(
        account: str,
        start: str = "",
        end: str = "",
        environment: str = "",
        serverCode: str = "",
    ):
        try:
            return await run_in_threadpool(
                legacy.call,
                "rebate_churning_account_audit_payload",
                _safe_login(account),
                start,
                end,
                environment,
                serverCode,
            )
        except ValueError as exc:
            candidates = getattr(exc, "candidates", None)
            payload = {"ok": False, "error": str(exc)}
            if candidates:
                payload["candidates"] = candidates
            return JSONResponse(payload, status_code=409 if candidates else 400)

    @app.post("/api/rebate-churning/scans")
    def start_rebate_churning_scan(payload: dict = Body(default_factory=dict)) -> dict:
        try:
            clean_payload = normalize_scan_options(payload, now=datetime.now())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        key = "rebate-churning-scan:" + json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("rebate_churning_scan", clean_payload, idempotency_key=key, max_attempts=1)
        return {"ok": True, "job": job}

    @app.get("/api/rebate-churning/scans/{job_id}")
    def get_rebate_churning_scan(job_id: str) -> dict:
        job = database.get_job(job_id)
        if not job or job.get("kind") != "rebate_churning_scan":
            raise HTTPException(status_code=404, detail="刷返佣扫描任务不存在")
        return {"ok": True, **job}

    @app.get("/api/rebate-churning/ibs/{environment}/{ib_id}")
    async def rebate_churning_ib_detail(environment: str, ib_id: int, start: str = "", end: str = ""):
        if environment not in {"gb", "cn", "dbg_cn", "dbg_vn"}:
            raise HTTPException(status_code=400, detail="环境无效")
        try:
            return await run_in_threadpool(legacy.call, "rebate_churning_ib_payload", environment, ib_id, start, end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/bonus-arbitrage/scans")
    def start_bonus_arbitrage_scan(payload: dict = Body(default_factory=dict)) -> dict:
        try:
            clean_payload = normalize_bonus_scan_options(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        key = "bonus-arbitrage-scan:" + json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("bonus_arbitrage_scan", clean_payload, idempotency_key=key, max_attempts=1)
        return {"ok": True, "job": job}

    @app.get("/api/bonus-arbitrage/scans/active")
    def get_active_bonus_arbitrage_scan() -> dict:
        return {"ok": True, "job": database.get_active_job("bonus_arbitrage_scan")}

    @app.get("/api/bonus-arbitrage/scans/{job_id}")
    def get_bonus_arbitrage_scan(job_id: str) -> dict:
        job = database.get_job(job_id)
        if not job or job.get("kind") != "bonus_arbitrage_scan":
            raise HTTPException(status_code=404, detail="赠金套利扫描任务不存在")
        return {"ok": True, **job}

    @app.post("/api/position-risk/scans")
    def start_position_risk_scan(payload: dict = Body(default_factory=dict)) -> dict:
        try:
            clean_payload = normalize_position_scan_options(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        key = "position-risk-scan:" + json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("position_risk_scan", clean_payload, idempotency_key=key, max_attempts=1)
        return {"ok": True, "job": job}

    @app.get("/api/position-risk/scans/active")
    def get_active_position_risk_scan() -> dict:
        return {"ok": True, "job": database.get_active_job("position_risk_scan")}

    @app.get("/api/position-risk/scans/{job_id}")
    def get_position_risk_scan(job_id: str) -> dict:
        job = database.get_job(job_id)
        if not job or job.get("kind") != "position_risk_scan":
            raise HTTPException(status_code=404, detail="重仓时点扫描任务不存在")
        return {"ok": True, **job}

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
        try:
            recent_orders = int(payload.get("recentOrders", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="recentOrders 必须是整数") from exc
        if not 0 <= recent_orders <= 1000:
            raise HTTPException(status_code=400, detail="recentOrders 必须在 0 到 1000 之间")
        clean_payload = {
            "account": login,
            "platform": str(payload.get("platform", "")),
            "server": str(payload.get("server", "")),
            "symbol": str(payload.get("symbol", "")),
            "start": str(payload.get("start", "")),
            "end": str(payload.get("end", "")),
            "recentOrders": recent_orders,
            "cacheVersion": str(payload.get("cacheVersion", "")),
            "includeTimeline": _payload_bool(payload, "includeTimeline", False),
            "refreshTimelineCache": _payload_bool(payload, "refreshTimelineCache", False),
        }
        if not clean_payload["includeTimeline"]:
            clean_payload["refreshTimelineCache"] = False
        key = "kline:" + json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("kline_from_database", clean_payload, idempotency_key=key)
        return {"ok": True, "job": job}

    @app.get("/api/accounts/by-login/{login}/inline-kline", response_class=HTMLResponse)
    async def account_inline_kline(
        login: str,
        platform: str = "",
        server: str = "",
        recentOrders: int = Query(default=300, ge=1, le=300),
    ) -> HTMLResponse:
        """Render the bounded detail-page chart directly from the account service.

        This intentionally bypasses the durable K-line job queue and the :8766
        task UI.  The separate manual generation endpoint above remains the
        only artifact-producing flow.
        """
        payload = {
            "platform": platform,
            "server": server,
            "recentOrders": recentOrders,
        }
        try:
            chart_html = await run_in_threadpool(
                legacy.call,
                "account_inline_kline_html",
                _safe_login(login),
                payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return HTMLResponse(chart_html, headers={"Cache-Control": "private, max-age=60"})

    @app.post("/api/push-discovery/start")
    def start_push_discovery(payload: dict = Body(default_factory=dict)) -> dict:
        try:
            days = int(payload.get("days", 7))
            deep_limit = int(payload.get("deepLimit", 50))
            max_orders = int(payload.get("maxOrders", 200))
            min_max_lot = float(payload.get("minMaxLot", 0.01))
            max_deposit = float(payload.get("maxDeposit", 2000))
            max_active_ratio = float(payload.get("maxActiveRatio", 30))
            require_period_profit = _payload_bool(payload, "requirePeriodProfit", True)
            limit_orders = _payload_bool(payload, "limitOrders", True)
            require_max_lot = _payload_bool(payload, "requireMaxLot", True)
            require_total_profit = _payload_bool(payload, "requireTotalProfit", True)
            limit_deposit = _payload_bool(payload, "limitDeposit", True)
            limit_active_ratio = _payload_bool(payload, "limitActiveRatio", True)
            exclude_handled = _payload_bool(payload, "excludeHandled", True)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="扫描参数格式无效") from exc
        if not 1 <= days <= 30:
            raise HTTPException(status_code=400, detail="扫描天数必须在1到30之间")
        if not 1 <= deep_limit <= 300:
            raise HTTPException(status_code=400, detail="深检账号上限必须在1到300之间")
        if not 1 <= max_orders <= 1000:
            raise HTTPException(status_code=400, detail="最大订单数必须在1到1000之间")
        if not 0 <= min_max_lot <= 100_000:
            raise HTTPException(status_code=400, detail="最大手数筛选值必须在0到100000之间")
        if not 0 <= max_deposit <= 10_000_000:
            raise HTTPException(status_code=400, detail="累计入金上限必须在0到10000000之间")
        if not 0 <= max_active_ratio <= 100:
            raise HTTPException(status_code=400, detail="活跃天数占比必须在0到100之间")
        clean_payload = {
            "days": days,
            "maxOrders": max_orders,
            "requirePeriodProfit": require_period_profit,
            "limitOrders": limit_orders,
            "requireMaxLot": require_max_lot,
            "minMaxLot": min_max_lot,
            "requireTotalProfit": require_total_profit,
            "limitDeposit": limit_deposit,
            "maxDeposit": max_deposit,
            "limitActiveRatio": limit_active_ratio,
            "maxActiveRatio": max_active_ratio,
            "excludeHandled": exclude_handled,
            "smallOrderPriority": min(max_orders, 200) if limit_orders else 200,
            "deepLimit": deep_limit,
            "workers": 4,
        }
        key = "push-discovery:" + json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
        job = database.create_job("push_discovery", clean_payload, idempotency_key=key, max_attempts=2)
        return {"ok": True, "job": job}

    @app.get("/api/push-discovery/active")
    def get_active_push_discovery() -> dict:
        return {"ok": True, "job": database.get_active_job("push_discovery")}

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
