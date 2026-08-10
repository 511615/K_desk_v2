from __future__ import annotations

import gc
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import kuzu
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from kdesk.api.account_app import create_account_app
from kdesk.api.kline_app import create_kline_app
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


def test_kline_upload_page_chains_inspection_to_generation(tmp_path: Path) -> None:
    app = create_kline_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "startGeneration" in response.text
    assert "/api/jobs/'+inspect.id+'/generate" in response.text
    assert "打开生成图表" in response.text


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


def test_copy_time_range_validation_returns_bad_request(tmp_path: Path, monkeypatch) -> None:
    def fake_call(_self, name, *args):
        assert name == "account_copy_origins_payload"
        raise ValueError("跟单开始时间不能晚于结束时间")

    monkeypatch.setattr(LegacyBridge, "call", fake_call)
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get(
            "/api/accounts/by-login/302360/copy-origins"
            "?start=2026-08-02%2000:00:00&end=2026-08-01%2000:00:00"
        )
    assert response.status_code == 400
    assert response.json()["error"] == "跟单开始时间不能晚于结束时间"


def test_account_detail_always_uses_legacy_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(LegacyBridge, "account_page", lambda _self, login: f"<html><body>legacy-account:{login}</body></html>")
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/account/302360?platform=MT5&server=DBG%20MT5")
        assert response.status_code == 200
        assert "legacy-account:302360" in response.text


def test_historical_funds_api_replays_read_only_source_facts(tmp_path: Path, monkeypatch) -> None:
    def fake_call(_self, name, *args):
        assert name == "account_historical_funds_source_payload"
        return {
            "available": True,
            "account": "302360",
            "platform": "MT4",
            "server": "DBG MT4 CN1",
            "source": "fixture",
            "currency": "USD",
            "moneyScale": 1,
            "coverage": {"eventRows": 2, "dailyAnchors": 1, "completeHistory": True},
            "anchors": [{"timestamp": "2026-01-01 00:00:00", "balance": 100, "credit": 20, "equity": 120}],
            "events": [
                {"id": "1", "timestamp": "2026-01-01 01:00:00", "CMD": 6, "PROFIT": 100, "COMMENT": "DEP-EO-1"},
                {"id": "2", "timestamp": "2026-01-01 02:00:00", "CMD": 7, "PROFIT": 10, "COMMENT": "BONUS"},
            ],
        }

    monkeypatch.setattr(LegacyBridge, "call", fake_call)
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/accounts/by-login/302360/historical-funds?platform=MT4&server=DBG%20MT4%20CN1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["available"] is True
    assert payload["summary"]["externalDeposit"] == 100
    assert payload["summary"]["bonusGranted"] == 10
    assert payload["events"][-1]["balance"] == 200
    assert payload["events"][-1]["credit"] == 30


def test_historical_funds_api_returns_a_readable_failure_without_database_detail(tmp_path: Path, monkeypatch) -> None:
    def failing_call(_self, _name, *_args):
        raise RuntimeError("source timeout should stay in server logs")

    monkeypatch.setattr(LegacyBridge, "call", failing_call)
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/accounts/by-login/302360/historical-funds?platform=MT5&server=DBG%20MT5")

    assert response.status_code == 503
    payload = response.json()
    assert payload["ok"] is False
    assert payload["available"] is False
    assert payload["error"] == "历史资金数据查询失败，请检查数据库连接"
    assert "timeout" not in payload["error"]


def test_relationship_network_returns_kuzu_scored_evidence_with_partial_source_coverage(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, tuple]] = []

    def fake_call(_self, name, *args):
        calls.append((name, args))
        if name == "account_risk_panels_payload":
            return {
                "riskPanels": {
                    "available": True,
                    "sameName": [{
                        "account": "302361", "platform": "MT5", "server": "DBG MT5",
                        "comprehensiveProfit": 120.5, "rebate": 15, "currency": "USD",
                    }],
                    "finance": {"rebate": 18.75, "rebateRows": 2, "displayCurrency": "USD"},
                }
            }
        if name == "account_login_ips_payload":
            return {"records": [{
                "ip": "203.0.113.42", "platform": "MT5", "server": "DBG MT5",
                "lastAccessAt": "2026-07-29 10:00:00", "firstSeenAt": "2026-07-01 10:00:00",
                "lastSeenAt": "2026-07-29 10:00:00", "geo": {"country": "CN"},
            }]}
        if name == "account_shared_last_ip_payload":
            return {"peers": [{"account": "302365", "platform": "MT5", "server": "DBG MT5", "ip": "203.0.113.42", "lastAccessAt": "2026-07-29 10:00:00"}], "coverage": [{"source": "sharedLastIp", "status": "available", "reason": ""}]}
        if name == "account_ea_comment_profit_payload":
            return {"groups": [{
                "comment": "GoldBot", "platform": "MT5", "server": "DBG MT5",
                "classificationLabel": "EA", "matchRule": "Comment + ExpertID",
                "members": [{
                    "account": "302362", "platform": "MT5", "server": "DBG MT5",
                    "orders": 8, "netProfit": 42.5, "currency": "USD", "matchClue": "Comment matched",
                }],
            }]}
        if name == "account_copy_origins_payload":
            return {"origins": [{
                "account": "302363", "platform": "MT5", "server": "DBG MT5", "matchedOrders": 4,
                "orders": 4, "netProfit": 11.2, "currency": "USD", "followers": [{
                    "account": "302364", "platform": "MT5", "server": "DBG MT5", "orders": 4,
                    "netProfit": 9.8, "currency": "USD",
                }],
            }]}
        if name == "account_copy_group_profit_payload":
            raise RuntimeError("copy group source temporarily unavailable")
        raise AssertionError(name)

    monkeypatch.setattr(LegacyBridge, "call", fake_call)
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/accounts/by-login/302360/relationship-network?platform=MT5&server=DBG%20MT5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account"] == "302360"
    assert payload["source"] == "kuzu-request-projection"
    assert payload["threshold"] == 12
    assert {item["id"] for item in payload["relationTypes"]} == {
        "same_crm_user", "login_ip", "ea_feature", "copy_order", "copy_group", "rebate",
        "toxic_sync_same", "toxic_sync_opposite",
    }
    assert {item["type"] for item in payload["relationships"]} == {
        "same_crm_user", "login_ip", "ea_feature", "copy_order", "rebate",
    }
    assert payload["summary"]["entityCount"] >= 7
    assert any(item["source"] == "copyGroups" and item["status"] == "failed" for item in payload["coverage"])
    assert "调查优先级" in payload["limitations"][0]
    assert all("score" in item and "riskColor" in item for item in payload["entities"])
    assert {name for name, _args in calls} == {
        "account_risk_panels_payload", "account_login_ips_payload", "account_copy_origins_payload",
        "account_copy_group_profit_payload", "account_ea_comment_profit_payload", "account_shared_last_ip_payload",
    }


def test_kuzu_risk_page_loads_the_replaced_account_relationship_endpoint(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))

    with TestClient(app) as client:
        page = client.get("/kuzu-risk?account=302360&platform=MT5&server=DBG%20MT5")

    assert page.status_code == 200
    assert "/api/accounts/by-login/" in page.text
    assert "relationship-network" in page.text
    assert "include_toxic" in page.text


def test_kuzu_demo_reads_a_persisted_local_evidence_graph(tmp_path: Path) -> None:
    graph_path = tmp_path / "relationship_graph_demo.kuzu"
    database = kuzu.Database(str(graph_path))
    connection = kuzu.Connection(database)
    connection.execute(
        "CREATE NODE TABLE Entity("
        "id STRING, kind STRING, label STRING, platform STRING, server STRING, "
        "detail STRING, subject BOOL, PRIMARY KEY(id))"
    )
    connection.execute(
        "CREATE REL TABLE Evidence("
        "FROM Entity TO Entity, id STRING, kind STRING, label STRING, evidence STRING)"
    )
    connection.execute(
        "CREATE (:Entity {id: 'account:2013674', kind: 'account', label: '2013674', "
        "platform: 'MT5', server: 'DBG CN MT5', detail: '', subject: true})"
    )
    connection.execute(
        "CREATE (:Entity {id: 'ea:demo', kind: 'ea_feature', label: 'Demo EA', "
        "platform: 'MT5', server: 'DBG CN MT5', detail: 'EA / 路由特征', subject: false})"
    )
    connection.execute(
        "CREATE (:Entity {id: 'account:2013675', kind: 'account', label: '2013675', "
        "platform: 'MT5', server: 'DBG CN MT5', detail: '净盈亏：12 USD', subject: false})"
    )
    connection.execute(
        "MATCH (subject:Entity), (feature:Entity) WHERE subject.id = 'account:2013674' AND feature.id = 'ea:demo' "
        "CREATE (subject)-[:Evidence {id: 'subject-ea', kind: 'ea_feature', label: 'EA / 路由特征', "
        "evidence: '[\"匹配规则：Comment + ExpertID\"]'}]->(feature)"
    )
    connection.execute(
        "MATCH (feature:Entity), (peer:Entity) WHERE feature.id = 'ea:demo' AND peer.id = 'account:2013675' "
        "CREATE (feature)-[:Evidence {id: 'ea-peer', kind: 'ea_feature', label: 'EA 特征匹配', "
        "evidence: '[\"Comment matched\"]'}]->(peer)"
    )
    connection.close()
    del connection
    del database
    gc.collect()

    settings = replace(make_test_settings(tmp_path), kuzu_demo_path=graph_path)
    app = create_account_app(settings)
    with TestClient(app) as client:
        page = client.get('/kuzu-demo')
        graph = client.get('/api/kuzu-demo/graph?depth=2')
        invalid_depth = client.get('/api/kuzu-demo/graph?depth=4')

    assert page.status_code == 200
    assert 'Kuzu 关系图试用' in page.text
    assert graph.status_code == 200
    payload = graph.json()
    assert payload['source'] == 'kuzu-local-cache'
    assert payload['depth'] == 2
    assert payload['summary'] == {'entityCount': 3, 'relationshipCount': 2}
    assert {entity['label'] for entity in payload['entities']} == {'2013674', 'Demo EA', '2013675'}
    assert payload['relationships'][0]['evidence']
    assert invalid_depth.status_code == 422


def test_kuzu_risk_graph_propagates_until_its_score_threshold(tmp_path: Path) -> None:
    graph_path = tmp_path / "relationship_risk_graph.kuzu"
    database = kuzu.Database(str(graph_path))
    connection = kuzu.Connection(database)
    connection.execute(
        "CREATE NODE TABLE Entity("
        "id STRING, kind STRING, label STRING, platform STRING, server STRING, "
        "detail STRING, subject BOOL, PRIMARY KEY(id))"
    )
    connection.execute(
        "CREATE REL TABLE Evidence("
        "FROM Entity TO Entity, id STRING, kind STRING, label STRING, evidence STRING)"
    )
    for account, subject in (("639549", "true"), ("639550", "false"), ("639551", "false"), ("639552", "false")):
        connection.execute(
            "CREATE (:Entity {id: 'account:" + account + "', kind: 'account', label: '" + account + "', "
            "platform: 'MT5', server: 'AC CN', detail: '', subject: " + subject + "})"
        )
    for edge_id, source, target, kind in (
        ("ip-1", "639549", "639550", "login_ip"),
        ("toxic-1", "639550", "639551", "toxic_sync_same"),
        ("name-1", "639551", "639552", "same_name"),
    ):
        connection.execute(
            "MATCH (source:Entity), (target:Entity) WHERE source.id = 'account:" + source
            + "' AND target.id = 'account:" + target + "' CREATE (source)-[:Evidence {id: '" + edge_id
            + "', kind: '" + kind + "', label: '" + kind + "', evidence: '[]'}]->(target)"
        )
    connection.close()
    del connection
    del database
    gc.collect()

    settings = replace(make_test_settings(tmp_path), kuzu_risk_path=graph_path)
    app = create_account_app(settings)
    with TestClient(app) as client:
        page = client.get("/kuzu-risk")
        graph = client.get("/api/kuzu-risk/graph?threshold=30")
        invalid_threshold = client.get("/api/kuzu-risk/graph?threshold=0")

    assert page.status_code == 200
    assert "Kuzu 关联风险扩散" in page.text
    assert "#ef4444" in page.text
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["source"] == "kuzu-local-cache"
    assert payload["threshold"] == 30
    assert payload["summary"]["entityCount"] == 4
    assert next(node for node in payload["entities"] if node["label"] == "639552")["expandable"] is False
    assert invalid_threshold.status_code == 422


def test_vue_workbench_forces_account_links_through_the_server() -> None:
    root = Path(__file__).resolve().parents[1]
    main_source = (root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
    workbench_source = (root / "frontend" / "src" / "pages" / "WorkbenchPage.vue").read_text(encoding="utf-8")

    assert "AccountPage" not in main_source
    assert "window.location.assign(to.fullPath)" in main_source
    assert "router.push" not in workbench_source
    assert "<RouterLink" not in workbench_source
    assert "window.location.assign(accountHref(" in workbench_source


def test_vue_index_is_not_cached_across_production_deployments(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    settings.frontend_dist.mkdir(parents=True)
    (settings.frontend_dist / "index.html").write_text("<html><body>versioned-ui</body></html>", encoding="utf-8")
    app = create_account_app(settings)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["pragma"] == "no-cache"


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


def test_rebate_scan_submission_is_persistent_and_normalized(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/rebate-churning/scans", json={
            "start": "2026-07-13", "end": "2026-07-20", "environments": ["dbg_vn", "gb"],
        })
        assert response.status_code == 200
        job = response.json()["job"]
        assert job["kind"] == "rebate_churning_scan"
        assert job["payload"]["environments"] == ["dbg_vn", "gb"]
        polled = client.get(f"/api/rebate-churning/scans/{job['id']}").json()
        assert polled["status"] == "queued"


def test_rebate_scan_rejects_ranges_over_31_days(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/rebate-churning/scans", json={"start": "2026-06-01", "end": "2026-07-20"})
    assert response.status_code == 400


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


def test_copy_and_ea_profit_reports_download_from_the_main_service(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_call(_self, name, *args):
        calls.append((name, args))
        if name == "account_copy_origins_payload":
            return {"ok": True, "account": "7798437", "detected": False, "origins": [], "errors": []}
        if name == "account_ea_comment_profit_payload":
            return {"ok": True, "account": "7798437", "detected": False, "groups": [], "errors": []}
        raise AssertionError(name)

    monkeypatch.setattr(LegacyBridge, "call", fake_call)
    app = create_account_app(make_test_settings(tmp_path))
    query = "platform=MT4&server=DBG%20MT4%20CN1"
    with TestClient(app) as client:
        copy_response = client.get(f"/api/accounts/by-login/7798437/copy-report.xlsx?{query}")
        ea_response = client.get(f"/api/accounts/by-login/7798437/ea-report.xlsx?{query}")

    assert copy_response.status_code == 200
    assert copy_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'filename="copy_profit_7798437_' in copy_response.headers["content-disposition"]
    assert load_workbook(BytesIO(copy_response.content), read_only=True).sheetnames == ["单主汇总"]
    assert ea_response.status_code == 200
    assert 'filename="ea_profit_7798437_' in ea_response.headers["content-disposition"]
    assert load_workbook(BytesIO(ea_response.content), read_only=True).sheetnames == ["EA汇总", "EA账户明细", "导出说明"]
    filters = {"platform": "MT4", "server": "DBG MT4 CN1", "symbol": "", "start": "", "end": ""}
    assert sorted(name for name, _args in calls) == [
        "account_copy_origins_payload",
        "account_ea_comment_profit_payload",
    ]
    assert all(args == ("7798437", filters) for _name, args in calls)


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
        job = response.json()["job"]
        payload = job["payload"]
        assert payload["requirePeriodProfit"] is False
        assert payload["deepLimit"] == 80
        assert payload["maxOrders"] == 100
        assert payload["requireMaxLot"] is True
        assert payload["minMaxLot"] == 0.05
        assert payload["requireTotalProfit"] is True
        assert payload["maxDeposit"] == 2000
        assert payload["maxActiveRatio"] == 25
        assert payload["excludeHandled"] is False
        assert job["max_attempts"] == 2


def test_push_discovery_active_job_can_be_resumed(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/push-discovery/start", json={"days": 3}).json()["job"]
        response = client.get("/api/push-discovery/active")

    assert response.status_code == 200
    assert response.json()["job"]["id"] == created["id"]
    assert response.json()["job"]["status"] == "queued"


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


def test_bonus_arbitrage_scan_options_are_validated_and_persisted(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/bonus-arbitrage/scans", json={
            "start": "2026-07-01 00:00:00",
            "end": "2026-07-20 00:00:00",
            "environments": ["ac_gb", "dbg_cn"],
            "deepLimit": 80,
            "minGrant": 100,
            "excludeHandled": False,
        })

    assert response.status_code == 200
    payload = response.json()["job"]["payload"]
    assert payload["environments"] == ["ac_gb", "dbg_cn"]
    assert payload["deepLimit"] == 80
    assert payload["minGrant"] == 100
    assert payload["excludeHandled"] is False


def test_bonus_arbitrage_scan_can_be_resumed_and_rejects_invalid_range(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/bonus-arbitrage/scans", json={
            "start": "2026-07-01", "end": "2026-07-20",
        }).json()["job"]
        active = client.get("/api/bonus-arbitrage/scans/active")
        invalid = client.post("/api/bonus-arbitrage/scans", json={
            "start": "2025-01-01", "end": "2026-07-20",
        })

    assert active.status_code == 200
    assert active.json()["job"]["id"] == created["id"]
    assert invalid.status_code == 400
    assert "180天" in invalid.json()["error"]


def test_position_risk_scan_is_persistent_recoverable_and_bounded(tmp_path: Path) -> None:
    app = create_account_app(make_test_settings(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/position-risk/scans", json={
            "start": "2026-07-01", "end": "2026-07-22", "environments": ["ac_gb", "dbg_cn"],
            "deepLimit": 80, "excludeHandled": False, "minPositionPercent": 30,
            "minLots": 2.5, "minProfit": 100,
        })
        assert created.status_code == 200
        job = created.json()["job"]
        active = client.get("/api/position-risk/scans/active")
        polled = client.get(f"/api/position-risk/scans/{job['id']}")
        invalid = client.post("/api/position-risk/scans", json={"start": "2026-01-01", "end": "2026-07-22"})

    assert job["kind"] == "position_risk_scan"
    assert job["payload"]["deepLimit"] == 80
    assert job["payload"]["excludeHandled"] is False
    assert job["payload"]["minPositionPercent"] == 30
    assert job["payload"]["minLots"] == 2.5
    assert job["payload"]["minProfit"] == 100
    assert active.json()["job"]["id"] == job["id"]
    assert polled.json()["status"] == "queued"
    assert invalid.status_code == 400
    assert "90天" in invalid.json()["error"]


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
