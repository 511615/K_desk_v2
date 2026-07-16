from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kdesk.api.account_app import create_account_app
from kdesk.settings import Settings


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


def test_health_and_ledger_api_are_isolated(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/ready").json()["ok"] is True
        saved = client.post("/api/accounts/mark", json={"account": "302360", "action": "M", "status": "观察中"})
        assert saved.status_code == 200
        ledger = client.get("/api/accounts/by-login/302360/ledger").json()
        assert ledger["marked"] is True
        assert ledger["record"]["建议动作"] == "M"


def test_account_validation_rejects_unsafe_path_data(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/accounts/mark", json={"account": "../bad"})
        assert response.status_code == 400


def test_job_polling_keeps_legacy_and_v2_contracts(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        created = app.state.database.create_job("toxic_check", {"account": "302360"})
        app.state.database.update_job(
            created["id"],
            status="done",
            progress=100,
            result={
                "status": "done",
                "percent": 100,
                "message": "Toxic 检测完成",
                "result": {"account": "302360", "results": [{"type": "market_pushing", "score": 62.1}]},
            },
        )
        payload = client.get(f"/api/toxic/jobs/{created['id']}").json()
        assert payload["status"] == "done"
        assert payload["progress"] == 100
        assert payload["job"]["percent"] == 100
        assert payload["job"]["message"] == "Toxic 检测完成"
        assert payload["job"]["result"]["results"][0]["type"] == "market_pushing"
