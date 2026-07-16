from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from kdesk.infrastructure.database import Database
from kdesk.infrastructure.legacy_bridge import LegacyBridge
from kdesk.settings import Settings
from kdesk.settings import settings as default_settings


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.legacy = LegacyBridge(settings)
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
        while True:
            line = process.stdout.readline()
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
            if process.poll() is not None:
                output.extend(process.stdout.readlines())
                break
            current = self.database.get_job(job_id)
            if current and current.get("cancel_requested"):
                process.kill()
                self.database.update_job(job_id, status="cancelled", event_message="运行中的任务已取消")
                raise RuntimeError("任务已取消")
            if time.monotonic() - started > timeout:
                process.kill()
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
        matches = re.findall(r"[A-Za-z]:\\[^\r\n]+?_trade_kline\.html", output)
        html_path = matches[-1].strip() if matches else ""
        return {"html_path": html_path, "html_url": f"/output/{Path(html_path).name}" if html_path else "", "output": output[-4000:]}

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
            "--small-order-priority", str(payload["smallOrderPriority"]),
            "--deep-limit", str(payload["deepLimit"]),
            "--workers", str(payload["workers"]),
            "--output-root", str(output_root),
        ]
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
        results = [{
            "deepRank": int(item.get("deepRank") or 0),
            "platform": str(item.get("platform") or ""),
            "server": str(item.get("server") or ""),
            "account": str(item.get("login") or ""),
            "orders": int(item.get("exactOrders") or item.get("closedOrders") or 0),
            "periodNetRaw": float(item.get("periodNetRaw") or 0),
            "initialScore": float(item.get("initialScore") or 0),
            "deepScore": float(item.get("deepScore") or 0),
            "level": str(item.get("deepLevel") or ""),
            "tickAvailable": bool(item.get("tickAvailable")),
            "coordinatedMatchedRatio": float(item.get("coordinatedMatchedRatio") or 0),
            "headline": str(item.get("headline") or ""),
            "routeReasons": list(item.get("routeReasons") or []),
            "suspectedAccomplices": list(item.get("suspectedAccomplices") or []),
        } for item in deep_results[:200]]
        return {"summary": summary, "results": results, "outputDir": str(summary_path.parent)}

    def process(self, job: dict) -> None:
        handlers = {
            "kline_inspect": self._kline_inspect,
            "kline_generate": self._kline_generate,
            "kline_from_database": self._kline_from_database,
            "toxic_check": self._toxic_check,
            "push_discovery": self._push_discovery,
        }
        handler = handlers.get(job["kind"])
        if handler is None:
            raise RuntimeError(f"未知任务类型: {job['kind']}")
        if job.get("cancel_requested"):
            self.database.update_job(job["id"], status="cancelled", event_message="任务已取消")
            return
        self.database.update_job(job["id"], progress=5, event_message=f"开始执行 {job['kind']}")
        result = handler(job)
        self.database.update_job(job["id"], status="done", progress=100, result=result, event_message="任务完成")

    def run(self, *, once: bool = False, poll_seconds: float = 0.7) -> None:
        self.database.create_schema()
        self.database.recover_interrupted_jobs()
        while self.running:
            job = self.database.claim_next_job()
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
    args = parser.parse_args()
    if args.profile:
        os.environ["KDESK_PROFILE"] = args.profile
    config = Settings.load() if args.profile else default_settings
    config.ensure_runtime()
    Worker(config).run(once=args.once)


if __name__ == "__main__":
    main()
