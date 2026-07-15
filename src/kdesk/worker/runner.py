from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
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
                self.database.update_job(job_id, event_message=line.rstrip())
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
        legacy.run_db_kline_job(job["id"], payload["account"], {key: payload.get(key, "") for key in ("platform", "server", "symbol", "start", "end")})
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
        legacy.run_toxic_job(job["id"], payload["account"], mode, type_ids, filters)
        result = legacy.get_toxic_job(job["id"])
        if result.get("status") != "done":
            raise RuntimeError(result.get("message") or "Toxic 检测失败")
        return result

    def process(self, job: dict) -> None:
        handlers = {
            "kline_inspect": self._kline_inspect,
            "kline_generate": self._kline_generate,
            "kline_from_database": self._kline_from_database,
            "toxic_check": self._toxic_check,
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
    args = parser.parse_args()
    config = default_settings
    config.ensure_runtime()
    Worker(config).run(once=args.once)


if __name__ == "__main__":
    main()
