from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import kdesk.worker.runner as worker_module
from kdesk.settings import Settings
from kdesk.worker.runner import Worker, normalize_push_failure


def make_test_settings(tmp_path: Path) -> Settings:
    runtime = tmp_path / "runtime"
    return Settings(
        root=tmp_path,
        profile="test",
        host="127.0.0.1",
        account_port=8877,
        kline_port=8866,
        runtime_dir=runtime,
        database_path=runtime / "kdesk.sqlite",
        queue_database_path=runtime / "jobs.sqlite",
        artifact_dir=runtime / "artifacts",
        upload_dir=runtime / "uploads",
        log_dir=runtime / "logs",
        legacy_root=tmp_path / "legacy",
        legacy_output=tmp_path / "legacy_output",
        legacy_trade_database=tmp_path / "trades.sqlite",
        bootstrap_xlsx=runtime / "import" / "problematic_accounts.xlsx",
        legacy_compat_dir=runtime / "legacy_compat",
        frontend_dist=tmp_path / "frontend" / "dist",
        ui_mode="vue",
    )


def test_normalize_push_failure_explains_known_failures() -> None:
    timeout = normalize_push_failure({
        "stage": "aggregate",
        "source": "AC CN MT5",
        "attempts": 2,
        "error": "(2013, 'Lost connection to MySQL server during query (timed out)')",
    })
    assert timeout["stageLabel"] == "候选聚合"
    assert timeout["reason"] == "数据库查询超时或连接中断，重试后仍未恢复"
    assert timeout["account"] == ""

    no_rows = normalize_push_failure({
        "stage": "deep",
        "source": "AC GB MT4",
        "platform": "MT4",
        "server": "AC GB MT4",
        "login": "6003464",
        "error": "账号全历史没有可检测订单",
    })
    assert no_rows["reason"] == "当前服务器归属下没有可用于深检的已平仓订单"
    assert no_rows["impact"] == "该账号没有生成深检结果"


def test_push_discovery_result_includes_failure_details(tmp_path: Path, monkeypatch) -> None:
    settings = make_test_settings(tmp_path)
    run_dir = settings.runtime_dir / "push_discovery" / "push_discovery_test"
    run_dir.mkdir(parents=True)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps({"failures": 2}), encoding="utf-8")
    (run_dir / "deep_results.json").write_text(json.dumps([
        {
            "login": "5000002", "platform": "MT4", "server": "AC CN MT4",
            "suspectedPushIntervals": {"intervalCount": 1, "netProfit": 120},
            "economicEvidence": {
                "qualified": True, "intervalReturnPct": 24.0,
                "reason": "疑似区间已形成与资金规模相符的正向经济结果",
            },
        },
        {
            "login": "5000003", "platform": "MT4", "server": "AC CN MT4",
            "suspectedPushIntervals": {"intervalCount": 1, "netProfit": 5},
            "economicEvidence": {"qualified": False, "reason": "收益过低"},
        },
    ]), encoding="utf-8")
    (run_dir / "failures.json").write_text(json.dumps([
        {"stage": "aggregate", "source": "DBG MT5", "error": "timed out", "attempts": 2},
        {
            "stage": "deep", "source": "AC MT4", "platform": "MT4", "server": "AC CN MT4",
            "login": "5000001", "error": "账号全历史没有可检测订单",
        },
    ]), encoding="utf-8")
    worker = Worker(settings, queue="discovery")
    monkeypatch.setattr(worker, "_run_process", lambda *_args, **_kwargs: f"RESULT {summary_path}\n")
    payload = {
        "days": 3, "maxOrders": 100, "minMaxLot": 0.01, "maxDeposit": 2000,
        "maxActiveRatio": 30, "smallOrderPriority": 100, "deepLimit": 50, "workers": 4,
        "requirePeriodProfit": True, "limitOrders": True, "requireMaxLot": True,
        "requireTotalProfit": True, "limitDeposit": True, "limitActiveRatio": True,
        "excludeHandled": True,
    }

    result = worker._push_discovery({"id": "test-job", "payload": payload})

    assert result["failureTotal"] == 2
    assert result["failureSummary"] == {"候选聚合": 1, "深度检测": 1}
    assert result["failures"][1]["account"] == "5000001"
    assert [row["account"] for row in result["results"]] == ["5000002"]
    assert result["results"][0]["suspectedIntervalReturnPct"] == 24.0
    assert result["results"][0]["economicQualified"] is True


def test_run_process_cancels_even_when_child_has_no_output(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    worker = Worker(settings, queue="discovery")

    class CancellingDatabase:
        def __init__(self) -> None:
            self.polls = 0
            self.updates: list[dict] = []

        def get_job(self, _job_id: str) -> dict:
            self.polls += 1
            return {"cancel_requested": self.polls >= 2}

        def update_job(self, _job_id: str, **values) -> None:
            self.updates.append(values)

    database = CancellingDatabase()
    worker.database = database  # type: ignore[assignment]
    started = time.monotonic()

    try:
        worker._run_process("cancel-test", [sys.executable, "-c", "import time; time.sleep(10)"])
    except RuntimeError as exc:
        assert str(exc) == "任务已取消"
    else:
        raise AssertionError("silent child process was not cancelled")

    assert time.monotonic() - started < 3
    assert any(update.get("status") == "cancelled" for update in database.updates)


def test_toxic_worker_replaces_legacy_bonus_placeholder(tmp_path: Path, monkeypatch) -> None:
    settings = make_test_settings(tmp_path)
    worker = Worker(settings, queue="interactive")

    class LegacyModule:
        TOXIC_CHECK_TYPES = [{"id": "bonus_arbitrage"}, {"id": "short_close_trading"}]

        @staticmethod
        def run_toxic_job(*_args) -> None:
            return None

        @staticmethod
        def get_toxic_job(_job_id: str) -> dict:
            return {
                "status": "done",
                "result": {
                    "results": [
                        {"type": "bonus_arbitrage", "label": "赠金套利", "score": 10},
                        {"type": "short_close_trading", "label": "短平交易", "score": 30},
                    ]
                },
            }

    class LegacyBridgeStub:
        @staticmethod
        def module() -> LegacyModule:
            return LegacyModule()

    class DatabaseStub:
        updates: list[dict] = []

        def update_job(self, _job_id: str, **values) -> None:
            self.updates.append(values)

    class BonusServiceStub:
        def __init__(self, _repository) -> None:
            pass

        @staticmethod
        def analyze(*_args, **_kwargs) -> dict:
            return {
                "type": "bonus_arbitrage", "label": "赠金套利", "score": 90,
                "level": "严重形态", "evidence": {"cycles": [{"extractor": True}]},
            }

    worker.legacy = LegacyBridgeStub()  # type: ignore[assignment]
    worker.database = DatabaseStub()  # type: ignore[assignment]
    monkeypatch.setattr(worker, "_run_legacy_monitored", lambda *_args: None)
    monkeypatch.setattr(worker_module, "LegacyBonusArbitrageRepository", lambda _bridge: object())
    monkeypatch.setattr(worker_module, "BonusArbitrageService", BonusServiceStub)

    result = worker._toxic_check({
        "id": "bonus-job",
        "payload": {"account": "621928", "mode": "selected", "types": ["bonus_arbitrage"], "platform": "MT5", "server": "AC GB MT5"},
    })

    rows = result["result"]["results"]
    assert [row["type"] for row in rows] == ["bonus_arbitrage", "short_close_trading"]
    assert rows[0]["score"] == 90
    assert result["result"]["bonusArbitrage"]["cycles"][0]["extractor"] is True
    assert worker.database.updates[-1]["event_message"] == "正在复核历史赠金、提款与关联账户资金周期"


def test_toxic_worker_replaces_weekend_and_open_with_position_risk(tmp_path: Path, monkeypatch) -> None:
    settings = make_test_settings(tmp_path)
    worker = Worker(settings, queue="interactive")

    class LegacyModule:
        TOXIC_CHECK_TYPES = [{"id": "weekend_gap_trading"}, {"id": "open_betting"}, {"id": "short_close_trading"}]

        @staticmethod
        def run_toxic_job(*_args) -> None:
            return None

        @staticmethod
        def get_toxic_job(_job_id: str) -> dict:
            return {"status": "done", "result": {"results": [
                {"type": "weekend_gap_trading", "score": 40},
                {"type": "open_betting", "score": 50},
                {"type": "short_close_trading", "score": 30},
            ]}}

    class LegacyBridgeStub:
        @staticmethod
        def module() -> LegacyModule:
            return LegacyModule()

    class DatabaseStub:
        updates: list[dict] = []

        def update_job(self, _job_id: str, **values) -> None:
            self.updates.append(values)

    class PositionServiceStub:
        def __init__(self, _repository) -> None:
            pass

        @staticmethod
        def analyze(*_args, **_kwargs) -> dict:
            return {"results": [
                {"type": "weekend_gap_trading", "label": "周末跳空交易", "score": 88},
                {"type": "open_betting", "label": "赌开盘", "score": 92},
            ], "events": [{"classification": "combined"}], "source": {"leverage": 1000}}

    worker.legacy = LegacyBridgeStub()  # type: ignore[assignment]
    worker.database = DatabaseStub()  # type: ignore[assignment]
    monkeypatch.setattr(worker, "_run_legacy_monitored", lambda *_args: None)
    monkeypatch.setattr(worker_module, "LegacyPositionRiskRepository", lambda _bridge: object())
    monkeypatch.setattr(worker_module, "PositionRiskService", PositionServiceStub)

    result = worker._toxic_check({
        "id": "position-job",
        "payload": {"account": "5005153", "mode": "selected", "types": ["weekend_gap_trading", "open_betting"], "platform": "MT5", "server": "AC GB MT5"},
    })

    rows = result["result"]["results"]
    assert [row["type"] for row in rows] == ["open_betting", "weekend_gap_trading", "short_close_trading"]
    assert result["result"]["positionRisk"]["source"]["leverage"] == 1000
    assert worker.database.updates[-1]["event_message"] == "正在按历史权益、杠杆和持仓敞口复核特殊时点"


def test_toxic_worker_replaces_internal_lock_with_cross_account_query(tmp_path: Path, monkeypatch) -> None:
    settings = make_test_settings(tmp_path)
    worker = Worker(settings, queue="interactive")

    class LegacyModule:
        TOXIC_CHECK_TYPES = [{"id": "internal_lock_arbitrage"}, {"id": "short_close_trading"}]

        @staticmethod
        def run_toxic_job(*_args) -> None:
            return None

        @staticmethod
        def get_toxic_job(_job_id: str) -> dict:
            return {"status": "done", "result": {"results": [
                {"type": "internal_lock_arbitrage", "score": 35},
                {"type": "short_close_trading", "score": 30},
            ]}}

    class LegacyBridgeStub:
        @staticmethod
        def module() -> LegacyModule:
            return LegacyModule()

    class DatabaseStub:
        updates: list[dict] = []

        def update_job(self, _job_id: str, **values) -> None:
            self.updates.append(values)

    class HedgeServiceStub:
        def __init__(self, _repository) -> None:
            pass

        @staticmethod
        def analyze(*_args, **_kwargs) -> dict:
            return {
                "result": {
                    "type": "internal_lock_arbitrage", "label": "平台内多账户对锁",
                    "score": 100, "level": "发现疑似对锁", "evidence": {"hedgeQuery": {"accountCount": 1}},
                },
                "evidence": {"accountCount": 1, "matchTotal": 2},
            }

    worker.legacy = LegacyBridgeStub()  # type: ignore[assignment]
    worker.database = DatabaseStub()  # type: ignore[assignment]
    monkeypatch.setattr(worker, "_run_legacy_monitored", lambda *_args: None)
    monkeypatch.setattr(worker_module, "LegacyPositionRiskRepository", lambda _bridge: object())
    monkeypatch.setattr(worker_module, "CrossAccountHedgeService", HedgeServiceStub)

    result = worker._toxic_check({
        "id": "hedge-job",
        "payload": {"account": "1001", "mode": "selected", "types": ["internal_lock_arbitrage"], "platform": "MT5", "server": "AC GB MT5"},
    })

    rows = result["result"]["results"]
    assert [row["type"] for row in rows] == ["internal_lock_arbitrage", "short_close_trading"]
    assert rows[0]["level"] == "发现疑似对锁"
    assert result["result"]["internalLock"]["matchTotal"] == 2
    assert worker.database.updates[-1]["event_message"] == "正在查询全平台反向同步开平仓订单"


def test_bonus_scan_worker_passes_handled_accounts_to_service(tmp_path: Path, monkeypatch) -> None:
    settings = make_test_settings(tmp_path)
    worker = Worker(settings, queue="discovery")
    captured = {}

    class Record:
        account = "900001"
        action = "A/TA"

    class DatabaseStub:
        updates = []

        @staticmethod
        def list_accounts():
            return [Record()]

        @staticmethod
        def get_job(_job_id):
            return {"cancel_requested": False}

        def update_job(self, _job_id, **values):
            self.updates.append(values)

    class ServiceStub:
        def __init__(self, _repository):
            pass

        @staticmethod
        def run(payload, **kwargs):
            captured["payload"] = payload
            captured["handled"] = kwargs["handled_logins"]
            kwargs["progress"](50, "half")
            return {"summary": {"candidateAccounts": 1}}

    worker.database = DatabaseStub()  # type: ignore[assignment]
    monkeypatch.setattr(worker_module, "LegacyBonusArbitrageScanRepository", lambda _bridge: object())
    monkeypatch.setattr(worker_module, "BonusArbitrageScanService", ServiceStub)

    result = worker._bonus_arbitrage_scan({"id": "bonus-scan", "payload": {"deepLimit": 10}})

    assert captured["handled"] == {"900001"}
    assert result["summary"]["candidateAccounts"] == 1
    assert worker.database.updates[-1]["progress"] == 50
