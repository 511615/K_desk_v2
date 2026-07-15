from __future__ import annotations

import cgi
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(os.environ.get("K_DESK_ROOT", Path(__file__).resolve().parents[2]))
LEGACY_RISK_ROOT = Path(r"D:\risk")
DEFAULT_OUT_DIR = LEGACY_RISK_ROOT / "output_data" if LEGACY_RISK_ROOT.exists() else ROOT / "outputs" / "kline"
DEFAULT_PYDEPS = LEGACY_RISK_ROOT / "pydeps" if (LEGACY_RISK_ROOT / "pydeps").exists() else ROOT / "pydeps"
OUT_DIR = Path(os.environ.get("TRADE_KLINE_OUT_DIR", DEFAULT_OUT_DIR))
UPLOAD_DIR = OUT_DIR / "uploaded_statements"
TOOL_DIR = Path(os.environ.get("TRADE_KLINE_TOOL_DIR", ROOT / "tools" / "trade_kline_tool"))
GENERATOR = TOOL_DIR / "generate_trade_kline_from_statement.py"
PYTHON = Path(os.environ.get("K_DESK_PYTHON", r"C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"))
TERMINAL = Path(r"C:\Program Files\AC Capital Market MT5 Terminal\terminal64.exe")
HOST = "127.0.0.1"
PORT = int(os.environ.get("TRADE_KLINE_WEB_PORT", "8765"))
if ROOT.name == "K_desk_ai_dev" and "TRADE_KLINE_WEB_PORT" not in os.environ:
    PORT = 8766

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
AI_JOBS: dict[str, dict] = {}
AI_JOBS_LOCK = threading.Lock()
AI_CHAT_LOCK = threading.Lock()

if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(name: str) -> str:
    name = Path(name or "statement.html").name
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return name or "statement.html"


def file_url(path: Path) -> str:
    return "file:///" + str(path.resolve()).replace("\\", "/")


def public_output_url(path: Path) -> str:
    return "/output/" + quote(path.name)


def stem_from_chart_name(name: str) -> str:
    safe = Path(name).name
    suffix = "_trade_kline.html"
    if safe.endswith(suffix):
        return safe[: -len(suffix)]
    suffix = "_trades.csv"
    if safe.endswith(suffix):
        return safe[: -len(suffix)]
    return Path(safe).stem


def ai_result_path(stem: str) -> Path:
    return OUT_DIR / f"{Path(stem).name}_ai_analysis.json"


def ai_trades_path(stem: str) -> Path:
    return OUT_DIR / f"{Path(stem).name}_trades.csv"


def ai_chat_path(stem: str) -> Path:
    return OUT_DIR / f"{Path(stem).name}_ai_chat.json"


def read_ai_result(stem: str) -> dict | None:
    path = ai_result_path(stem)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def empty_ai_chat(stem: str) -> dict[str, Any]:
    return {"stem": stem, "conversation_summary": "", "messages": []}


def read_ai_chat(stem: str) -> dict[str, Any]:
    path = ai_chat_path(stem)
    if not path.exists():
        return empty_ai_chat(stem)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_ai_chat(stem)
    if not isinstance(data, dict):
        return empty_ai_chat(stem)
    data.setdefault("stem", stem)
    data.setdefault("conversation_summary", "")
    data.setdefault("messages", [])
    if not isinstance(data["messages"], list):
        data["messages"] = []
    return data


def write_ai_chat(stem: str, chat: dict[str, Any]) -> None:
    path = ai_chat_path(stem)
    path.write_text(json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8")


def public_ai_chat(stem: str) -> dict[str, Any]:
    chat = read_ai_chat(stem)
    return {
        "stem": stem,
        "conversation_summary": chat.get("conversation_summary", ""),
        "messages": chat.get("messages", []),
    }


def parse_request_payload(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(length).decode("utf-8", errors="replace") if length else ""
    if handler.headers.get("Content-Type", "").startswith("application/json"):
        return json.loads(raw or "{}")
    data = parse_qs(raw)
    return {key: (value[0] if value else "") for key, value in data.items()}


def update_ai_job(stem: str, **updates) -> None:
    with AI_JOBS_LOCK:
        job = AI_JOBS.setdefault(stem, {"stem": stem})
        job.update(updates)
        job["updated_at"] = now_text()


def run_ai_analysis(stem: str, provider: str = "", model: str = "") -> None:
    trades = ai_trades_path(stem)
    if not trades.exists():
        update_ai_job(stem, status="failed", message=f"missing trades csv: {trades}", finished_at=now_text())
        return
    started_ts = time.time()
    update_ai_job(stem, status="running", message="AI分析中", started_at=now_text(), started_ts=started_ts, elapsed_seconds=0)
    try:
        from ai_trade_analysis import analyze_trades_file

        rules_env = os.environ.get("K_DESK_AI_RULES", "").strip()
        result = analyze_trades_file(
            trades,
            OUT_DIR,
            provider=provider or os.environ.get("K_DESK_AI_PROVIDER", "mock"),
            model=model or os.environ.get("K_DESK_AI_MODEL", "gpt-5.4-mini"),
            rules_path=Path(rules_env) if rules_env else None,
        )
        elapsed = round(time.time() - started_ts, 2)
        update_ai_job(stem, status="done", message=f"AI分析完成，用时 {elapsed:.2f} 秒", result=str(result), finished_at=now_text(), elapsed_seconds=elapsed)
    except Exception as exc:
        elapsed = round(time.time() - started_ts, 2)
        update_ai_job(stem, status="failed", message=str(exc), finished_at=now_text(), elapsed_seconds=elapsed)


def run_ai_analysis(stem: str, provider: str = "", model: str = "") -> None:
    trades = ai_trades_path(stem)
    if not trades.exists():
        update_ai_job(stem, status="failed", message=f"missing trades csv: {trades}", finished_at=now_text())
        return
    started_ts = time.time()
    update_ai_job(
        stem,
        status="running",
        message="正在启动AI分析",
        progress_percent=3,
        started_at=now_text(),
        started_ts=started_ts,
        elapsed_seconds=0,
    )
    try:
        from ai_trade_analysis import analyze_trades_file

        def progress_callback(status: str, message: str, percent: int) -> None:
            update_ai_job(
                stem,
                status=status,
                message=message,
                progress_percent=max(0, min(100, int(percent))),
                elapsed_seconds=round(time.time() - started_ts, 2),
            )

        rules_env = os.environ.get("K_DESK_AI_RULES", "").strip()
        result = analyze_trades_file(
            trades,
            OUT_DIR,
            provider=provider or os.environ.get("K_DESK_AI_PROVIDER", "mock"),
            model=model or os.environ.get("K_DESK_AI_MODEL", "gpt-5.4-mini"),
            rules_path=Path(rules_env) if rules_env else None,
            progress=progress_callback,
        )
        elapsed = round(time.time() - started_ts, 2)
        update_ai_job(
            stem,
            status="done",
            message=f"AI分析完成，用时 {elapsed:.2f} 秒",
            progress_percent=100,
            result=str(result),
            finished_at=now_text(),
            elapsed_seconds=elapsed,
        )
    except Exception as exc:
        elapsed = round(time.time() - started_ts, 2)
        update_ai_job(
            stem,
            status="failed",
            message=str(exc),
            progress_percent=0,
            finished_at=now_text(),
            elapsed_seconds=elapsed,
        )


def run_ai_analysis(stem: str, provider: str = "", model: str = "") -> None:
    trades = ai_trades_path(stem)
    if not trades.exists():
        update_ai_job(stem, status="failed", message=f"missing trades csv: {trades}", finished_at=now_text())
        return
    started_ts = time.time()
    update_ai_job(
        stem,
        status="running",
        message="正在启动AI分析",
        progress_percent=3,
        started_at=now_text(),
        started_ts=started_ts,
        elapsed_seconds=0,
    )
    try:
        from ai_trade_analysis import analyze_trades_file

        def progress_callback(status: str, message: str, percent: int) -> None:
            update_ai_job(
                stem,
                status=status,
                message=message,
                progress_percent=max(0, min(100, int(percent))),
                elapsed_seconds=round(time.time() - started_ts, 2),
            )

        rules_env = os.environ.get("K_DESK_AI_RULES", "").strip()
        result_path = analyze_trades_file(
            trades,
            OUT_DIR,
            provider=provider or os.environ.get("K_DESK_AI_PROVIDER", "openai"),
            model=model or os.environ.get("K_DESK_AI_MODEL", "gpt-5.4-mini"),
            rules_path=Path(rules_env) if rules_env else None,
            progress=progress_callback,
        )
        elapsed = round(time.time() - started_ts, 2)
        analysis = read_ai_result(stem) or {}
        if analysis.get("model_call_failed"):
            update_ai_job(
                stem,
                status="failed",
                message=str(analysis.get("model_error") or "AI模型调用失败，已保存本地兜底结果，可重新发起AI分析"),
                progress_percent=0,
                fallback_result=analysis,
                result=str(result_path),
                finished_at=now_text(),
                elapsed_seconds=elapsed,
            )
            return
        update_ai_job(
            stem,
            status="done",
            message=f"AI分析完成，用时 {elapsed:.2f} 秒",
            progress_percent=100,
            result=str(result_path),
            finished_at=now_text(),
            elapsed_seconds=elapsed,
        )
    except Exception as exc:
        elapsed = round(time.time() - started_ts, 2)
        update_ai_job(
            stem,
            status="failed",
            message=str(exc),
            progress_percent=0,
            finished_at=now_text(),
            elapsed_seconds=elapsed,
        )


def run_ai_followup(stem: str, question: str, provider: str = "", model: str = "") -> dict[str, Any]:
    ai_result = read_ai_result(stem)
    if not ai_result:
        raise RuntimeError("请先完成一次AI分析，再进行追问")
    with AI_CHAT_LOCK:
        chat = read_ai_chat(stem)
        chat.setdefault("messages", [])
        chat["messages"].append({"role": "user", "content": question, "created_at": now_text()})
        from ai_trade_analysis import answer_followup_question

        answer = answer_followup_question(
            stem,
            ai_result,
            chat,
            question,
            provider=provider or os.environ.get("K_DESK_AI_PROVIDER", "mock"),
            model=model or os.environ.get("K_DESK_AI_MODEL", "gpt-5.4-mini"),
        )
        assistant_message = {
            "role": "assistant",
            "content": str(answer.get("answer", "")),
            "key_points": answer.get("key_points", []),
            "referenced_tickets": answer.get("referenced_tickets", []),
            "limitations": answer.get("limitations", []),
            "created_at": answer.get("created_at") or now_text(),
            "provider": answer.get("provider", ""),
            "model": answer.get("model", ""),
        }
        chat["messages"].append(assistant_message)
        chat["conversation_summary"] = str(answer.get("conversation_summary") or chat.get("conversation_summary", ""))[:3000]
        write_ai_chat(stem, chat)
        return {"ok": True, "stem": stem, "answer": assistant_message, "chat": public_ai_chat(stem)}


def ai_status(stem: str) -> dict:
    result = read_ai_result(stem)
    with AI_JOBS_LOCK:
        job = dict(AI_JOBS.get(stem) or {"stem": stem})
    estimate = None
    trades = ai_trades_path(stem)
    if trades.exists():
        try:
            from ai_trade_analysis import estimate_trades_file

            estimate = estimate_trades_file(trades, os.environ.get("K_DESK_AI_MODEL", "gpt-5.4-mini"))
        except Exception as exc:
            estimate = {"error": str(exc)}
    if job.get("status") in {"queued", "running"}:
        if job.get("status") == "running" and job.get("started_ts"):
            try:
                job["elapsed_seconds"] = round(time.time() - float(job["started_ts"]), 2)
            except (TypeError, ValueError):
                pass
        job["estimate"] = estimate
        return job
    if result:
        job.update(
            {
                "status": "done",
                "message": "AI分析完成",
                "result": result,
                "result_path": str(ai_result_path(stem)),
                "estimate": estimate,
                "elapsed_seconds": job.get("elapsed_seconds") or result.get("elapsed_seconds"),
            }
        )
    elif not job.get("status"):
        job.update({"status": "idle", "message": "尚未分析", "estimate": estimate})
    else:
        job["estimate"] = estimate
    return job


def ai_status(stem: str) -> dict:
    result = read_ai_result(stem)
    with AI_JOBS_LOCK:
        job = dict(AI_JOBS.get(stem) or {"stem": stem})
    status = job.get("status")
    if status in {"queued", "running"}:
        if status == "running" and job.get("started_ts"):
            try:
                job["elapsed_seconds"] = round(time.time() - float(job["started_ts"]), 2)
            except (TypeError, ValueError):
                pass
        job.setdefault("progress_percent", 3 if status == "running" else 0)
        return job
    if result:
        job.update(
            {
                "status": "done",
                "message": "AI分析完成",
                "progress_percent": 100,
                "result": result,
                "result_path": str(ai_result_path(stem)),
                "estimate": result.get("cost_estimate"),
                "elapsed_seconds": job.get("elapsed_seconds") or result.get("elapsed_seconds"),
            }
        )
    elif not status:
        job.update({"status": "idle", "message": "尚未分析，点击发起AI分析后才会计算二级指标", "progress_percent": 0})
    return job


def ai_status(stem: str) -> dict:
    result = read_ai_result(stem)
    with AI_JOBS_LOCK:
        job = dict(AI_JOBS.get(stem) or {"stem": stem})
    status = job.get("status")
    if status in {"queued", "running"}:
        if status == "running" and job.get("started_ts"):
            try:
                job["elapsed_seconds"] = round(time.time() - float(job["started_ts"]), 2)
            except (TypeError, ValueError):
                pass
        job.setdefault("progress_percent", 3 if status == "running" else 0)
        return job
    if status == "failed":
        if result and result.get("model_call_failed"):
            job.setdefault("fallback_result", result)
            job.setdefault("result_path", str(ai_result_path(stem)))
            job.setdefault("estimate", result.get("cost_estimate"))
        return job
    if result:
        if result.get("model_call_failed"):
            job.update(
                {
                    "status": "failed",
                    "message": str(result.get("model_error") or "AI模型调用失败，已保存本地兜底结果，可重新发起AI分析"),
                    "progress_percent": 0,
                    "fallback_result": result,
                    "result_path": str(ai_result_path(stem)),
                    "estimate": result.get("cost_estimate"),
                    "elapsed_seconds": job.get("elapsed_seconds") or result.get("elapsed_seconds"),
                }
            )
        else:
            job.update(
                {
                    "status": "done",
                    "message": "AI分析完成",
                    "progress_percent": 100,
                    "result": result,
                    "result_path": str(ai_result_path(stem)),
                    "estimate": result.get("cost_estimate"),
                    "elapsed_seconds": job.get("elapsed_seconds") or result.get("elapsed_seconds"),
                }
            )
    elif not status:
        job.update({"status": "idle", "message": "尚未分析，点击发起AI分析后才会计算二级指标", "progress_percent": 0})
    return job


def build_ai_panel_html(stem: str) -> str:
    return f"""
<style>
#kDeskAiPanel {{ margin:12px 18px; background:#ffffff; border:1px solid #d7e0e6; border-radius:8px; box-shadow:0 2px 10px rgba(15,23,42,.05); font-family:Arial,"Microsoft YaHei",sans-serif; overflow:hidden; color:#1f2937; }}
#kDeskAiPanel .ai-top {{ display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 14px; border-bottom:1px solid #edf2f5; background:#f8fbfc; }}
#kDeskAiPanel .ai-title-wrap {{ display:flex; align-items:center; gap:8px; min-width:0; }}
#kDeskAiPanel .ai-title {{ font-size:15px; font-weight:800; color:#1f2937; }}
#kDeskAiPanel .ai-subtitle {{ color:#64748b; font-size:12px; white-space:nowrap; }}
#kDeskAiPanel .ai-status {{ display:inline-flex; align-items:center; min-height:24px; padding:2px 8px; border-radius:999px; background:#eef2f6; color:#334155; font-size:12px; font-weight:700; }}
#kDeskAiPanel .ai-status.running {{ background:#eaf1ff; color:#1d4ed8; }}
#kDeskAiPanel .ai-status.done {{ background:#e8f5e9; color:#166534; }}
#kDeskAiPanel .ai-status.failed {{ background:#ffebee; color:#991b1b; }}
#kDeskAiPanel .ai-actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
#kDeskAiPanel button {{ border:1px solid #00796b; background:#00796b; color:white; border-radius:7px; padding:7px 10px; cursor:pointer; font-size:13px; }}
#kDeskAiPanel button:disabled {{ opacity:.55; cursor:not-allowed; }}
#kDeskAiPanel button.secondary {{ background:white; color:#1f2937; border-color:#d7e0e6; }}
#kDeskAiPanel button.secondary:hover {{ border-color:#aebcc5; background:#f8fbfc; }}
#kDeskAiPanel .ai-progress {{ height:3px; background:#e5e7eb; overflow:hidden; display:none; }}
#kDeskAiPanel .ai-progress.active {{ display:block; }}
#kDeskAiPanel .ai-progress span {{ display:block; width:36%; height:100%; background:#00796b; animation:kDeskAiMove 1.15s infinite ease-in-out; }}
@keyframes kDeskAiMove {{ 0% {{ transform:translateX(-110%); }} 100% {{ transform:translateX(310%); }} }}
#kDeskAiPanel .ai-content {{ padding:12px 14px 14px; }}
#kDeskAiPanel .ai-summary-grid {{ display:grid; grid-template-columns:minmax(120px,160px) minmax(0,1fr) minmax(210px,280px); gap:10px; align-items:stretch; }}
#kDeskAiPanel .ai-risk-card, #kDeskAiPanel .ai-note-card, #kDeskAiPanel .ai-cost-card {{ min-width:0; border:1px solid #edf2f5; border-radius:7px; padding:10px; background:#fff; }}
#kDeskAiPanel .ai-warning-card {{ border:1px solid #facc15; border-radius:6px; padding:9px 10px; background:#fefce8; color:#854d0e; font-size:13px; line-height:1.5; margin-bottom:10px; }}
#kDeskAiPanel .ai-label {{ color:#64748b; font-size:12px; margin-bottom:5px; }}
#kDeskAiPanel .ai-risk {{ display:inline-flex; align-items:center; justify-content:center; min-width:48px; min-height:28px; padding:2px 10px; border-radius:7px; background:#fff7df; color:#8a5a00; font-weight:800; }}
#kDeskAiPanel .ai-note {{ color:#111827; font-size:13px; line-height:1.55; overflow-wrap:anywhere; }}
#kDeskAiPanel .ai-muted {{ color:#64748b; font-size:12px; line-height:1.45; overflow-wrap:anywhere; }}
#kDeskAiPanel .ai-section {{ margin-top:12px; }}
#kDeskAiPanel .ai-section-title {{ font-size:13px; font-weight:700; color:#111827; margin-bottom:7px; }}
#kDeskAiPanel .ai-evidence {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:8px; }}
#kDeskAiPanel .ai-evidence button {{ display:block; width:100%; text-align:left; background:#fff; color:#111827; border-color:#d7e0e6; padding:9px 10px; }}
#kDeskAiPanel .ai-evidence button:hover {{ border-color:#00796b; box-shadow:0 1px 7px rgba(0,121,107,.12); }}
#kDeskAiPanel .ai-evidence-main {{ display:flex; align-items:center; justify-content:space-between; gap:8px; font-weight:700; }}
#kDeskAiPanel .ai-evidence-time {{ color:#64748b; font-size:11px; margin-top:4px; white-space:normal; }}
#kDeskAiPanel .ai-evidence-reason {{ color:#334155; font-size:12px; line-height:1.45; margin-top:5px; white-space:normal; }}
#kDeskAiPanel .ai-audit-card {{ display:block; width:100%; text-align:left; background:#fff; color:#111827; border:1px solid #d7e0e6; border-radius:7px; padding:10px; cursor:pointer; }}
#kDeskAiPanel .ai-audit-card:hover {{ border-color:#00796b; box-shadow:0 1px 7px rgba(0,121,107,.12); }}
#kDeskAiPanel .ai-audit-fields {{ display:grid; grid-template-columns:1fr; gap:6px; margin-top:8px; }}
#kDeskAiPanel .ai-audit-field {{ border-top:1px solid #eef2f7; padding-top:6px; }}
#kDeskAiPanel .ai-audit-field b {{ display:block; color:#475569; font-size:11px; margin-bottom:2px; }}
#kDeskAiPanel .ai-audit-field span {{ display:block; color:#111827; font-size:12px; line-height:1.5; white-space:normal; word-break:break-word; }}
#kDeskAiPanel .ai-chip {{ display:inline-flex; align-items:center; border:1px solid #e2e8f0; border-radius:999px; padding:1px 7px; color:#475569; background:#f8fafc; font-size:11px; font-weight:700; }}
#kDeskAiPanel .ai-empty {{ color:#94a3b8; font-size:13px; }}
#kDeskAiPanel .ai-chat {{ border:1px solid #edf2f5; border-radius:7px; background:#fbfdff; overflow:hidden; }}
#kDeskAiPanel .ai-chat-log {{ max-height:360px; overflow-y:auto; padding:10px; display:flex; flex-direction:column; gap:10px; }}
#kDeskAiPanel .ai-msg {{ max-width:92%; border:1px solid #e2e8f0; border-radius:6px; padding:9px 10px; background:white; color:#111827; font-size:13px; line-height:1.55; overflow-wrap:anywhere; }}
#kDeskAiPanel .ai-msg.user {{ align-self:flex-end; background:#263238; border-color:#263238; color:#fff; }}
#kDeskAiPanel .ai-msg.assistant {{ align-self:flex-start; }}
#kDeskAiPanel .ai-msg-meta {{ font-size:11px; opacity:.72; margin-bottom:4px; }}
#kDeskAiPanel .ai-msg-points {{ margin-top:6px; padding-left:18px; color:inherit; }}
#kDeskAiPanel .ai-ticket-row {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:7px; }}
#kDeskAiPanel .ai-ticket-row button {{ padding:3px 7px; font-size:12px; border-color:#cbd5e1; background:#fff; color:#111827; }}
#kDeskAiPanel .ai-chat-input {{ border-top:1px solid #e5e7eb; padding:10px; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:end; background:#fff; }}
#kDeskAiPanel .ai-chat-input textarea {{ width:100%; min-height:68px; max-height:150px; resize:vertical; border:1px solid #d7e0e6; border-radius:7px; padding:8px 9px; font:13px/1.45 Arial,"Microsoft YaHei",sans-serif; box-sizing:border-box; }}
#kDeskAiPanel .ai-chat-state {{ padding:0 10px 10px; color:#64748b; font-size:12px; display:none; }}
#kDeskAiPanel .ai-chat-state.active {{ display:block; }}
tr.kdesk-ai-trade-highlight td {{ background:#fff7cc !important; box-shadow:inset 0 1px 0 #f59e0b,inset 0 -1px 0 #f59e0b; }}
@media (max-width: 980px) {{ #kDeskAiPanel .ai-summary-grid {{ grid-template-columns:1fr; }} #kDeskAiPanel .ai-subtitle {{ display:none; }} #kDeskAiPanel .ai-chat-input {{ grid-template-columns:1fr; }} }}
</style>
<section id="kDeskAiPanel" data-stem="{html.escape(stem)}">
  <div class="ai-top">
    <div class="ai-title-wrap">
      <span class="ai-title">AI交易复核</span>
      <span class="ai-status" id="kDeskAiStatus">读取中</span>
      <span class="ai-subtitle">辅助判断，不自动定性</span>
    </div>
    <div class="ai-actions">
      <button id="kDeskAiRun">发起AI分析</button>
      <button class="secondary" id="kDeskAiRefresh">刷新</button>
    </div>
  </div>
  <div class="ai-progress" id="kDeskAiProgress"><span></span></div>
  <div class="ai-content" id="kDeskAiBody">正在读取AI状态。</div>
</section>
<script>
(function(){{
  const stem = {json.dumps(stem)};
  const statusEl = document.getElementById('kDeskAiStatus');
  const bodyEl = document.getElementById('kDeskAiBody');
  const runBtn = document.getElementById('kDeskAiRun');
  const refreshBtn = document.getElementById('kDeskAiRefresh');
  const progressEl = document.getElementById('kDeskAiProgress');
  let pollTimer = null;
  let chatTimer = null;
  function escapeHtml(v) {{ return String(v ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch])); }}
  function setBusy(busy) {{
    runBtn.disabled = busy;
    progressEl.classList.toggle('active', busy);
    if (!busy && pollTimer) {{
      clearTimeout(pollTimer);
      pollTimer = null;
    }}
  }}
  function schedulePoll() {{
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(load, 1000);
  }}
  function normalizeTicket(v) {{
    return String(v ?? '').trim().replace(/\\.0$/, '');
  }}
  function statusText(status) {{
    return ({{idle:'未分析', queued:'排队中', running:'分析中', done:'已完成', failed:'失败'}})[status] || status || 'unknown';
  }}
  function timeAround(start, end, ticket) {{
    const s = String(start || '').slice(0, 16);
    const e = String(end || start || '').slice(0, 16);
    const canApplyWindow = typeof windowStartInput !== 'undefined'
      && typeof windowEndInput !== 'undefined'
      && typeof applyWindow === 'function';
    if (ticket) {{
      setAiHighlightedTicket(ticket);
      return;
    }}
    if (canApplyWindow) {{
      windowStartInput.value = s;
      windowEndInput.value = e;
      applyWindow();
      window.scrollTo({{top: 0, behavior: 'smooth'}});
    }}
  }}
  function costHtml(est) {{
    if (!est) return '<div class="ai-muted">暂无成本预估</div>';
    if (est.error) return `<div class="ai-muted">成本预估失败：${{escapeHtml(est.error)}}</div>`;
    return `<div class="ai-muted">模型：${{escapeHtml(est.model || '')}}<br>预计费用：$${{Number(est.estimated_cost_usd || 0).toFixed(4)}}<br>输入：${{escapeHtml(est.estimated_input_tokens || '')}} tokens<br>输出：${{escapeHtml(est.estimated_output_tokens || '')}} tokens<br>调用：${{escapeHtml(est.api_call_count || est.chunk_count || '')}} 次<br>样本订单：${{escapeHtml(est.sampled_trade_count || '')}}</div>`;
  }}
  function formatDuration(seconds) {{
    const n = Number(seconds || 0);
    if (!Number.isFinite(n) || n <= 0) return '0 秒';
    if (n < 60) return n.toFixed(1) + ' 秒';
    return Math.floor(n / 60) + ' 分 ' + Math.round(n % 60) + ' 秒';
  }}
  function renderIdle(job) {{
    const est = job.estimate || null;
    bodyEl.innerHTML = `<div class="ai-summary-grid">
      <div class="ai-risk-card"><div class="ai-label">状态</div><div class="ai-risk">未分析</div></div>
      <div class="ai-note-card"><div class="ai-label">说明</div><div class="ai-note">${{escapeHtml(job.message || '点击“发起AI分析”后开始处理。')}}</div></div>
      <div class="ai-cost-card"><div class="ai-label">调用预估</div>${{costHtml(est)}}</div>
    </div>`;
  }}
  function renderRunning(job) {{
    const est = job.estimate || null;
    const progress = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    bodyEl.innerHTML = `<div class="ai-summary-grid">
      <div class="ai-risk-card"><div class="ai-label">状态</div><div class="ai-risk">处理中</div></div>
      <div class="ai-note-card"><div class="ai-label">进度</div><div class="ai-note">${{escapeHtml(job.message || 'AI正在分析交易数据。')}}</div><div class="ai-muted" style="margin-top:6px">已耗时：${{formatDuration(job.elapsed_seconds)}}。后台处理中，页面会每 1 秒自动检查一次，完成后直接显示结果。</div></div>
      <div class="ai-cost-card"><div class="ai-label">调用预估</div>${{costHtml(est)}}</div>
    </div>`;
  }}
  function renderRunning(job) {{
    const progress = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    bodyEl.innerHTML = `<div class="ai-summary-grid">
      <div class="ai-risk-card"><div class="ai-label">进度</div><div class="ai-risk">${{progress}}%</div></div>
      <div class="ai-note-card"><div class="ai-label">当前步骤</div><div class="ai-note">${{escapeHtml(job.message || 'AI正在分析交易数据。')}}</div><div class="ai-muted" style="margin-top:6px">已耗时：${{formatDuration(job.elapsed_seconds)}}。页面每 1 秒自动刷新一次，完成后直接显示结果。</div></div>
      <div class="ai-cost-card"><div class="ai-label">说明</div><div class="ai-muted">二级指标和证据包只在发起AI分析后计算。</div></div>
    </div>`;
  }}
  function evidenceOrderHtml(o) {{
    const title = escapeHtml(o.ticket || 'order');
    const time = [o.open_time, o.close_time].filter(Boolean).map(escapeHtml).join(' -> ');
    const reason = escapeHtml(o.reason || '');
    const confidence = o.confidence ? `<span class="ai-chip">${{escapeHtml(o.confidence)}}</span>` : '';
    return `<button data-ai-ticket="${{escapeHtml(o.ticket || '')}}" data-ai-start="${{escapeHtml(o.open_time)}}" data-ai-end="${{escapeHtml(o.close_time)}}" title="${{reason}}">
      <span class="ai-evidence-main"><span>${{title}}</span>${{confidence}}</span>
      <span class="ai-evidence-time">${{time || '无时间'}}</span>
      <span class="ai-evidence-reason">${{reason || '无说明'}}</span>
    </button>`;
  }}
  function evidenceSegmentHtml(s) {{
    const title = escapeHtml(s.segment_id || 'segment');
    const time = [s.start_time, s.end_time].filter(Boolean).map(escapeHtml).join(' -> ');
    const reason = escapeHtml(s.reason || '');
    const confidence = s.confidence ? `<span class="ai-chip">${{escapeHtml(s.confidence)}}</span>` : '';
    return `<button data-ai-start="${{escapeHtml(s.start_time)}}" data-ai-end="${{escapeHtml(s.end_time)}}" title="${{reason}}">
      <span class="ai-evidence-main"><span>${{title}}</span>${{confidence}}</span>
      <span class="ai-evidence-time">${{time || '无时间'}}</span>
      <span class="ai-evidence-reason">${{reason || '无说明'}}</span>
    </button>`;
  }}
  function chatMessageHtml(msg) {{
    const role = msg.role === 'user' ? 'user' : 'assistant';
    const title = role === 'user' ? '我的追问' : 'AI回答';
    const points = Array.isArray(msg.key_points) && msg.key_points.length
      ? `<ul class="ai-msg-points">${{msg.key_points.map(p => `<li>${{escapeHtml(p)}}</li>`).join('')}}</ul>` : '';
    const tickets = Array.isArray(msg.referenced_tickets) ? msg.referenced_tickets.filter(Boolean) : [];
    const ticketHtml = tickets.length
      ? `<div class="ai-ticket-row">${{tickets.map(t => `<button type="button" data-chat-ticket="${{escapeHtml(t)}}">#${{escapeHtml(t)}}</button>`).join('')}}</div>` : '';
    return `<div class="ai-msg ${{role}}">
      <div class="ai-msg-meta">${{title}} · ${{escapeHtml(msg.created_at || '')}}</div>
      <div>${{escapeHtml(msg.content || '')}}</div>${{points}}${{ticketHtml}}
    </div>`;
  }}
  function renderChat(chat) {{
    const log = document.getElementById('kDeskAiChatLog');
    if (!log) return;
    const messages = (chat && Array.isArray(chat.messages)) ? chat.messages : [];
    log.innerHTML = messages.map(chatMessageHtml).join('') || '<div class="ai-empty">暂无追问记录</div>';
    log.querySelectorAll('[data-chat-ticket]').forEach(btn => btn.addEventListener('click', () => setAiHighlightedTicket(btn.getAttribute('data-chat-ticket'))));
    log.scrollTop = log.scrollHeight;
  }}
  async function loadChat() {{
    try {{
      const res = await fetch('/api/ai/chat/' + encodeURIComponent(stem), {{cache:'no-store'}});
      if (res.ok) renderChat(await res.json());
    }} catch (err) {{
      const state = document.getElementById('kDeskAiChatState');
      if (state) {{
        state.textContent = '追问记录读取失败：' + (err.message || String(err));
        state.classList.add('active');
      }}
    }}
  }}
  function setChatSending(sending, text) {{
    const btn = document.getElementById('kDeskAiChatSend');
    const input = document.getElementById('kDeskAiChatInput');
    const state = document.getElementById('kDeskAiChatState');
    if (btn) btn.disabled = sending;
    if (input) input.disabled = sending;
    if (chatTimer) {{
      clearInterval(chatTimer);
      chatTimer = null;
    }}
    if (state) {{
      state.textContent = text || '';
      state.classList.toggle('active', Boolean(text));
      if (sending) {{
        const started = Date.now();
        chatTimer = setInterval(() => {{
          state.textContent = `${{text || 'AI思考中'}} 已耗时 ${{formatDuration((Date.now() - started) / 1000)}}`;
        }}, 1000);
      }}
    }}
  }}
  async function sendChat() {{
    const input = document.getElementById('kDeskAiChatInput');
    if (!input) return;
    const question = input.value.trim();
    if (!question) return;
    setChatSending(true, 'AI思考中，正在结合当前分析上下文回答...');
    try {{
      const body = new URLSearchParams();
      body.set('stem', stem);
      body.set('question', question);
      const res = await fetch('/api/ai/chat', {{method:'POST', body}});
      const data = await res.json().catch(() => ({{error:'invalid json response'}}));
      if (!res.ok) throw new Error(data.error || data.message || '追问失败');
      input.value = '';
      renderChat(data.chat);
      setChatSending(false, '');
    }} catch (err) {{
      setChatSending(false, '追问失败：' + (err.message || String(err)));
    }}
  }}
  function attachChatHandlers() {{
    const btn = document.getElementById('kDeskAiChatSend');
    const input = document.getElementById('kDeskAiChatInput');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', sendChat);
    if (input) input.addEventListener('keydown', ev => {{
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') sendChat();
    }});
  }}
  function renderDone(job) {{
    const r = job.result || {{}};
    const est = r.cost_estimate || job.estimate || null;
    const orders = (r.evidence_orders || []).slice(0, 20);
    const segments = (r.evidence_segments || []).slice(0, 10);
    const elapsed = job.elapsed_seconds || r.elapsed_seconds || null;
    const accountClass = r.account_class || '-';
    const judgment = r.violation_judgment || '';
    const shortSummary = r.short_summary || r.conclusion || '';
    const fallback = r.model_call_failed || r.analysis_source === 'local_fallback'
      || String(r.explanation || '').includes('模型调用失败')
      || String(r.behavior_definition || '').includes('本地统计兜底');
    const fallbackWarning = fallback
      ? `<div class="ai-warning-card"><b>当前展示的是本地兜底结果，不是模型正式分析。</b><br>${{escapeHtml(r.model_error || '模型调用或结果解析失败，系统使用本地二级指标生成兜底结论。建议重新发起AI分析；若再次出现，请查看服务日志中的 model_error。')}}</div>` : '';
    bodyEl.innerHTML = `${{fallbackWarning}}<div class="ai-summary-grid">
      <div class="ai-risk-card"><div class="ai-label">账户定义</div><div class="ai-risk">${{escapeHtml(accountClass)}}</div><div class="ai-muted" style="margin-top:6px">风险：${{escapeHtml(r.risk_level || '-')}}<br>${{escapeHtml(judgment)}}</div></div>
      <div class="ai-note-card"><div class="ai-label">结论</div><div class="ai-note">${{escapeHtml(shortSummary)}}</div><div class="ai-muted" style="margin-top:6px">${{escapeHtml(r.account_class_reason || '')}}</div></div>
      <div class="ai-cost-card"><div class="ai-label">调用信息</div>${{costHtml(est)}}<div class="ai-muted" style="margin-top:6px">实际耗时：${{elapsed ? formatDuration(elapsed) : '无记录'}}</div></div>
    </div>
    <div class="ai-section"><div class="ai-section-title">行为定义</div><div class="ai-muted">${{escapeHtml(r.behavior_definition || '')}}</div></div>
    <div class="ai-section"><div class="ai-section-title">意图推测</div><div class="ai-muted">${{escapeHtml(r.inferred_intent || '')}}</div></div>
    <div class="ai-section"><div class="ai-section-title">关键指标解释</div><div class="ai-muted">${{escapeHtml(r.key_metric_interpretation || '')}}</div></div>
    <div class="ai-section"><div class="ai-section-title">分析说明</div><div class="ai-muted">${{escapeHtml(r.explanation || '')}}</div></div>
    <div class="ai-section"><div class="ai-section-title">证据订单</div><div class="ai-evidence">${{orders.map(evidenceOrderHtml).join('') || '<span class="ai-empty">无</span>'}}</div></div>
    <div class="ai-section"><div class="ai-section-title">证据区间</div><div class="ai-evidence">${{segments.map(evidenceSegmentHtml).join('') || '<span class="ai-empty">无</span>'}}</div></div>
    <div class="ai-section"><div class="ai-section-title">局限</div><div class="ai-muted">${{escapeHtml((r.limitations || []).join('；') || '无')}}</div></div>
    <div class="ai-section">
      <div class="ai-section-title">追问AI</div>
      <div class="ai-chat">
        <div class="ai-chat-log" id="kDeskAiChatLog"><div class="ai-empty">正在读取追问记录...</div></div>
        <div class="ai-chat-input">
          <textarea id="kDeskAiChatInput" placeholder="输入你想追问的点，例如：为什么判断像延迟套利？哪些订单最关键？"></textarea>
          <button id="kDeskAiChatSend" type="button">发送</button>
        </div>
        <div class="ai-chat-state" id="kDeskAiChatState"></div>
      </div>
      <div class="ai-muted" style="margin-top:6px">追问会保留上下文；系统只发送分析摘要、本地指标、关键订单和最近对话，避免重复发送全量交易。</div>
    </div>`;
    bodyEl.querySelectorAll('[data-ai-start]').forEach(btn => btn.addEventListener('click', () => timeAround(
      btn.getAttribute('data-ai-start'),
      btn.getAttribute('data-ai-end'),
      btn.getAttribute('data-ai-ticket')
    )));
    attachChatHandlers();
    loadChat();
  }}
  function quoteAuditHtml(q) {{
    const title = escapeHtml(q.reason_code || q.question || 'quote_audit');
    const time = [q.start, q.end].filter(Boolean).map(escapeHtml).join(' -> ');
    const tfs = Array.isArray(q.timeframes) ? q.timeframes.join(', ') : (q.timeframes || '');
    const tickets = Array.isArray(q.related_tickets) ? q.related_tickets.join(', ') : (q.related_tickets || '');
    const legacy = !(q.why_needed || q.data_to_check || q.if_confirmed_conclusion || q.classification_impact);
    const field = (label, value, fallback='-') => `<div class="ai-audit-field"><b>${{label}}</b><span>${{escapeHtml(value || fallback)}}</span></div>`;
    return `<button class="ai-audit-card" data-ai-start="${{escapeHtml(q.start)}}" data-ai-end="${{escapeHtml(q.end)}}" title="${{escapeHtml(q.classification_impact || q.expected_decision_impact || '')}}">
      <span class="ai-evidence-main"><span>${{title}}</span><span class="ai-chip">${{escapeHtml(tfs || q.priority || 'quote')}}</span></span>
      <span class="ai-evidence-time">${{time || 'no window'}} · tickets: ${{escapeHtml(tickets || '-')}}</span>
      <div class="ai-audit-fields">
        ${{field('当前不确定点', q.current_uncertainty || q.question || q.reason)}}
        ${{field('为什么要这些数据', q.why_needed || (legacy ? '旧报告未细化该字段：需要重新发起AI分析，让模型说明该报价窗口能验证哪一个风险假设。' : ''))}}
        ${{field('要查什么', q.data_to_check || [q.symbol, time, tfs].filter(Boolean).join(' / '))}}
        ${{field('如果查到什么，就支持风险假设', q.pass_condition)}}
        ${{field('拿到后得到什么结果', q.if_confirmed_conclusion || q.expected_decision_impact)}}
        ${{field('如果没查到，如何处理', q.if_not_confirmed_conclusion || q.fail_condition)}}
        ${{field('对定级影响', q.classification_impact || q.expected_decision_impact)}}
      </div>
    </button>`;
  }}
  function dataRequestHtml(q) {{
    const legacy = !(q.why_needed || q.data_to_check || q.if_confirmed_conclusion || q.classification_impact);
    const field = (label, value, fallback='-') => `<div class="ai-audit-field"><b>${{label}}</b><span>${{escapeHtml(value || fallback)}}</span></div>`;
    return `<button type="button" class="ai-audit-card secondary" title="${{escapeHtml(q.classification_impact || q.expected_decision_impact || '')}}">
      <span class="ai-evidence-main"><span>${{escapeHtml(q.data_type || 'data_request')}}</span><span class="ai-chip">${{escapeHtml(q.priority || '-')}}</span></span>
      <div class="ai-audit-fields">
        ${{field('当前不确定点', q.current_uncertainty || q.reason)}}
        ${{field('为什么要这些数据', q.why_needed || (legacy ? '旧报告未细化该字段：需要重新发起AI分析，让模型说明该数据能验证哪一个风险假设。' : ''))}}
        ${{field('要查什么', q.data_to_check || q.data_type)}}
        ${{field('如果查到什么，就支持风险假设', q.pass_condition)}}
        ${{field('拿到后得到什么结果', q.if_confirmed_conclusion || q.expected_decision_impact)}}
        ${{field('如果没查到，如何处理', q.if_not_confirmed_conclusion || q.fail_condition)}}
        ${{field('对定级影响', q.classification_impact || q.expected_decision_impact)}}
      </div>
    </button>`;
  }}
  function supplementalAuditHtml(audit, r) {{
    audit = audit || {{}};
    const summary = audit.summary || {{}};
    const quoteItems = Array.isArray(audit.quote_audit_results) ? audit.quote_audit_results : [];
    const dataItems = Array.isArray(audit.data_request_results) ? audit.data_request_results : [];
    const statusText = r.supplemental_pass_completed
      ? '已完成二次AI复核'
      : (r.supplemental_model_call_failed ? '二次AI复核失败，当前保留首轮结论' : (quoteItems.length || dataItems.length ? '已生成补充数据包，未完成二次复核' : '未触发二次补充'));
    const quoteCards = quoteItems.map(item => {{
      const tfs = item.timeframe_results || {{}};
      const tfText = Object.keys(tfs).map(tf => `${{tf}}：${{tfs[tf].rows || 0}}根`).join('；');
      const status = item.status === 'fulfilled' ? '已拿到' : (item.status === 'empty' ? '无数据' : '未拿到');
      return `<div class="ai-audit-card">
        <span class="ai-evidence-main"><span>${{escapeHtml(item.reason_code || '报价窗口')}}</span><span class="ai-chip">${{escapeHtml(status)}}</span></span>
        <span class="ai-evidence-time">${{escapeHtml(item.actual_start || item.requested_start || '')}} -> ${{escapeHtml(item.actual_end || item.requested_end || '')}}</span>
        <div class="ai-audit-fields">
          <div class="ai-audit-field"><b>拿到了什么</b><span>${{escapeHtml(item.obtained_data_summary || (item.status === 'fulfilled' ? '本地报价缓存OHLC/Spread窗口数据' : (item.unavailable_reason || '-')))}}</span></div>
          <div class="ai-audit-field"><b>补充了什么</b><span>${{escapeHtml(item.supplemented_evidence_summary || `覆盖周期：${{tfText || '-'}}`)}}</span></div>
          <div class="ai-audit-field"><b>起到什么作用</b><span>${{escapeHtml(item.review_effect || '作为二次AI复核输入，用于支持或削弱价格窗口类怀疑。')}}</span></div>
          <div class="ai-audit-field"><b>仍然不能证明什么</b><span>本地报价缓存不是tick级bid/ask，也不是成交回报日志，不能单独确认执行延迟或外部报价套利。</span></div>
        </div>
      </div>`;
    }}).join('');
    const dataCards = dataItems.map(item => `<div class="ai-audit-card secondary">
      <span class="ai-evidence-main"><span>${{escapeHtml(item.data_type || '其他数据')}}</span><span class="ai-chip">未拿到</span></span>
      <div class="ai-audit-fields">
        <div class="ai-audit-field"><b>没拿到的数据</b><span>${{escapeHtml(item.requested_data || item.data_type || '-')}}</span></div>
        <div class="ai-audit-field"><b>为什么没拿到</b><span>${{escapeHtml(item.why_not_obtained || item.unavailable_reason || '当前没有配置该类数据源。')}}</span></div>
        <div class="ai-audit-field"><b>对结论的影响</b><span>${{escapeHtml(item.review_effect || '该项不能作为已确认事实，只能作为仍未解决的限制条件。')}}</span></div>
      </div>
    </div>`).join('');
    return `<div class="ai-section">
      <div class="ai-section-title">二次补充核查</div>
      <div class="ai-muted">${{escapeHtml(statusText)}}；已拿到报价窗口 ${{escapeHtml(summary.quote_requests_fulfilled || 0)}}/${{escapeHtml(summary.quote_requests_total || 0)}}，未拿到其他数据 ${{escapeHtml(summary.data_requests_unavailable || 0)}} 项。</div>
      <div class="ai-evidence" style="margin-top:8px">${{quoteCards || '<span class="ai-empty">没有拿到新的报价窗口数据</span>'}}</div>
      <div class="ai-evidence" style="margin-top:8px">${{dataCards || '<span class="ai-empty">没有未获取的其他数据</span>'}}</div>
    </div>`;
  }}
  function renderDone(job) {{
    const r = job.result || {{}};
    const est = r.cost_estimate || job.estimate || null;
    const orders = (r.evidence_orders || []).slice(0, 20);
    const segments = (r.evidence_segments || []).slice(0, 10);
    const quoteRequests = (r.quote_audit_requests || []).slice(0, 3);
    const dataRequests = (r.data_requests || []).slice(0, 8);
    const elapsed = job.elapsed_seconds || r.elapsed_seconds || null;
    const supplemental = supplementalAuditHtml(r.supplemental_audit || {{}}, r);
    const fallback = r.model_call_failed || r.analysis_source === 'local_fallback';
    const fallbackWarning = fallback
      ? `<div class="ai-warning-card"><b>当前展示的是本地兜底结果，不是模型正式分析。</b><br>${{escapeHtml(r.model_error || '模型调用或结果解析失败。')}}</div>` : '';
    bodyEl.innerHTML = `${{fallbackWarning}}<div class="ai-summary-grid">
      <div class="ai-risk-card"><div class="ai-label">账户定义</div><div class="ai-risk">${{escapeHtml(r.account_class || '-')}}</div><div class="ai-muted" style="margin-top:6px">风险：${{escapeHtml(r.risk_level || '-')}}<br>${{escapeHtml(r.violation_judgment || '')}}</div></div>
      <div class="ai-note-card"><div class="ai-label">结论</div><div class="ai-note">${{escapeHtml(r.short_summary || r.conclusion || '')}}</div><div class="ai-muted" style="margin-top:6px">${{escapeHtml(r.account_class_reason || '')}}</div></div>
      <div class="ai-cost-card"><div class="ai-label">调用信息</div>${{costHtml(est)}}<div class="ai-muted" style="margin-top:6px">实际耗时：${{elapsed ? formatDuration(elapsed) : '无记录'}}</div></div>
    </div>
    <div class="ai-section"><div class="ai-section-title">行为定义</div><div class="ai-muted">${{escapeHtml(r.behavior_definition || '')}}</div></div>
    <div class="ai-section"><div class="ai-section-title">意图推测</div><div class="ai-muted">${{escapeHtml(r.inferred_intent || '')}}</div></div>
    <div class="ai-section"><div class="ai-section-title">关键指标解释</div><div class="ai-muted">${{escapeHtml(r.key_metric_interpretation || '')}}</div></div>
    <div class="ai-section"><div class="ai-section-title">分析说明</div><div class="ai-muted">${{escapeHtml(r.explanation || '')}}</div></div>
    ${{supplemental}}
    <div class="ai-section"><div class="ai-section-title">证据订单</div><div class="ai-evidence">${{orders.map(evidenceOrderHtml).join('') || '<span class="ai-empty">无</span>'}}</div></div>
    <div class="ai-section"><div class="ai-section-title">证据区间</div><div class="ai-evidence">${{segments.map(evidenceSegmentHtml).join('') || '<span class="ai-empty">无</span>'}}</div></div>
    <div class="ai-section"><div class="ai-section-title">局限</div><div class="ai-muted">${{escapeHtml((r.limitations || []).join('；') || '无')}}</div></div>
    <div class="ai-section">
      <div class="ai-section-title">追问AI</div>
      <div class="ai-chat">
        <div class="ai-chat-log" id="kDeskAiChatLog"><div class="ai-empty">正在读取追问记录...</div></div>
        <div class="ai-chat-input">
          <textarea id="kDeskAiChatInput" placeholder="输入你想追问的点"></textarea>
          <button id="kDeskAiChatSend" type="button">发送</button>
        </div>
        <div class="ai-chat-state" id="kDeskAiChatState"></div>
      </div>
    </div>`;
    bodyEl.querySelectorAll('[data-ai-start]').forEach(btn => btn.addEventListener('click', () => timeAround(
      btn.getAttribute('data-ai-start'),
      btn.getAttribute('data-ai-end'),
      btn.getAttribute('data-ai-ticket')
    )));
    attachChatHandlers();
    loadChat();
  }}
  function render(job) {{
    const status = job.status || 'idle';
    statusEl.textContent = statusText(status);
    statusEl.className = 'ai-status ' + status;
    setBusy(status === 'queued' || status === 'running');
    if (status === 'done' && job.result) renderDone(job);
    else if (status === 'queued' || status === 'running') renderRunning(job);
    else if (status === 'failed') {{
      bodyEl.innerHTML = `<div class="ai-note-card"><div class="ai-label">失败原因</div><div class="ai-note">${{escapeHtml(job.message || 'AI分析失败')}}</div></div>`;
    }} else renderIdle(job);
    if (status === 'queued' || status === 'running') schedulePoll();
  }}
  async function load() {{
    try {{
      const res = await fetch('/api/ai/status/' + encodeURIComponent(stem), {{cache:'no-store'}});
      render(await res.json());
    }} catch (err) {{
      statusEl.textContent = '读取失败';
      statusEl.className = 'ai-status failed';
      bodyEl.innerHTML = `<div class="ai-note-card"><div class="ai-note">${{escapeHtml(err.message || String(err))}}</div></div>`;
      setBusy(false);
    }}
  }}
  async function run() {{
    setBusy(true);
    statusEl.textContent = '提交中';
    statusEl.className = 'ai-status running';
    bodyEl.innerHTML = '<div class="ai-note-card"><div class="ai-note">正在提交AI分析任务。</div></div>';
    const body = new URLSearchParams();
    body.set('stem', stem);
    try {{
      const res = await fetch('/api/ai/analyze', {{method:'POST', body}});
      if (!res.ok) throw new Error(await res.text());
      schedulePoll();
    }} catch (err) {{
      statusEl.textContent = '提交失败';
      statusEl.className = 'ai-status failed';
      bodyEl.innerHTML = `<div class="ai-note-card"><div class="ai-note">${{escapeHtml(err.message || String(err))}}</div></div>`;
      setBusy(false);
    }}
  }}
  runBtn.addEventListener('click', run);
  refreshBtn.addEventListener('click', load);
  load();

  let selectedAiTicket = '';
  let originalDraw = null;
  function setAiHighlightedTicket(ticket) {{
    selectedAiTicket = normalizeTicket(ticket);
    if (typeof window !== 'undefined') window.kDeskAiSelectedTicket = selectedAiTicket;
    focusHighlightedTrade();
    if (typeof draw === 'function') draw(false);
  }}
  function findHighlightedTrade() {{
    const wanted = selectedAiTicket || (typeof window !== 'undefined' ? window.kDeskAiSelectedTicket : '');
    if (!wanted || typeof DATA === 'undefined' || !Array.isArray(DATA.trades)) return null;
    return DATA.trades.find(t => normalizeTicket(t.Ticket) === normalizeTicket(wanted)) || null;
  }}
  function focusHighlightedTrade() {{
    const t = findHighlightedTrade();
    if (!t) return;
    if (typeof symbol !== 'undefined' && t.Item && t.Item !== symbol && typeof symbolSelect !== 'undefined') {{
      symbolSelect.value = t.Item;
      symbolSelect.dispatchEvent(new Event('change'));
    }}
    if (typeof windowStartInput !== 'undefined' && typeof windowEndInput !== 'undefined' && typeof applyWindow === 'function') {{
      const openMs = typeof toMs === 'function' ? toMs(t["Open Time"]) : Date.parse(String(t["Open Time"]).replace(' ', 'T'));
      const closeMs = typeof toMs === 'function' ? toMs(t["Close Time"]) : Date.parse(String(t["Close Time"]).replace(' ', 'T'));
      if (Number.isFinite(openMs) && Number.isFinite(closeMs)) {{
        const holdMs = Math.max(60000, closeMs - openMs);
        const padMs = Math.max(10 * 60000, Math.min(2 * 3600 * 1000, holdMs * 0.8));
        windowStartInput.value = formatAiInputTime(openMs - padMs);
        windowEndInput.value = formatAiInputTime(closeMs + padMs);
        applyWindow();
      }}
    }}
  }}
  function formatAiInputTime(ms) {{
    const d = new Date(ms);
    const p = n => String(n).padStart(2, '0');
    return `${{d.getFullYear()}}-${{p(d.getMonth()+1)}}-${{p(d.getDate())}} ${{p(d.getHours())}}:${{p(d.getMinutes())}}:${{p(d.getSeconds())}}`;
  }}
  function drawAiHighlightOverlay() {{
    const t = findHighlightedTrade();
    if (!t || typeof canvas === 'undefined' || typeof ctx === 'undefined' || typeof bars === 'undefined' || !bars.length) return;
    const rect = canvas.getBoundingClientRect(), W = rect.width, H = rect.height;
    const pad = {{l:72, r:24, t:20, b:74}}, plotW = W - pad.l - pad.r;
    const profitH = 118, profitGap = 30;
    const plotH = Math.max(280, H - pad.t - pad.b - profitH - profitGap);
    const vb = typeof visibleBars === 'function' ? visibleBars() : [];
    const vt = typeof visibleTrades === 'function' ? visibleTrades() : [];
    const lim = typeof displayLimit === 'function' ? displayLimit() : 300;
    const shown = vt.slice(0, lim);
    if (!vb.length) return;
    const prices = [];
    vb.forEach(([b]) => prices.push(Number(b.low), Number(b.high)));
    shown.forEach(row => prices.push(Number(row["Open Plot Price"] ?? row["Open Price"]), Number(row["Close Plot Price"] ?? row["Close Price"])));
    prices.push(Number(t["Open Plot Price"] ?? t["Open Price"]), Number(t["Close Plot Price"] ?? t["Close Price"]));
    let lo = Math.min(...prices), hi = Math.max(...prices);
    const d = typeof digits === 'function' ? digits() : 2;
    const margin = Math.max(d === 2 ? 0.5 : 0.0002, (hi - lo) * 0.08);
    lo -= margin; hi += margin;
    const y = p => pad.t + (hi - p) / Math.max(hi - lo, 0.0000001) * plotH;
    const xIndex = idx => typeof xForIndex === 'function' ? xForIndex(idx, pad, plotW) : pad.l + (idx - viewStart) / Math.max(viewEnd - viewStart, 1) * plotW;
    const xMsValue = ms => typeof timeToCanvasX === 'function' ? timeToCanvasX(ms, pad, plotW) : xIndex(typeof findIndex === 'function' ? findIndex(formatAiInputTime(ms)) : 0);
    const openIdx = Number.isFinite(t.openIdx) ? t.openIdx : (typeof findIndex === 'function' ? findIndex(t["Open Time"]) : 0);
    const closeIdx = Number.isFinite(t.closeIdx) ? t.closeIdx : (typeof findIndex === 'function' ? findIndex(t["Close Time"]) : openIdx);
    const xo = typeof showNoQuoteTime !== 'undefined' && showNoQuoteTime ? xMsValue(toMs(t["Open Time"])) : xIndex(openIdx);
    const xc = typeof showNoQuoteTime !== 'undefined' && showNoQuoteTime ? xMsValue(toMs(t["Close Time"])) : xIndex(closeIdx);
    const yo = y(Number(t["Open Plot Price"] ?? t["Open Price"]));
    const yc = y(Number(t["Close Plot Price"] ?? t["Close Price"]));
    if (![xo, xc, yo, yc].every(Number.isFinite)) return;
    ctx.save();
    ctx.shadowColor = 'rgba(245,158,11,0.55)';
    ctx.shadowBlur = 10;
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 4;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(xo, yo);
    ctx.lineTo(xc, yc);
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#f59e0b';
    ctx.strokeStyle = '#111827';
    ctx.lineWidth = 2;
    [[xo, yo], [xc, yc]].forEach(([xx, yy]) => {{
      ctx.beginPath();
      ctx.arc(xx, yy, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }});
    const label = `AI选中 #${{normalizeTicket(t.Ticket)}}`;
    const lx = Math.max(pad.l + 4, Math.min((xo + xc) / 2 - 48, pad.l + plotW - 116));
    const ly = Math.max(pad.t + 4, Math.min((yo + yc) / 2 - 28, pad.t + plotH - 24));
    ctx.fillStyle = '#111827';
    ctx.fillRect(lx, ly, 112, 22);
    ctx.fillStyle = '#fff';
    ctx.font = '12px Arial';
    ctx.fillText(label, lx + 7, ly + 15);
    ctx.restore();
  }}
  function highlightAiTradeTableRow() {{
    const wanted = selectedAiTicket || (typeof window !== 'undefined' ? window.kDeskAiSelectedTicket : '');
    const table = document.getElementById('tradeTable');
    if (!wanted || !table) return;
    table.querySelectorAll('tr.kdesk-ai-trade-highlight').forEach(row => row.classList.remove('kdesk-ai-trade-highlight'));
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {{
      const first = row.querySelector('td');
      if (first && normalizeTicket(first.textContent) === normalizeTicket(wanted)) {{
        row.classList.add('kdesk-ai-trade-highlight');
        row.scrollIntoView({{block:'center', behavior:'smooth'}});
      }}
    }});
  }}
  function installAiChartHighlighter(attempt = 0) {{
    if (typeof draw !== 'function' || typeof canvas === 'undefined' || typeof DATA === 'undefined') {{
      if (attempt < 80) setTimeout(() => installAiChartHighlighter(attempt + 1), 120);
      return;
    }}
    if (originalDraw) return;
    originalDraw = draw;
    draw = function(...args) {{
      const ret = originalDraw.apply(this, args);
      try {{
        drawAiHighlightOverlay();
        highlightAiTradeTableRow();
      }} catch (err) {{
        console.warn('AI highlight failed', err);
      }}
      return ret;
    }};
    if (selectedAiTicket) draw(false);
  }}
  setTimeout(() => installAiChartHighlighter(), 0);
}})();
</script>
"""


def inject_ai_panel(html_text: str, chart_name: str) -> str:
    if "id=\"kDeskAiPanel\"" in html_text:
        return html_text
    stem = stem_from_chart_name(chart_name)
    panel = build_ai_panel_html(stem)
    if "</header>" in html_text:
        return html_text.replace("</header>", "</header>\n" + panel, 1)
    return html_text.replace("</body>", panel + "\n</body>", 1)


def inject_ai_panel_legacy(html_text: str, chart_name: str) -> str:
    if "id=\"kDeskAiPanel\"" in html_text:
        return html_text
    stem = stem_from_chart_name(chart_name)
    panel = f"""
<style>
#kDeskAiPanel {{ margin:12px 18px; background:#fff; border:1px solid #d7e0e6; border-radius:8px; padding:12px; font-family:Arial,"Microsoft YaHei",sans-serif; box-shadow:0 2px 10px rgba(15,23,42,.05); }}
#kDeskAiPanel .ai-head {{ display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }}
#kDeskAiPanel .ai-title {{ font-weight:800; color:#1f2937; }}
#kDeskAiPanel .ai-status {{ color:#64748b; font-size:13px; }}
#kDeskAiPanel .ai-body {{ margin-top:10px; color:#1f2937; font-size:13px; line-height:1.5; }}
#kDeskAiPanel .ai-risk {{ display:inline-block; padding:2px 8px; border-radius:7px; background:#fff7df; color:#8a5a00; font-weight:700; }}
#kDeskAiPanel button {{ border:1px solid #00796b; background:#00796b; color:white; border-radius:7px; padding:6px 9px; cursor:pointer; }}
#kDeskAiPanel button.secondary {{ background:white; color:#1f2937; border-color:#d7e0e6; }}
#kDeskAiPanel .ai-evidence {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
</style>
<section id="kDeskAiPanel" data-stem="{html.escape(stem)}">
  <div class="ai-head">
    <div><span class="ai-title">AI交易复核</span> <span class="ai-status" id="kDeskAiStatus">读取中</span></div>
    <div>
      <button id="kDeskAiRun">发起AI分析</button>
      <button class="secondary" id="kDeskAiRefresh">刷新</button>
    </div>
  </div>
  <div class="ai-body" id="kDeskAiBody">AI为辅助判断，不自动定性，不影响图表生成。</div>
</section>
<script>
(function(){{
  const stem = {json.dumps(stem)};
  const statusEl = document.getElementById('kDeskAiStatus');
  const bodyEl = document.getElementById('kDeskAiBody');
  const runBtn = document.getElementById('kDeskAiRun');
  const refreshBtn = document.getElementById('kDeskAiRefresh');
  function escapeHtml(v) {{ return String(v ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch])); }}
  function timeAround(start, end) {{
    const s = String(start || '').slice(0, 16);
    const e = String(end || start || '').slice(0, 16);
    if (windowStartInput && windowEndInput && typeof applyWindow === 'function') {{
      windowStartInput.value = s;
      windowEndInput.value = e;
      applyWindow();
      window.scrollTo({{top: 0, behavior: 'smooth'}});
    }}
  }}
  function render(job) {{
    statusEl.textContent = job.status || 'unknown';
    if (job.status === 'done' && job.result) {{
      const r = job.result;
      const est = r.cost_estimate || job.estimate || null;
      const orders = (r.evidence_orders || []).slice(0, 20);
      const segments = (r.evidence_segments || []).slice(0, 10);
      bodyEl.innerHTML =
        `<div><span class="ai-risk">${{escapeHtml(r.risk_level || '-')}}</span> ${{escapeHtml(r.conclusion || '')}}</div>` +
        (est ? `<div style="margin-top:6px;color:#64748b">成本预估：${{escapeHtml(est.model || '')}} · $${{Number(est.estimated_cost_usd || 0).toFixed(4)}} · 输入约${{escapeHtml(est.estimated_input_tokens || '')}} tokens · 分块${{escapeHtml(est.chunk_count || '')}}</div>` : '') +
        `<div style="margin-top:6px">${{escapeHtml(r.explanation || '')}}</div>` +
        `<div style="margin-top:8px"><b>可疑订单</b></div>` +
        `<div class="ai-evidence">${{orders.map(o => `<button class="secondary" data-ai-start="${{escapeHtml(o.open_time)}}" data-ai-end="${{escapeHtml(o.close_time)}}">${{escapeHtml(o.ticket || 'order')}}</button>`).join('') || '<span>无</span>'}}</div>` +
        `<div style="margin-top:8px"><b>可疑订单段</b></div>` +
        `<div class="ai-evidence">${{segments.map(s => `<button class="secondary" data-ai-start="${{escapeHtml(s.start_time)}}" data-ai-end="${{escapeHtml(s.end_time)}}">${{escapeHtml(s.segment_id || 'segment')}}</button>`).join('') || '<span>无</span>'}}</div>` +
        `<div style="margin-top:8px;color:#64748b">局限：${{escapeHtml((r.limitations || []).join('；'))}}</div>`;
      bodyEl.querySelectorAll('[data-ai-start]').forEach(btn => btn.addEventListener('click', () => timeAround(btn.dataset.aiStart, btn.dataset.aiEnd)));
    }} else {{
      const est = job.estimate || null;
      bodyEl.innerHTML = escapeHtml(job.message || '尚未分析。') +
        (est && !est.error ? `<div style="margin-top:6px;color:#64748b">预计：${{escapeHtml(est.model || '')}} · $${{Number(est.estimated_cost_usd || 0).toFixed(4)}} · 输入约${{escapeHtml(est.estimated_input_tokens || '')}} tokens · 输出约${{escapeHtml(est.estimated_output_tokens || '')}} tokens · 分块${{escapeHtml(est.chunk_count || '')}}</div>` : '') +
        (est && est.error ? `<div style="margin-top:6px;color:#991b1b">成本预估失败：${{escapeHtml(est.error)}}</div>` : '');
    }}
  }}
  async function load() {{
    const res = await fetch('/api/ai/status/' + encodeURIComponent(stem), {{cache:'no-store'}});
    render(await res.json());
  }}
  async function run() {{
    runBtn.disabled = true;
    const body = new URLSearchParams();
    body.set('stem', stem);
    const res = await fetch('/api/ai/analyze', {{method:'POST', body}});
    if (!res.ok) bodyEl.textContent = await res.text();
    setTimeout(load, 800);
    runBtn.disabled = false;
  }}
  runBtn.addEventListener('click', run);
  refreshBtn.addEventListener('click', load);
  load();
}})();
</script>
"""
    if "</header>" in html_text:
        return html_text.replace("</header>", "</header>\n" + panel, 1)
    return html_text.replace("</body>", panel + "\n</body>", 1)


def json_response(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, body: str, status: int = 200) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def update_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(updates)
        job["updated_at"] = now_text()


def append_log(job_id: str, text: str) -> None:
    if not text:
        return
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        logs = job.setdefault("logs", "")
        job["logs"] = (logs + text)[-80000:]
        job["updated_at"] = now_text()


def parse_preview_json(output: str) -> dict:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("inspect did not return JSON")
    return json.loads(output[start : end + 1])


def run_inspection(job_id: str, statement_path: Path) -> None:
    update_job(job_id, status="parsed_running", started_at=now_text(), message="正在解析报表产品和时间范围")
    cmd = [str(PYTHON), str(GENERATOR), str(statement_path), "--inspect", "--out-dir", str(OUT_DIR)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("TRADE_KLINE_PYDEPS", str(DEFAULT_PYDEPS))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
        output = proc.stdout or ""
        append_log(job_id, output)
        if proc.returncode != 0:
            update_job(job_id, status="failed", message="解析失败，查看日志", finished_at=now_text(), return_code=proc.returncode)
            return
        preview = parse_preview_json(output)
        update_job(
            job_id,
            status="parsed",
            message="已解析，请选择要生成的产品和时间段",
            preview=preview,
            return_code=proc.returncode,
        )
    except Exception as exc:
        append_log(job_id, f"\nERROR: {exc}\n")
        update_job(job_id, status="failed", message=str(exc), finished_at=now_text())


def generated_files_for(html_path: Path | None) -> list[dict]:
    if not html_path:
        return []
    name = html_path.name
    if not name.endswith("_trade_kline.html"):
        return []
    stem = name[: -len("_trade_kline.html")]
    files = []
    for path in sorted(OUT_DIR.glob(stem + "*")):
        if path.is_file():
            files.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "url": public_output_url(path),
                    "file_url": file_url(path),
                }
            )
    return files


def parse_html_path(output: str) -> Path | None:
    matches = re.findall(r"[A-Za-z]:\\[^\r\n]+?_trade_kline\.html", output)
    for match in reversed(matches):
        path = Path(match.strip())
        if path.exists():
            return path
    return None


def run_generation(job_id: str, statement_path: Path, symbols: list[str] | None = None, start: str = "", end: str = "", run_ai: bool = False) -> None:
    update_job(job_id, status="running", started_at=now_text(), message="正在解析并生成图表")
    cmd = [
        str(PYTHON),
        str(GENERATOR),
        str(statement_path),
        "--out-dir",
        str(OUT_DIR),
        "--terminal",
        str(TERMINAL),
    ]
    if symbols:
        cmd.extend(["--symbols", ",".join(symbols)])
    if start:
        cmd.extend(["--start", start])
    if end:
        cmd.extend(["--end", end])
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("TRADE_KLINE_PYDEPS", str(DEFAULT_PYDEPS))
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        output_parts: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            output_parts.append(line)
            append_log(job_id, line)
        code = proc.wait()
        output = "".join(output_parts)
        html_path = parse_html_path(output)
        if code == 0 and html_path:
            files = generated_files_for(html_path)
            stem = stem_from_chart_name(html_path.name)
            update_job(
                job_id,
                status="done",
                message="生成完成",
                finished_at=now_text(),
                stem=stem,
                html_path=str(html_path),
                html_url=public_output_url(html_path),
                html_file_url=file_url(html_path),
                files=files,
                return_code=code,
            )
            if run_ai:
                update_ai_job(stem, status="queued", message="已提交AI分析", elapsed_seconds=0)
                threading.Thread(target=run_ai_analysis, args=(stem,), daemon=True).start()
        else:
            update_job(
                job_id,
                status="failed",
                message="生成失败，查看日志",
                finished_at=now_text(),
                return_code=code,
                html_path=str(html_path) if html_path else "",
            )
    except Exception as exc:
        append_log(job_id, f"\nERROR: {exc}\n")
        update_job(job_id, status="failed", message=str(exc), finished_at=now_text())


def recent_charts(limit: int = 20) -> list[dict]:
    rows = []
    for path in OUT_DIR.glob("*_trade_kline.html"):
        if not path.is_file():
            continue
        rows.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "url": public_output_url(path),
                "file_url": file_url(path),
            }
        )
    rows.sort(key=lambda item: item["mtime"], reverse=True)
    return rows[:limit]


def recover_job(job_id: str) -> dict:
    uploads = sorted(UPLOAD_DIR.glob(f"{job_id}_*"))
    if not uploads:
        return {"id": job_id, "status": "missing", "message": "任务不存在"}
    statement = uploads[0]
    account_match = re.search(r"(?:Statement|ReportHistory)[_ -]?(\d+)", statement.name, re.I)
    candidates = []
    if account_match:
        account = account_match.group(1)
        candidates = sorted(
            OUT_DIR.glob(f"{account}_*_trade_kline.html"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if not candidates:
        upload_time = statement.stat().st_mtime
        candidates = sorted(
            [p for p in OUT_DIR.glob("*_trade_kline.html") if p.stat().st_mtime >= upload_time],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if candidates:
        html_path = candidates[0]
        return {
            "id": job_id,
            "status": "done",
            "message": "生成完成（服务重启后自动恢复）",
            "statement": str(statement),
            "html_path": str(html_path),
            "html_url": public_output_url(html_path),
            "html_file_url": file_url(html_path),
            "files": generated_files_for(html_path),
            "logs": "服务重启后从输出文件自动恢复任务状态；详细实时日志不再保留。\n",
        }
    return {
        "id": job_id,
        "status": "failed",
        "message": "任务状态已丢失，且未找到对应输出图表",
        "statement": str(statement),
        "logs": "服务重启后未找到对应输出图表，请重新上传生成。\n",
    }


BASE_CSS = """
body{margin:0;background:#f4f6f8;color:#172033;font-family:Arial,"Microsoft YaHei",sans-serif}
header{background:#111827;color:white;padding:16px 22px}
h1{margin:0;font-size:20px}
.meta{margin-top:6px;color:#cbd5e1;font-size:13px}
main{padding:18px 22px 28px}
.panel{background:white;border:1px solid #d9e2ec;border-radius:6px;padding:16px;margin-bottom:14px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
input[type=file]{border:1px solid #cbd5e1;padding:9px;background:#fff;border-radius:4px;min-width:360px}
button,.btn{border:1px solid #111827;background:#111827;color:white;border-radius:4px;padding:9px 13px;cursor:pointer;text-decoration:none;display:inline-block}
.btn.secondary{background:#fff;color:#111827;border-color:#cbd5e1}
.hint{color:#64748b;font-size:13px;margin-top:8px;line-height:1.5}
.status{font-weight:700}
.done{color:#16a34a}.failed{color:#dc2626}.running{color:#2563eb}.queued{color:#7c3aed}
pre{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:12px;border-radius:6px;max-height:360px;overflow:auto;font-size:12px}
table{width:100%;border-collapse:collapse;background:white;font-size:13px}
th,td{border:1px solid #e5e7eb;padding:7px 9px;text-align:left;white-space:nowrap}
th{background:#eef2f7}
.chartFrame{width:100%;height:760px;border:1px solid #cbd5e1;background:white}
"""


def page_shell(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<header>
<h1>买卖点 K 线图生成工具</h1>
<div class="meta">上传交易报表后自动解析、核对时间口径、读取/复用 MT5 M1 缓存并生成图表。只读读取行情，不修改 MT5/Manager 数据。</div>
</header>
<main>{content}</main>
</body>
</html>"""


def index_page() -> str:
    rows = recent_charts()
    recent = "".join(
        f"<tr><td><a href='{item['url']}' target='_blank'>{html.escape(item['name'])}</a></td>"
        f"<td>{html.escape(item['mtime'])}</td><td>{item['size']:,}</td>"
        f"<td><a href='{item['url']}' target='_blank'>网页打开</a> · <a href='{item['file_url']}' target='_blank'>file 打开</a></td></tr>"
        for item in rows
    )
    if not recent:
        recent = "<tr><td colspan='4'>暂无生成记录</td></tr>"
    return page_shell(
        "买卖点 K 线图生成工具",
        f"""
<section class="panel">
  <form action="/upload" method="post" enctype="multipart/form-data">
    <div class="row">
      <input type="file" name="statement" accept=".htm,.html" required>
      <button type="submit">上传并生成</button>
    </div>
    <div class="hint">支持 MT5 statement / ReportHistory 的 .htm 或 .html 文件。输出和缓存保存在项目目录 <code>{html.escape(str(OUT_DIR))}</code>。</div>
  </form>
</section>
<section class="panel">
  <h2 style="font-size:16px;margin:0 0 10px">最近生成</h2>
  <table><thead><tr><th>图表</th><th>生成时间</th><th>大小</th><th>操作</th></tr></thead><tbody>{recent}</tbody></table>
</section>
""",
    )


def job_page(job_id: str) -> str:
    return page_shell(
        "生成任务",
        f"""
<section class="panel">
  <div class="row">
    <a class="btn secondary" href="/">返回上传</a>
    <span>任务 ID: <code>{html.escape(job_id)}</code></span>
    <span class="status queued" id="status">读取中</span>
  </div>
  <div class="hint" id="message"></div>
  <div class="row" id="actions" style="margin-top:10px"></div>
</section>
<section class="panel" id="previewPanel" style="display:none">
  <iframe class="chartFrame" id="chartFrame"></iframe>
</section>
<section class="panel">
  <h2 style="font-size:16px;margin:0 0 10px">生成日志</h2>
  <pre id="logs"></pre>
</section>
<section class="panel" id="filesPanel" style="display:none">
  <h2 style="font-size:16px;margin:0 0 10px">输出文件</h2>
  <table><thead><tr><th>文件</th><th>时间</th><th>大小</th><th>链接</th></tr></thead><tbody id="files"></tbody></table>
</section>
<script>
const jobId = {json.dumps(job_id)};
async function refresh(){{
  const res = await fetch('/api/jobs/' + jobId, {{cache:'no-store'}});
  const job = await res.json();
  const status = document.getElementById('status');
  status.textContent = job.status || 'unknown';
  status.className = 'status ' + (job.status || '');
  document.getElementById('message').textContent = job.message || '';
  document.getElementById('logs').textContent = job.logs || '';
  if (job.html_url) {{
    document.getElementById('actions').innerHTML =
      `<a class="btn" target="_blank" href="${{job.html_url}}">打开图表</a>` +
      `<a class="btn secondary" target="_blank" href="${{job.html_file_url}}">file 打开</a>`;
    document.getElementById('previewPanel').style.display = 'block';
    const frame = document.getElementById('chartFrame');
    if (!frame.src) frame.src = job.html_url;
  }}
  if (job.files && job.files.length) {{
    document.getElementById('filesPanel').style.display = 'block';
    document.getElementById('files').innerHTML = job.files.map(f =>
      `<tr><td>${{f.name}}</td><td>${{f.mtime}}</td><td>${{f.size.toLocaleString()}}</td>` +
      `<td><a target="_blank" href="${{f.url}}">网页</a> · <a target="_blank" href="${{f.file_url}}">file</a></td></tr>`
    ).join('');
  }}
  if (!['done','failed'].includes(job.status)) setTimeout(refresh, 1200);
}}
refresh();
</script>
""",
    )

def job_page(job_id: str) -> str:
    content = """
<section class="panel">
  <div class="row">
    <a class="btn secondary" href="/">返回上传</a>
    <span>任务 ID: <code>__JOB_ID_HTML__</code></span>
    <span class="status queued" id="status">读取中</span>
  </div>
  <div class="hint" id="message"></div>
  <div class="row" id="actions" style="margin-top:10px"></div>
</section>
<section class="panel" id="selectPanel" style="display:none">
  <h2 style="font-size:16px;margin:0 0 10px">选择生成范围</h2>
  <form id="generateForm">
    <div class="row" style="margin-bottom:10px">
      <label>开始 <input id="startInput" name="start" type="text" style="width:170px" placeholder="YYYY-MM-DD HH:MM:SS"></label>
      <label>结束 <input id="endInput" name="end" type="text" style="width:170px" placeholder="YYYY-MM-DD HH:MM:SS"></label>
      <label><input id="runAiInput" name="run_ai" type="checkbox"> 同时生成AI分析</label>
      <button type="submit">生成选中范围</button>
    </div>
    <div class="row" style="margin-bottom:10px">
      <span class="hint">快捷范围</span>
      <button type="button" class="btn secondary quickRange" data-range="7d">7天</button>
      <button type="button" class="btn secondary quickRange" data-range="1m">1个月</button>
      <button type="button" class="btn secondary quickRange" data-range="3m">3个月</button>
      <button type="button" class="btn secondary quickRange" data-range="6m">半年</button>
      <button type="button" class="btn secondary quickRange" data-range="12m">1年</button>
      <button type="button" class="btn secondary quickRange" data-range="all">全部</button>
    </div>
    <div class="hint" id="previewMeta"></div>
    <table style="margin-top:10px"><thead><tr><th><input id="selectAllSymbols" type="checkbox" checked></th><th>产品</th><th>订单数</th><th>时间范围</th><th>Profit</th></tr></thead><tbody id="symbolRows"></tbody></table>
  </form>
</section>
<section class="panel" id="previewPanel" style="display:none">
  <iframe class="chartFrame" id="chartFrame"></iframe>
</section>
<section class="panel">
  <h2 style="font-size:16px;margin:0 0 10px">任务日志</h2>
  <pre id="logs"></pre>
</section>
<section class="panel" id="filesPanel" style="display:none">
  <h2 style="font-size:16px;margin:0 0 10px">输出文件</h2>
  <table><thead><tr><th>文件</th><th>时间</th><th>大小</th><th>链接</th></tr></thead><tbody id="files"></tbody></table>
</section>
<script>
const jobId = __JOB_ID_JSON__;
let lastPreviewKey = '';
let currentPreview = null;
function parseDateTime(text) {
  const value = String(text || '').trim();
  if (!value) return null;
  const normalized = value.length === 16 ? value + ':00' : value;
  const d = new Date(normalized.replace(' ', 'T'));
  return Number.isFinite(d.getTime()) ? d : null;
}
function formatDateTime(date) {
  const p = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
}
function applyQuickRange(range) {
  if (!currentPreview) return;
  const startInput = document.getElementById('startInput');
  const endInput = document.getElementById('endInput');
  if (range === 'all') {
    startInput.value = currentPreview.start || '';
    endInput.value = currentPreview.end || '';
    return;
  }
  const fullStart = parseDateTime(currentPreview.start);
  const fullEnd = parseDateTime(currentPreview.end);
  const end = parseDateTime(endInput.value) || fullEnd;
  if (!end) return;
  const start = new Date(end.getTime());
  if (range === '7d') start.setDate(start.getDate() - 7);
  else if (range === '1m') start.setMonth(start.getMonth() - 1);
  else if (range === '3m') start.setMonth(start.getMonth() - 3);
  else if (range === '6m') start.setMonth(start.getMonth() - 6);
  else if (range === '12m') start.setFullYear(start.getFullYear() - 1);
  if (fullStart && start < fullStart) start.setTime(fullStart.getTime());
  startInput.value = formatDateTime(start);
  endInput.value = formatDateTime(end);
}
function renderSelection(job) {
  const preview = job.preview;
  if (!preview || job.status !== 'parsed') return;
  const key = JSON.stringify(preview);
  document.getElementById('selectPanel').style.display = 'block';
  currentPreview = preview;
  if (key === lastPreviewKey) return;
  lastPreviewKey = key;
  document.getElementById('startInput').value = preview.start || '';
  document.getElementById('endInput').value = preview.end || '';
  document.getElementById('previewMeta').textContent =
    `账户 ${preview.account}，共 ${preview.trade_count} 笔，完整范围 ${preview.start} 到 ${preview.end}`;
  document.getElementById('symbolRows').innerHTML = (preview.symbols || []).map(s =>
    `<tr><td><input class="symbolCheck" type="checkbox" value="${s.symbol}" checked></td>` +
    `<td>${s.symbol}</td><td>${s.trades}</td><td>${s.open_start} - ${s.close_end}</td>` +
    `<td>${Number(s.profit || 0).toFixed(2)}</td></tr>`
  ).join('');
}
document.addEventListener('change', ev => {
  if (ev.target && ev.target.id === 'selectAllSymbols') {
    document.querySelectorAll('.symbolCheck').forEach(cb => cb.checked = ev.target.checked);
  }
});
document.addEventListener('click', ev => {
  const btn = ev.target && ev.target.closest ? ev.target.closest('.quickRange') : null;
  if (btn) applyQuickRange(btn.dataset.range);
});
document.addEventListener('submit', async ev => {
  if (ev.target && ev.target.id === 'generateForm') {
    ev.preventDefault();
    const symbols = Array.from(document.querySelectorAll('.symbolCheck:checked')).map(cb => cb.value);
    if (!symbols.length) { alert('请至少选择一个产品'); return; }
    const body = new URLSearchParams();
    body.set('job_id', jobId);
    symbols.forEach(s => body.append('symbols', s));
    body.set('start', document.getElementById('startInput').value.trim());
    body.set('end', document.getElementById('endInput').value.trim());
    if (document.getElementById('runAiInput').checked) body.set('run_ai', '1');
    const res = await fetch('/generate', {method:'POST', body});
    if (!res.ok) {
      const txt = await res.text();
      alert('启动生成失败：' + txt);
      return;
    }
    document.getElementById('selectPanel').style.display = 'none';
    setTimeout(refresh, 300);
  }
});
async function refresh(){
  const res = await fetch('/api/jobs/' + jobId, {cache:'no-store'});
  const job = await res.json();
  const status = document.getElementById('status');
  status.textContent = job.status || 'unknown';
  status.className = 'status ' + (job.status || '');
  document.getElementById('message').textContent = job.message || '';
  document.getElementById('logs').textContent = job.logs || '';
  renderSelection(job);
  if (job.html_url) {
    document.getElementById('actions').innerHTML =
      `<a class="btn" target="_blank" href="${job.html_url}">打开图表</a>` +
      `<a class="btn secondary" target="_blank" href="${job.html_file_url}">file 打开</a>`;
    document.getElementById('previewPanel').style.display = 'block';
    const frame = document.getElementById('chartFrame');
    if (!frame.src) frame.src = job.html_url;
  }
  if (job.files && job.files.length) {
    document.getElementById('filesPanel').style.display = 'block';
    document.getElementById('files').innerHTML = job.files.map(f =>
      `<tr><td>${f.name}</td><td>${f.mtime}</td><td>${f.size.toLocaleString()}</td>` +
      `<td><a target="_blank" href="${f.url}">网页</a> · <a target="_blank" href="${f.file_url}">file</a></td></tr>`
    ).join('');
  }
  if (!['done','failed','parsed'].includes(job.status)) setTimeout(refresh, 1200);
}
refresh();
</script>
"""
    content = content.replace("__JOB_ID_HTML__", html.escape(job_id)).replace("__JOB_ID_JSON__", json.dumps(job_id))
    return page_shell("生成任务", content)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[{now_text()}] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            html_response(self, index_page())
            return
        if path.startswith("/job/"):
            job_id = path.rsplit("/", 1)[-1]
            html_response(self, job_page(job_id))
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id) or recover_job(job_id))
            json_response(self, job, 200 if job.get("status") != "missing" else 404)
            return
        if path == "/api/recent":
            json_response(self, {"charts": recent_charts()})
            return
        if path.startswith("/api/ai/status/"):
            stem = Path(unquote(path[len("/api/ai/status/") :])).name
            json_response(self, ai_status(stem))
            return
        if path.startswith("/api/ai/result/"):
            stem = Path(unquote(path[len("/api/ai/result/") :])).name
            result = read_ai_result(stem)
            if not result:
                json_response(self, {"error": "AI result not found"}, 404)
                return
            json_response(self, {"ok": True, "result": result})
            return
        if path.startswith("/api/ai/chat/"):
            stem = Path(unquote(path[len("/api/ai/chat/") :])).name
            json_response(self, public_ai_chat(stem))
            return
        if path.startswith("/output/"):
            self.serve_output(unquote(path[len("/output/") :]))
            return
        html_response(self, page_shell("404", "<section class='panel'>页面不存在</section>"), 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/generate":
            self.handle_generate()
            return
        if path == "/api/ai/analyze":
            self.handle_ai_analyze()
            return
        if path == "/api/ai/chat":
            self.handle_ai_chat()
            return
        if path == "/api/ai/chat/clear":
            self.handle_ai_chat_clear()
            return
        if path != "/upload":
            json_response(self, {"error": "not found"}, 404)
            return
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        item = form["statement"] if "statement" in form else None
        if item is None or not getattr(item, "filename", ""):
            html_response(self, page_shell("上传失败", "<section class='panel failed'>没有收到文件</section>"), 400)
            return
        filename = safe_filename(item.filename)
        if not filename.lower().endswith((".htm", ".html")):
            html_response(self, page_shell("上传失败", "<section class='panel failed'>只支持 .htm / .html</section>"), 400)
            return
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        dest = UPLOAD_DIR / f"{job_id}_{filename}"
        with dest.open("wb") as out:
            shutil.copyfileobj(item.file, out)
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "message": "已上传，等待生成",
                "created_at": now_text(),
                "updated_at": now_text(),
                "statement": str(dest),
                "logs": "",
            }
        thread = threading.Thread(target=run_inspection, args=(job_id, dest), daemon=True)
        thread.start()
        self.send_response(303)
        self.send_header("Location", f"/job/{job_id}")
        self.end_headers()

    def handle_generate(self) -> None:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        job_id = str(form.getfirst("job_id", "")).strip()
        symbols = [str(item).strip().upper() for item in form.getlist("symbols") if str(item).strip()]
        start = str(form.getfirst("start", "")).strip()
        end = str(form.getfirst("end", "")).strip()
        run_ai = str(form.getfirst("run_ai", "")).strip().lower() in {"1", "true", "on", "yes"}
        if not job_id:
            json_response(self, {"error": "missing job_id"}, 400)
            return
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                job = recover_job(job_id)
                JOBS[job_id] = job
            statement = Path(str(job.get("statement", "")))
            status = job.get("status")
        if status not in {"parsed", "failed", "done"}:
            json_response(self, {"error": f"job is not ready for generation: {status}"}, 400)
            return
        if not statement.exists():
            json_response(self, {"error": "statement file not found"}, 404)
            return
        if not symbols:
            json_response(self, {"error": "no symbols selected"}, 400)
            return
        update_job(job_id, status="queued", message="已提交生成任务", selected_symbols=symbols, selected_start=start, selected_end=end, run_ai=run_ai, logs="")
        thread = threading.Thread(target=run_generation, args=(job_id, statement, symbols, start, end, run_ai), daemon=True)
        thread.start()
        json_response(self, {"ok": True, "job_id": job_id})

    def handle_ai_analyze(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        if self.headers.get("Content-Type", "").startswith("application/json"):
            payload = json.loads(raw or "{}")
            stem = str(payload.get("stem", "")).strip()
            provider = str(payload.get("provider", "")).strip()
            model = str(payload.get("model", "")).strip()
        else:
            data = parse_qs(raw)
            stem = str((data.get("stem") or [""])[0]).strip()
            provider = str((data.get("provider") or [""])[0]).strip()
            model = str((data.get("model") or [""])[0]).strip()
        stem = Path(stem).name
        if not stem:
            json_response(self, {"error": "missing stem"}, 400)
            return
        trades = ai_trades_path(stem)
        if not trades.exists():
            json_response(self, {"error": f"trades csv not found: {trades}"}, 404)
            return
        current = ai_status(stem)
        if current.get("status") in {"queued", "running"}:
            json_response(self, {"ok": True, "status": current.get("status"), "stem": stem})
            return
        update_ai_job(stem, status="queued", message="已提交AI分析", elapsed_seconds=0)
        threading.Thread(target=run_ai_analysis, args=(stem, provider, model), daemon=True).start()
        json_response(self, {"ok": True, "status": "queued", "stem": stem})

    def handle_ai_chat(self) -> None:
        try:
            payload = parse_request_payload(self)
        except Exception as exc:
            json_response(self, {"error": f"invalid request: {exc}"}, 400)
            return
        stem = Path(str(payload.get("stem", "")).strip()).name
        question = str(payload.get("question", "")).strip()
        provider = str(payload.get("provider", "")).strip()
        model = str(payload.get("model", "")).strip()
        if not stem:
            json_response(self, {"error": "missing stem"}, 400)
            return
        if not question:
            json_response(self, {"error": "missing question"}, 400)
            return
        if len(question) > 2000:
            json_response(self, {"error": "question is too long; please keep it within 2000 characters"}, 400)
            return
        if not read_ai_result(stem):
            json_response(self, {"error": "请先完成一次AI分析，再进行追问"}, 400)
            return
        started = time.time()
        try:
            result = run_ai_followup(stem, question, provider, model)
            result["elapsed_seconds"] = round(time.time() - started, 2)
            json_response(self, result)
        except Exception as exc:
            json_response(self, {"error": str(exc), "stem": stem}, 500)

    def handle_ai_chat_clear(self) -> None:
        try:
            payload = parse_request_payload(self)
        except Exception as exc:
            json_response(self, {"error": f"invalid request: {exc}"}, 400)
            return
        stem = Path(str(payload.get("stem", "")).strip()).name
        if not stem:
            json_response(self, {"error": "missing stem"}, 400)
            return
        with AI_CHAT_LOCK:
            write_ai_chat(stem, empty_ai_chat(stem))
        json_response(self, {"ok": True, "chat": public_ai_chat(stem)})

    def serve_output(self, filename: str) -> None:
        name = Path(filename).name
        path = OUT_DIR / name
        if not path.exists() or not path.is_file():
            self.send_error(404, "file not found")
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        if ctype == "text/html" and name.endswith("_trade_kline.html"):
            text = data.decode("utf-8", errors="replace")
            data = inject_ai_panel(text, name).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not GENERATOR.exists():
        raise SystemExit(f"missing generator: {GENERATOR}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"trade kline web running: http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
