from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from kdesk.application.bonus_arbitrage import BonusArbitrageService
from kdesk.application.bonus_arbitrage_scan import BonusArbitrageScanService, BonusScanCancelled
from kdesk.application.hedge_detection import CrossAccountHedgeService
from kdesk.application.position_risk import PositionRiskService
from kdesk.application.position_risk_scan import PositionRiskScanCancelled, PositionRiskScanService
from kdesk.application.rebate_churning_scan import RebateChurningScanService, ScanCancelled
from kdesk.infrastructure.bonus_arbitrage import LegacyBonusArbitrageRepository
from kdesk.infrastructure.bonus_arbitrage_scan import LegacyBonusArbitrageScanRepository
from kdesk.infrastructure.database import Database
from kdesk.infrastructure.legacy_bridge import LegacyBridge
from kdesk.infrastructure.position_risk import LegacyPositionRiskRepository
from kdesk.infrastructure.position_risk_scan import LegacyPositionRiskScanRepository
from kdesk.infrastructure.rebate_churning import LegacyRebateRepository
from kdesk.settings import Settings
from kdesk.settings import settings as default_settings

PUSH_FAILURE_STAGES = {
    "aggregate": ("候选聚合", "该服务器未能进入本轮候选筛选"),
    "load_rows": ("初筛订单读取", "该服务器的候选账号未能完成结构初筛"),
    "screen": ("结构初筛", "该账号未能进入深检排序"),
    "deep": ("深度检测", "该账号没有生成深检结果"),
    "result": ("结果整理", "本次失败明细可能不完整"),
}


def normalize_push_failure(item: dict) -> dict:
    stage = str(item.get("stage") or "result")
    stage_label, impact = PUSH_FAILURE_STAGES.get(stage, ("检测过程", "该项没有生成检测结果"))
    detail = str(item.get("error") or "").strip()
    lower_detail = detail.lower()
    attempts = max(int(item.get("attempts") or 1), 1)
    if "账号全历史没有可检测订单" in detail:
        reason = "当前服务器归属下没有可用于深检的已平仓订单"
    elif "lost connection" in lower_detail or "timed out" in lower_detail or "查询超时" in detail:
        reason = "数据库查询超时或连接中断"
        if attempts > 1:
            reason += "，重试后仍未恢复"
    elif "access denied" in lower_detail:
        reason = "数据库账号没有所需的只读权限"
    elif detail:
        reason = detail
    else:
        reason = "未记录具体异常原因"
    return {
        "stage": stage,
        "stageLabel": stage_label,
        "source": str(item.get("source") or ""),
        "platform": str(item.get("platform") or ""),
        "server": str(item.get("server") or ""),
        "account": str(item.get("login") or item.get("account") or ""),
        "reason": reason,
        "detail": detail,
        "impact": impact,
        "attempts": attempts,
    }


def load_push_failures(path: Path, expected_total: int = 0) -> tuple[list[dict], dict[str, int]]:
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("失败明细不是列表")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raw = [{"stage": "result", "error": f"失败明细文件无法读取：{exc}"}]
    elif expected_total > 0:
        raw = [{"stage": "result", "error": "扫描报告记录了失败，但失败明细文件不存在"}]
    else:
        raw = []
    failures = [normalize_push_failure(item) for item in raw if isinstance(item, dict)]
    summary: dict[str, int] = {}
    for item in failures:
        label = item["stageLabel"]
        summary[label] = summary.get(label, 0) + 1
    return failures, summary


class Worker:
    HEARTBEAT_INTERVAL_SECONDS = 5
    STALE_JOB_GRACE_SECONDS = 180

    QUEUE_KINDS = {
        "interactive": ("kline_inspect", "kline_generate", "kline_from_database", "toxic_check"),
        "discovery": ("push_discovery", "rebate_churning_scan", "bonus_arbitrage_scan", "position_risk_scan"),
    }

    def __init__(self, settings: Settings, *, queue: str = "all"):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.legacy = LegacyBridge(settings)
        self.queue = queue
        self.kinds = self.QUEUE_KINDS.get(queue)
        self.running = True

    def _generator(self) -> Path:
        return self.settings.legacy_root / "tools" / "trade_kline_tool" / "generate_trade_kline_from_statement.py"

    def _run_process(self, job_id: str, command: list[str], *, timeout: int = 3600) -> str:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["TRADE_KLINE_OUT_DIR"] = str(self.settings.artifact_dir)
        env["TRADE_KLINE_TOOL_DIR"] = str(self.settings.legacy_root / "tools" / "trade_kline_tool")
        env.setdefault("TRADE_KLINE_PYDEPS", r"D:\risk\pydeps")
        process = subprocess.Popen(
            command,
            cwd=str(self.settings.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        output: list[str] = []
        started = time.monotonic()
        assert process.stdout is not None
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            try:
                for line in process.stdout:
                    output_queue.put(line)
            finally:
                output_queue.put(None)

        reader = threading.Thread(target=read_output, name=f"job-output-{job_id}", daemon=True)
        reader.start()
        output_finished = False
        while True:
            try:
                line = output_queue.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                output_finished = True
                line = ""
            if line:
                output.append(line)
                event_message = line.rstrip()
                progress = None
                if event_message.startswith("PROGRESS "):
                    try:
                        payload = json.loads(event_message[len("PROGRESS ") :])
                        progress = min(max(int(payload.get("percent", 0)), 0), 99)
                        event_message = str(payload.get("message") or payload.get("stage") or event_message)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        progress = None
                self.database.update_job(job_id, progress=progress, event_message=event_message)
            if process.poll() is not None and output_finished:
                break
            current = self.database.get_job(job_id)
            if current and current.get("cancel_requested"):
                process.kill()
                process.wait(timeout=5)
                reader.join(timeout=1)
                self.database.update_job(job_id, status="cancelled", event_message="运行中的任务已取消")
                raise RuntimeError("任务已取消")
            if time.monotonic() - started > timeout:
                process.kill()
                process.wait(timeout=5)
                reader.join(timeout=1)
                raise TimeoutError(f"任务运行超过 {timeout} 秒")
        if process.returncode != 0:
            raise RuntimeError("".join(output)[-8000:] or f"process exited with {process.returncode}")
        return "".join(output)

    @staticmethod
    def _parse_json_output(output: str) -> dict:
        start = output.find("{")
        end = output.rfind("}")
        if start < 0 or end < start:
            raise ValueError("生成器未返回 JSON")
        return json.loads(output[start : end + 1])

    @staticmethod
    def _parse_kline_result(output: str) -> dict:
        for line in reversed(output.splitlines()):
            if line.startswith("KLINE_RESULT "):
                return json.loads(line[len("KLINE_RESULT ") :])
        return {}

    def _kline_inspect(self, job: dict) -> dict:
        statement = Path(job["payload"]["statement"])
        output = self._run_process(
            job["id"],
            [sys.executable, str(self._generator()), str(statement), "--inspect", "--out-dir", str(self.settings.artifact_dir)],
            timeout=180,
        )
        return {"preview": self._parse_json_output(output), "statement": str(statement)}

    def _kline_generate(self, job: dict) -> dict:
        payload = job["payload"]
        command = [sys.executable, str(self._generator()), payload["statement"], "--out-dir", str(self.settings.artifact_dir)]
        symbols = [str(item) for item in payload.get("symbols") or [] if str(item).strip()]
        if symbols:
            command.extend(["--symbols", ",".join(symbols)])
        if payload.get("start"):
            command.extend(["--start", payload["start"]])
        if payload.get("end"):
            command.extend(["--end", payload["end"]])
        output = self._run_process(job["id"], command)
        generation = self._parse_kline_result(output)
        matches = re.findall(r"[A-Za-z]:\\[^\r\n]+?_trade_kline\.html", output)
        html_path = matches[-1].strip() if matches else ""
        if not html_path or not generation.get("symbols"):
            self.database.update_job(job["id"], result=generation)
            details = generation.get("failures") or []
            reason = details[0].get("reason") if details else generation.get("message")
            raise RuntimeError(reason or "全部品种报价校验失败")
        return {
            "html_path": html_path,
            "html_url": f"/output/{Path(html_path).name}" if html_path else "",
            "output": output[-4000:],
            **generation,
        }

    def _kline_from_database(self, job: dict) -> dict:
        payload = job["payload"]
        legacy = self.legacy.module()
        filters = {key: payload.get(key, "") for key in ("platform", "server", "symbol", "start", "end")}
        self._run_legacy_monitored(
            job,
            lambda: legacy.run_db_kline_job(job["id"], payload["account"], filters),
            lambda: legacy.get_kline_job(job["id"]),
        )
        result = legacy.get_kline_job(job["id"])
        if result.get("status") != "done":
            self.database.update_job(job["id"], result=result)
            raise RuntimeError(result.get("message") or "K线生成失败")
        return result

    def _toxic_check(self, job: dict) -> dict:
        payload = job["payload"]
        legacy = self.legacy.module()
        mode = str(payload.get("mode") or "selected")
        type_ids = [str(item) for item in payload.get("types") or []]
        filters = {key: str(payload.get(key, "")) for key in ("platform", "server", "symbol", "start", "end")}
        self._run_legacy_monitored(
            job,
            lambda: legacy.run_toxic_job(job["id"], payload["account"], mode, type_ids, filters),
            lambda: legacy.get_toxic_job(job["id"]),
        )
        result = legacy.get_toxic_job(job["id"])
        if result.get("status") != "done":
            raise RuntimeError(result.get("message") or "Toxic 检测失败")
        selected = set(type_ids) if mode == "selected" else {str(item.get("id")) for item in getattr(legacy, "TOXIC_CHECK_TYPES", [])}
        if "bonus_arbitrage" in selected:
            self.database.update_job(job["id"], progress=94, event_message="正在复核历史赠金、提款与关联账户资金周期")
            try:
                bonus_result = BonusArbitrageService(LegacyBonusArbitrageRepository(self.legacy)).analyze(
                    str(payload["account"]), filters, stage="initial" if mode == "screen" else "deep",
                )
            except Exception as exc:
                bonus_result = {
                    "type": "bonus_arbitrage", "label": "赠金套利", "score": 0.0,
                    "level": "证据不可用", "stage": "initial" if mode == "screen" else "deep",
                    "confidence": 0, "summary": "历史赠金资金周期读取失败",
                    "metrics": [], "triggeredRules": [], "evidenceOrders": [], "evidence": {"cycles": []},
                    "limitations": [str(exc)], "requiresTick": False, "analysis": [],
                }
            payload_result = result.get("result") if isinstance(result.get("result"), dict) else {}
            rows = payload_result.get("results") if isinstance(payload_result.get("results"), list) else []
            rows = [row for row in rows if row.get("type") != "bonus_arbitrage"]
            rows.append(bonus_result)
            rows.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("label") or "")))
            payload_result["results"] = rows
            payload_result["bonusArbitrage"] = bonus_result.get("evidence") or {}
            result["result"] = payload_result
        position_types = sorted(selected & {"weekend_gap_trading", "open_betting"})
        if position_types:
            self.database.update_job(job["id"], progress=96, event_message="正在按历史权益、杠杆和持仓敞口复核特殊时点")
            try:
                position_analysis = PositionRiskService(LegacyPositionRiskRepository(self.legacy)).analyze(
                    str(payload["account"]), filters,
                    stage="initial" if mode == "screen" else "deep",
                    type_ids=position_types,
                )
                position_results = position_analysis.get("results") or []
            except Exception as exc:
                position_analysis = {"events": []}
                position_results = [
                    {
                        "type": type_id,
                        "label": "周末跳空交易" if type_id == "weekend_gap_trading" else "赌开盘",
                        "score": 0.0,
                        "level": "证据不可用",
                        "stage": "initial" if mode == "screen" else "deep",
                        "confidence": 0,
                        "summary": "历史权益、杠杆或持仓敞口读取失败",
                        "metrics": [],
                        "triggeredRules": [],
                        "evidenceOrders": [],
                        "limitations": [str(exc)],
                        "requiresTick": False,
                        "analysis": [],
                        "evidence": {"events": []},
                    }
                    for type_id in position_types
                ]
            payload_result = result.get("result") if isinstance(result.get("result"), dict) else {}
            rows = payload_result.get("results") if isinstance(payload_result.get("results"), list) else []
            rows = [row for row in rows if row.get("type") not in set(position_types)]
            rows.extend(position_results)
            rows.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("label") or "")))
            payload_result["results"] = rows
            payload_result["positionRisk"] = {
                "events": position_analysis.get("events") or [],
                "source": position_analysis.get("source") or {},
            }
            result["result"] = payload_result
        if "internal_lock_arbitrage" in selected:
            self.database.update_job(job["id"], progress=97, event_message="正在查询全平台反向同步开平仓订单")
            try:
                hedge_analysis = CrossAccountHedgeService(LegacyPositionRiskRepository(self.legacy)).analyze(
                    str(payload["account"]), filters,
                    stage="initial" if mode == "screen" else "deep",
                )
                hedge_result = hedge_analysis["result"]
            except Exception as exc:
                hedge_analysis = {"evidence": {}}
                hedge_result = {
                    "type": "internal_lock_arbitrage", "label": "平台内多账户对锁", "score": 0.0,
                    "level": "证据不可用", "stage": "initial" if mode == "screen" else "deep",
                    "confidence": 0, "summary": "跨账户反向同步开平仓查询失败",
                    "metrics": [], "triggeredRules": [], "evidenceOrders": [],
                    "limitations": [str(exc)], "requiresTick": False, "analysis": [],
                    "evidence": {"hedgeQuery": {}},
                }
            payload_result = result.get("result") if isinstance(result.get("result"), dict) else {}
            rows = payload_result.get("results") if isinstance(payload_result.get("results"), list) else []
            rows = [row for row in rows if row.get("type") != "internal_lock_arbitrage"]
            rows.append(hedge_result)
            rows.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("label") or "")))
            payload_result["results"] = rows
            payload_result["internalLock"] = hedge_analysis.get("evidence") or {}
            result["result"] = payload_result
        return result

    def _run_legacy_monitored(self, job: dict, target, snapshot) -> None:
        failures: list[BaseException] = []

        def run() -> None:
            try:
                target()
            except BaseException as exc:  # Propagate worker-thread failures to the job runner.
                failures.append(exc)

        thread = threading.Thread(target=run, name=f"legacy-job-{job['id']}", daemon=True)
        thread.start()
        last_update: tuple[int, str, str] | None = None
        while thread.is_alive():
            current = snapshot() or {}
            progress = min(max(int(current.get("percent") or 5), 5), 99)
            message = str(current.get("message") or "任务执行中")
            signature = (progress, message, str(current.get("status") or "running"))
            if signature != last_update:
                self.database.update_job(job["id"], progress=progress, event_message=message)
                last_update = signature
            thread.join(timeout=0.4)
        thread.join()
        if failures:
            raise failures[0]
        latest = self.database.get_job(job["id"])
        if latest and latest.get("cancel_requested"):
            self.database.update_job(job["id"], status="cancelled", event_message="任务已取消")
            raise RuntimeError("任务已取消")

    def _push_discovery(self, job: dict) -> dict:
        payload = job["payload"]
        output_root = (self.settings.runtime_dir / "push_discovery").resolve()
        script = self.settings.legacy_root / "scripts" / "run_platform_push_discovery.py"
        command = [
            sys.executable,
            str(script),
            "--days", str(payload["days"]),
            "--max-orders", str(payload["maxOrders"]),
            "--min-max-lot", str(payload.get("minMaxLot", 0.01)),
            "--max-deposit", str(payload.get("maxDeposit", 2000)),
            "--max-active-ratio", str(payload.get("maxActiveRatio", 30)),
            "--small-order-priority", str(payload["smallOrderPriority"]),
            "--deep-limit", str(payload["deepLimit"]),
            "--workers", str(payload["workers"]),
            "--output-root", str(output_root),
        ]
        boolean_options = (
            ("requirePeriodProfit", "require-period-profit"),
            ("limitOrders", "limit-orders"),
            ("requireMaxLot", "require-max-lot"),
            ("requireTotalProfit", "require-total-profit"),
            ("limitDeposit", "limit-deposit"),
            ("limitActiveRatio", "limit-active-ratio"),
            ("excludeHandled", "exclude-handled"),
        )
        for payload_key, option_name in boolean_options:
            command.append(f"--{option_name}" if payload.get(payload_key, True) else f"--no-{option_name}")
        output = self._run_process(job["id"], command, timeout=7200)
        matches = re.findall(r"^RESULT\s+(.+?summary\.json)\s*$", output, flags=re.MULTILINE)
        if not matches:
            raise RuntimeError("全平台扫描未返回结果文件")
        summary_path = Path(matches[-1].strip()).resolve()
        try:
            summary_path.relative_to(output_root)
        except ValueError as exc:
            raise RuntimeError("扫描结果路径不在开发运行目录") from exc
        if not summary_path.is_file():
            raise RuntimeError("扫描结果文件不存在")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        deep_path = summary_path.parent / "deep_results.json"
        deep_results = json.loads(deep_path.read_text(encoding="utf-8")) if deep_path.is_file() else []
        failures, failure_summary = load_push_failures(
            summary_path.parent / "failures.json",
            int(summary.get("failures") or 0),
        )
        results = []
        for item in deep_results[:200]:
            suspected = item.get("suspectedPushIntervals") or {}
            economic = item.get("economicEvidence") or {}
            if economic and not economic.get("qualified"):
                continue
            results.append({
                "deepRank": int(item.get("deepRank") or 0),
                "platform": str(item.get("platform") or ""),
                "server": str(item.get("server") or ""),
                "account": str(item.get("login") or ""),
                "orders": int(item.get("exactOrders") or item.get("closedOrders") or 0),
                "maxLot": float(item.get("maxLot") or 0),
                "deepOrders": int(item.get("deepOrders") or item.get("exactOrders") or 0),
                "deepAnalysisOrders": int(item.get("deepAnalysisOrders") or item.get("analysisOrders") or 0),
                "deepScope": str(item.get("deepScope") or "window"),
                "periodNetRaw": float(item.get("periodNetRaw") or 0),
                "periodNet": float(item.get("periodNet") or 0),
                "totalNet": float(item.get("totalNet") or 0),
                "depositTotal": float(item.get("depositTotal") or 0),
                "activeDays": int(item.get("activeDays") or 0),
                "registrationDays": int(item.get("registrationDays") or 0),
                "activeRatio": float(item.get("activeRatio") or 0),
                "currency": str(item.get("currency") or ""),
                "suspectedIntervalCount": int(suspected.get("intervalCount") or 0),
                "suspectedIntervalOrders": int(suspected.get("orders") or 0),
                "suspectedIntervalOrderRatio": float(suspected.get("orderRatio") or 0),
                "suspectedIntervalGrossProfit": float(suspected.get("grossProfit") or 0),
                "suspectedIntervalNetProfit": float(suspected.get("netProfit") or 0),
                "suspectedIntervalCosts": float(suspected.get("costs") or 0),
                "suspectedIntervalBasis": str(suspected.get("basis") or "none"),
                "suspectedIntervalConfirmed": bool(suspected.get("confirmed")),
                "suspectedIntervalReturnPct": (
                    float(economic["intervalReturnPct"])
                    if economic.get("intervalReturnPct") is not None else None
                ),
                "economicQualified": bool(economic.get("qualified", True)),
                "economicReason": str(economic.get("reason") or ""),
                "initialScore": float(item.get("initialScore") or 0),
                "deepScore": float(item.get("deepScore") or 0),
                "level": str(item.get("deepLevel") or ""),
                "scoreBasis": dict(item.get("scoreBasis") or {}),
                "tickAvailable": bool(item.get("tickAvailable")),
                "coordinatedMatchedRatio": float(item.get("coordinatedMatchedRatio") or 0),
                "headline": str(item.get("headline") or ""),
                "routeReasons": list(item.get("routeReasons") or []),
                "suspectedAccomplices": list(item.get("suspectedAccomplices") or []),
            })
        return {
            "summary": summary,
            "results": results,
            "failureTotal": len(failures),
            "failureSummary": failure_summary,
            "failures": failures,
            "outputDir": str(summary_path.parent),
        }

    def _rebate_churning_scan(self, job: dict) -> dict:
        service = RebateChurningScanService(LegacyRebateRepository(self.legacy))

        def progress(percent: int, message: str) -> None:
            self.database.update_job(job["id"], progress=percent, event_message=message)

        def cancelled() -> bool:
            current = self.database.get_job(job["id"])
            if current and current.get("cancel_requested"):
                self.database.update_job(job["id"], status="cancelled", event_message="任务已取消")
                return True
            return False

        try:
            return service.run(job["payload"], progress=progress, cancelled=cancelled)
        except ScanCancelled:
            raise RuntimeError("任务已取消") from None

    def _bonus_arbitrage_scan(self, job: dict) -> dict:
        service = BonusArbitrageScanService(LegacyBonusArbitrageScanRepository(self.legacy))

        def progress(percent: int, message: str) -> None:
            self.database.update_job(job["id"], progress=percent, event_message=message)

        def cancelled() -> bool:
            current = self.database.get_job(job["id"])
            if current and current.get("cancel_requested"):
                self.database.update_job(job["id"], status="cancelled", event_message="任务已取消")
                return True
            return False

        handled = {
            str(record.account)
            for record in self.database.list_accounts()
            if str(record.action).strip().upper() in {"T", "TA", "A", "A/TA"}
        }
        try:
            return service.run(
                job["payload"],
                progress=progress,
                cancelled=cancelled,
                handled_logins=handled,
            )
        except BonusScanCancelled:
            raise RuntimeError("任务已取消") from None

    def _position_risk_scan(self, job: dict) -> dict:
        service = PositionRiskScanService(LegacyPositionRiskScanRepository(self.legacy))

        def progress(percent: int, message: str) -> None:
            self.database.update_job(job["id"], progress=percent, event_message=message)

        def cancelled() -> bool:
            current = self.database.get_job(job["id"])
            if current and current.get("cancel_requested"):
                self.database.update_job(job["id"], status="cancelled", event_message="任务已取消")
                return True
            return False

        handled = {
            str(record.account)
            for record in self.database.list_accounts()
            if str(record.action).strip().upper() in {"T", "TA", "A", "A/TA"}
        }
        try:
            return service.run(job["payload"], progress=progress, cancelled=cancelled, handled_logins=handled)
        except PositionRiskScanCancelled:
            raise RuntimeError("任务已取消") from None

    def process(self, job: dict) -> None:
        handlers = {
            "kline_inspect": self._kline_inspect,
            "kline_generate": self._kline_generate,
            "kline_from_database": self._kline_from_database,
            "toxic_check": self._toxic_check,
            "push_discovery": self._push_discovery,
            "rebate_churning_scan": self._rebate_churning_scan,
            "bonus_arbitrage_scan": self._bonus_arbitrage_scan,
            "position_risk_scan": self._position_risk_scan,
        }
        handler = handlers.get(job["kind"])
        if handler is None:
            raise RuntimeError(f"未知任务类型: {job['kind']}")
        if job.get("cancel_requested"):
            self.database.update_job(job["id"], status="cancelled", event_message="任务已取消")
            return
        stop_heartbeat = threading.Event()
        touch_job = getattr(self.database, "touch_job", None)

        def heartbeat() -> None:
            while not stop_heartbeat.wait(self.HEARTBEAT_INTERVAL_SECONDS):
                if callable(touch_job):
                    touch_job(job["id"])

        heartbeat_thread = threading.Thread(target=heartbeat, name=f"job-heartbeat-{job['id']}", daemon=True)
        heartbeat_thread.start()
        try:
            self.database.update_job(job["id"], progress=5, event_message=f"开始执行 {job['kind']}")
            result = handler(job)
            self.database.update_job(job["id"], status="done", progress=100, result=result, event_message="任务完成")
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=1)

    def run(self, *, once: bool = False, poll_seconds: float = 0.7) -> None:
        self.database.create_schema()
        self.database.recover_interrupted_jobs(
            kinds=self.kinds,
            stale_after_seconds=self.STALE_JOB_GRACE_SECONDS,
        )
        last_recovery = time.monotonic()
        while self.running:
            if time.monotonic() - last_recovery >= 15:
                self.database.recover_interrupted_jobs(
                    kinds=self.kinds,
                    stale_after_seconds=self.STALE_JOB_GRACE_SECONDS,
                )
                last_recovery = time.monotonic()
            job = self.database.claim_next_job(kinds=self.kinds)
            if not job:
                if once:
                    return
                time.sleep(poll_seconds)
                continue
            try:
                self.process(job)
            except Exception as exc:
                latest = self.database.get_job(job["id"]) or job
                if latest.get("status") == "cancelled":
                    if once:
                        return
                    continue
                retry = latest.get("attempts", 1) < latest.get("max_attempts", 2)
                self.database.update_job(
                    job["id"],
                    status="queued" if retry else "failed",
                    error=str(exc),
                    event_message=f"任务失败{'，准备重试' if retry else ''}: {exc}",
                    event_level="error",
                )
            if once:
                return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--profile", choices=("dev", "test", "prod"), default="")
    parser.add_argument("--queue", choices=("all", "interactive", "discovery"), default="all")
    args = parser.parse_args()
    if args.profile:
        os.environ["KDESK_PROFILE"] = args.profile
    config = Settings.load() if args.profile else default_settings
    config.ensure_runtime()
    Worker(config, queue=args.queue).run(once=args.once)


if __name__ == "__main__":
    main()
