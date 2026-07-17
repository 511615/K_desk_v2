from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kdesk.api.account_app import create_account_app
from kdesk.infrastructure.legacy_bridge import LegacyBridge
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


def test_api_meta_exposes_governed_build_information(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        payload = client.get("/api/meta").json()
    assert payload["version"] == "2.1.0"
    assert payload["gitSha"]
    assert payload["buildTime"]
    assert payload["schemaRevision"] in {"unversioned", "uninitialized", "0001"}
    assert payload["featureRegistryVersion"]
    assert payload["featureCount"] >= 10
    assert payload["compatibilityLevel"] == "legacy-account-v1"


def test_account_validation_rejects_unsafe_path_data(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/accounts/mark", json={"account": "../bad"})
        assert response.status_code == 400


def test_account_detail_always_uses_legacy_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(LegacyBridge, "account_page", lambda _self, login: f"<html><body>legacy-account:{login}</body></html>")
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/account/302360?platform=MT5&server=DBG%20MT5")
        assert response.status_code == 200
        assert "legacy-account:302360" in response.text


def test_vue_workbench_forces_account_links_through_the_server() -> None:
    root = Path(__file__).resolve().parents[1]
    main_source = (root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
    workbench_source = (root / "frontend" / "src" / "pages" / "WorkbenchPage.vue").read_text(encoding="utf-8")

    assert "AccountPage" not in main_source
    assert "window.location.assign(to.fullPath)" in main_source
    assert "router.push" not in workbench_source
    assert "<RouterLink" not in workbench_source
    assert "window.location.assign(accountHref(" in workbench_source


def test_rebate_account_audit_is_exposed_on_the_main_service(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_call(_self, name, *args):
        calls.append((name, args))
        return {"ok": True, "account": {"account": 7798437}, "query": {"start": "2021-06-02 00:00:00"}}

    monkeypatch.setattr(LegacyBridge, "call", fake_call)
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/rebate-churning/accounts/7798437?environment=dbg_cn")

    assert response.status_code == 200
    assert response.json()["account"]["account"] == 7798437
    assert calls == [("rebate_churning_account_audit_payload", ("7798437", "", "", "dbg_cn", ""))]


def test_rebate_account_audit_returns_account_candidates(tmp_path: Path, monkeypatch) -> None:
    class AmbiguousAccount(ValueError):
        candidates = [{"environment": "gb", "serverCode": "1"}]

    def fake_call(_self, _name, *_args):
        raise AmbiguousAccount("该账户在多个服务器存在")

    monkeypatch.setattr(LegacyBridge, "call", fake_call)
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/rebate-churning/accounts/5000000")

    assert response.status_code == 409
    assert response.json()["candidates"][0]["serverCode"] == "1"


def test_ea_comment_profit_is_exposed_on_the_main_service(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_call(_self, name, *args):
        calls.append((name, args))
        return {"ok": True, "account": "7798437", "detected": True, "groups": [{"comment": "GoldBot"}]}

    monkeypatch.setattr(LegacyBridge, "call", fake_call)
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/accounts/by-login/7798437/ea-comment-profit?platform=MT4&server=DBG%20MT4%20CN1")

    assert response.status_code == 200
    assert response.json()["groups"][0]["comment"] == "GoldBot"
    assert calls == [("account_ea_comment_profit_payload", ("7798437", {
        "platform": "MT4", "server": "DBG MT4 CN1", "symbol": "", "start": "", "end": "",
    }))]


def test_push_discovery_filters_are_validated_and_persisted(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/push-discovery/start", json={
            "days": 3,
            "deepLimit": 80,
            "requirePeriodProfit": False,
            "limitOrders": True,
            "maxOrders": 100,
            "requireMaxLot": True,
            "minMaxLot": 0.05,
            "requireTotalProfit": True,
            "limitDeposit": True,
            "maxDeposit": 2000,
            "limitActiveRatio": True,
            "maxActiveRatio": 25,
            "excludeHandled": False,
        })
        assert response.status_code == 200
        payload = response.json()["job"]["payload"]
        assert payload["requirePeriodProfit"] is False
        assert payload["deepLimit"] == 80
        assert payload["maxOrders"] == 100
        assert payload["requireMaxLot"] is True
        assert payload["minMaxLot"] == 0.05
        assert payload["requireTotalProfit"] is True
        assert payload["maxDeposit"] == 2000
        assert payload["maxActiveRatio"] == 25
        assert payload["excludeHandled"] is False


def test_push_discovery_rejects_invalid_active_ratio(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/push-discovery/start", json={"maxActiveRatio": 101})
        assert response.status_code == 400


def test_push_discovery_rejects_invalid_deep_limit(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/push-discovery/start", json={"deepLimit": 301})
        assert response.status_code == 400


def test_push_discovery_rejects_invalid_min_max_lot(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/push-discovery/start", json={"minMaxLot": -0.01})
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


def test_queued_toxic_job_has_a_visible_legacy_status(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        created = app.state.database.create_job("toxic_check", {"account": "239453"})
        payload = client.get(f"/api/toxic/jobs/{created['id']}").json()
        assert payload["job"]["status"] == "queued"
        assert payload["job"]["percent"] == 0
        assert payload["job"]["message"] == "已提交，等待后台执行"
