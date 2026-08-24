from __future__ import annotations

import time
from pathlib import Path
from threading import Event, Lock
from typing import Any

from kdesk.application.relationship_expansion import AccountRelationshipExpansionCoordinator
from kdesk.application.relationship_network import AccountRelationshipNetworkService
from kdesk.application.relationship_process import IsolatedRelationshipRiskBuilder
from kdesk.application.relationship_risk import AccountRelationshipRiskService
from kdesk.domain.relationship_propagation import propagate_scores
from kdesk.settings import Settings


def _isolated_success_worker(
    result_queue, _settings, login, filters, _threshold, _include_toxic, _discovery_timeout, _source_timeout
) -> None:
    progress = {
        "ok": True, "account": login, "filters": filters, "entities": [], "relationships": [],
        "relationTypes": [], "coverage": [], "limitations": [],
        "summary": {"discoveryAccountCount": 1}, "inProgress": True,
    }
    result_queue.put(("progress", progress))
    result_queue.put(("complete", {**progress, "inProgress": False}))


def _isolated_stuck_worker(
    _result_queue, _settings, _login, _filters, _threshold, _include_toxic, _discovery_timeout, _source_timeout
) -> None:
    time.sleep(5)


def _test_settings(root: Path, profile: str = "prod") -> Settings:
    runtime = root / "runtime"
    return Settings(
        root=root,
        profile=profile,
        host="127.0.0.1",
        account_port=8777,
        kline_port=8766,
        runtime_dir=runtime,
        database_path=runtime / "kdesk.sqlite",
        queue_database_path=runtime / "jobs.sqlite",
        artifact_dir=runtime / "artifacts",
        upload_dir=runtime / "uploads",
        log_dir=runtime / "logs",
        legacy_root=root / "legacy",
        legacy_output=root / "legacy-output",
        legacy_trade_database=root / "trades.sqlite",
        bootstrap_xlsx=runtime / "bootstrap.xlsx",
        legacy_compat_dir=runtime / "legacy-compat",
        frontend_dist=root / "frontend",
        ui_mode="vue",
    )


class _EvidenceNetwork:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
        self.calls.append(login)
        subject = {
            "id": f"account:{login}", "type": "account", "label": login,
            "platform": filters["platform"], "server": filters["server"],
            "detail": "调查账户", "isSubject": True,
        }
        if login == "100":
            peer = {**subject, "id": "account:200", "label": "200", "isSubject": False}
            relationships = [{
                "id": "root-ea", "source": subject["id"], "target": peer["id"],
                "type": "ea_feature", "label": "EA 指纹", "evidence": ["Comment + ExpertID"],
            }]
            entities = [subject, peer]
        elif login == "200":
            peer = {**subject, "id": "account:300", "label": "300", "isSubject": False}
            relationships = [{
                "id": "peer-copy", "source": subject["id"], "target": peer["id"],
                "type": "copy_order", "label": "同步订单", "evidence": ["4 单匹配"],
            }]
            entities = [subject, peer]
        else:
            entities, relationships = [subject], []
        return {
            "entities": entities, "relationships": relationships,
            "relationTypes": [
                {"id": "ea_feature", "label": "EA"},
                {"id": "copy_order", "label": "跟单"},
                {"id": "login_ip", "label": "同 IP"},
            ],
            "coverage": [{"source": "fake", "status": "available", "reason": ""}],
        }


def _projection(entities: list[dict[str, Any]], relationships: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    return {"source": "test", "account": "100", **propagate_scores(entities, relationships, threshold=threshold)}


def test_relationship_risk_expands_real_evidence_until_score_falls_below_threshold() -> None:
    evidence = _EvidenceNetwork()
    service = AccountRelationshipRiskService(evidence, _projection, lambda _login, _filters: {"peers": [], "coverage": []})

    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert evidence.calls == ["100", "200", "300"]
    assert {node["label"] for node in result["entities"]} == {"100", "200", "300"}
    assert result["summary"]["relationshipCount"] == 2
    assert "已实际扩展 3 个" in result["limitations"][1]


def test_relationship_risk_without_a_global_deadline_expands_until_threshold() -> None:
    evidence = _EvidenceNetwork()
    service = AccountRelationshipRiskService(
        evidence,
        _projection,
        lambda _login, _filters: {"peers": [], "coverage": []},
        discovery_timeout_seconds=None,
    )

    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert evidence.calls == ["100", "200", "300"]
    assert result["queryBudgetExhausted"] is False
    assert result["discoveryTruncated"] is False


def test_relationship_expansion_runs_once_in_the_background_and_returns_progress() -> None:
    started = Event()
    release = Event()

    class _SlowRiskService:
        def build(self, login: str, filters: dict[str, str], threshold: float, *, include_toxic: bool, on_progress) -> dict[str, Any]:
            started.set()
            on_progress({
                "ok": True, "account": login, "filters": filters, "entities": [], "relationships": [],
                "relationTypes": [], "coverage": [], "limitations": [], "summary": {"discoveryAccountCount": 0},
                "inProgress": True, "queryBudgetExhausted": False, "discoveryTruncated": False,
            })
            release.wait(1)
            return {
                "ok": True, "account": login, "filters": filters, "entities": [], "relationships": [],
                "relationTypes": [], "coverage": [], "limitations": [], "summary": {"discoveryAccountCount": 3},
                "inProgress": False, "queryBudgetExhausted": False, "discoveryTruncated": False,
            }

    coordinator = AccountRelationshipExpansionCoordinator(_SlowRiskService(), max_concurrent_jobs=1)
    try:
        first = coordinator.get_or_start("100", {"platform": "MT5", "server": "AC CN MT5"}, 12, False)
        assert first["inProgress"] is True
        assert started.wait(0.5)
        duplicate = coordinator.get_or_start("100", {"platform": "MT5", "server": "AC CN MT5"}, 12, False)
        assert duplicate["inProgress"] is True
        release.set()
        deadline = time.monotonic() + 1
        completed = duplicate
        while completed["inProgress"] and time.monotonic() < deadline:
            time.sleep(0.01)
            completed = coordinator.get_or_start("100", {"platform": "MT5", "server": "AC CN MT5"}, 12, False)
        assert completed["inProgress"] is False
        assert completed["summary"]["discoveryAccountCount"] == 3
    finally:
        release.set()
        coordinator.close()


def test_relationship_expansion_bounds_distinct_resident_jobs_and_reports_pressure() -> None:
    started = Event()
    release = Event()

    class _BlockingRiskService:
        def build(self, login: str, filters: dict[str, str], threshold: float, *, include_toxic: bool, on_progress) -> dict[str, Any]:
            started.set()
            release.wait(1)
            return {
                "ok": True, "account": login, "filters": filters, "entities": [], "relationships": [],
                "relationTypes": [], "coverage": [], "limitations": [],
                "summary": {"discoveryAccountCount": 1}, "inProgress": False,
            }

    coordinator = AccountRelationshipExpansionCoordinator(
        _BlockingRiskService(), max_concurrent_jobs=1, max_resident_jobs=3,
    )
    try:
        for login in ("100", "200", "300"):
            coordinator.get_or_start(login, {"platform": "MT5"}, 20, False)
        assert started.wait(0.5)

        rejected = coordinator.get_or_start("400", {"platform": "MT5"}, 20, False)
        stats = coordinator.stats()

        assert rejected["progress"]["state"] == "busy"
        assert rejected["retryAfterSeconds"] == 3
        assert stats["residentJobs"] == 3
        assert stats["runningJobs"] == 1
        assert stats["queuedJobs"] == 2
    finally:
        release.set()
        coordinator.close()


def test_relationship_expansion_poll_does_not_deepcopy_the_full_graph() -> None:
    class _NoDeepcopy(dict):
        def __deepcopy__(self, _memo):
            raise AssertionError("polling must not deepcopy a complete graph")

    class _ImmediateRiskService:
        def build(self, login: str, filters: dict[str, str], threshold: float, *, include_toxic: bool, on_progress) -> dict[str, Any]:
            return {
                "ok": True, "account": login, "filters": filters,
                "entities": [_NoDeepcopy(id=f"account:{login}")], "relationships": [],
                "relationTypes": [], "coverage": [], "limitations": [],
                "summary": {"discoveryAccountCount": 1}, "inProgress": False,
            }

    coordinator = AccountRelationshipExpansionCoordinator(_ImmediateRiskService())
    try:
        snapshot = coordinator.get_or_start("100", {"platform": "MT5"}, 20, False)
        deadline = time.monotonic() + 1
        while snapshot["inProgress"] and time.monotonic() < deadline:
            time.sleep(0.01)
            snapshot = coordinator.get_or_start("100", {"platform": "MT5"}, 20, False)
        assert snapshot["entities"][0]["id"] == "account:100"
        assert snapshot["revision"] >= 1
    finally:
        coordinator.close()


def test_relationship_risk_throttles_heavy_progress_graph_materialization() -> None:
    evidence = _EvidenceNetwork()
    snapshots: list[dict[str, Any]] = []
    service = AccountRelationshipRiskService(
        evidence,
        _projection,
        lambda _login, _filters: {"peers": [], "coverage": []},
        progress_snapshot_interval_seconds=60,
    )

    service.build(
        "100",
        {"platform": "MT5", "server": "AC CN MT5"},
        threshold=12,
        on_progress=snapshots.append,
    )

    assert evidence.calls == ["100", "200", "300"]
    assert len(snapshots) == 1


def test_isolated_relationship_builder_forwards_progress_and_returns_complete_graph(tmp_path: Path) -> None:
    snapshots: list[dict[str, Any]] = []
    builder = IsolatedRelationshipRiskBuilder(
        _test_settings(tmp_path),
        discovery_timeout_seconds=30,
        source_timeout_seconds=6,
        process_timeout_seconds=5,
        worker_target=_isolated_success_worker,
    )

    result = builder.build(
        "100", {"platform": "MT5", "server": "AC CN MT5"}, 20, on_progress=snapshots.append,
    )

    assert result["inProgress"] is False
    assert result["account"] == "100"
    assert len(snapshots) == 1


def test_isolated_relationship_builder_terminates_a_worker_without_evidence(tmp_path: Path) -> None:
    builder = IsolatedRelationshipRiskBuilder(
        _test_settings(tmp_path),
        discovery_timeout_seconds=30,
        source_timeout_seconds=6,
        process_timeout_seconds=0.1,
        worker_target=_isolated_stuck_worker,
    )

    started_at = time.monotonic()
    try:
        builder.build("100", {"platform": "MT5"}, 20)
    except RuntimeError as exc:
        assert "没有返回可用证据" in str(exc)
    else:
        raise AssertionError("stuck isolated worker must fail")

    assert time.monotonic() - started_at < 3


def test_relationship_risk_materializes_kuzu_only_once_after_recursive_discovery() -> None:
    evidence = _EvidenceNetwork()
    projections: list[tuple[int, int]] = []

    def final_projection(entities: list[dict[str, Any]], relationships: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
        projections.append((len(entities), len(relationships)))
        return _projection(entities, relationships, threshold)

    service = AccountRelationshipRiskService(evidence, final_projection, lambda _login, _filters: {"peers": [], "coverage": []})
    service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert projections == [(3, 2)]


def test_relationship_evidence_returns_partial_coverage_when_one_source_exceeds_its_budget() -> None:
    release = Event()

    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        if name == "account_copy_group_profit_payload":
            release.wait(1)
        return {}

    service = AccountRelationshipNetworkService(legacy_call, source_timeout_seconds=0.01)
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"})
    release.set()

    timed_out = next(item for item in result["coverage"] if item["source"] == "copyGroups")
    assert timed_out == {"source": "copyGroups", "status": "timeout", "reason": "来源查询超过 0.01 秒预算"}


def test_relationship_evidence_uses_shared_last_ip_instead_of_slow_personal_ip_observation() -> None:
    calls: list[str] = []

    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        calls.append(name)
        return {}

    AccountRelationshipNetworkService(legacy_call).build("100", {"platform": "MT5", "server": "AC CN MT5"})

    assert "account_login_ips_payload" not in calls


def test_relationship_evidence_limits_a_slow_source_to_one_running_call_across_expansion() -> None:
    release = Event()
    started = Event()
    lock = Lock()
    active = 0
    peak = 0

    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        nonlocal active, peak
        if name != "account_ea_comment_profit_payload":
            return {}
        with lock:
            active += 1
            peak = max(peak, active)
        started.set()
        release.wait(1)
        with lock:
            active -= 1
        return {}

    service = AccountRelationshipNetworkService(legacy_call, source_timeout_seconds=0.01)
    try:
        service.build("100", {"platform": "MT5", "server": "AC CN MT5"})
        assert started.wait(0.5)
        service.build("200", {"platform": "MT5", "server": "AC CN MT5"})
        service.build("300", {"platform": "MT5", "server": "AC CN MT5"})
        assert peak == 1
    finally:
        release.set()
        service.close()


def test_relationship_evidence_can_use_the_remaining_discovery_budget() -> None:
    release = Event()

    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        if name == "account_copy_group_profit_payload":
            release.wait(1)
        return {}

    service = AccountRelationshipNetworkService(legacy_call, source_timeout_seconds=6)
    result = service.build_with_budget("100", {"platform": "MT5", "server": "AC CN MT5"}, remaining_seconds=0.01)
    release.set()

    timed_out = next(item for item in result["coverage"] if item["source"] == "copyGroups")
    assert timed_out == {"source": "copyGroups", "status": "timeout", "reason": "来源查询超过 0.01 秒预算"}


def test_relationship_evidence_reuses_automation_for_a_shared_current_last_ip_cohort() -> None:
    calls: list[str] = []

    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        calls.append(name)
        return {}

    service = AccountRelationshipNetworkService(legacy_call)
    try:
        result = service.build_with_budget(
            "200", {"platform": "MT5", "server": "AC CN MT5"},
            remaining_seconds=1, include_automation=False,
        )
    finally:
        service.close()

    assert set(calls) == {"account_relationship_core_payload", "account_crm_ib_relationship_payload"}
    skipped = {item["source"] for item in result["coverage"] if item["status"] == "skipped"}
    assert skipped == {"eaGroups", "copyOrigins", "copyGroups"}


def test_relationship_evidence_keeps_top_ib_members_collapsed_but_exposes_direct_ib_accounts() -> None:
    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        if name == "account_crm_ib_relationship_payload":
            return {"records": [{
                "crmSchema": "crm", "platform": "MT5", "server": "AC CN MT5", "crmUserId": 101,
                "directIbUserId": 202, "topIbUserId": 202,
                "directIbAccounts": [{"account": "200", "platform": "MT5", "server": "AC CN MT5"}],
                "topIbAccountCount": 601, "topIbClientCount": 600,
            }]}
        return {}

    result = AccountRelationshipNetworkService(legacy_call).build("100", {"platform": "MT5", "server": "AC CN MT5"})

    direct_account = next(entity for entity in result["entities"] if entity["type"] == "account" and entity["label"] == "200")
    aggregate = next(entity for entity in result["entities"] if entity["type"] == "ib_group")
    direct_edge = next(edge for edge in result["relationships"] if edge["type"] == "ib_direct_account")
    group_edge = next(edge for edge in result["relationships"] if edge["type"] == "top_ib_group")
    assert direct_edge["target"] == direct_account["id"]
    assert "601" in aggregate["detail"]
    assert any("600" in evidence for evidence in group_edge["evidence"])


def test_relationship_evidence_exposes_an_ib_owner_and_all_direct_rebate_accounts() -> None:
    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        if name == "account_crm_ib_relationship_payload":
            return {"records": [{
                "crmSchema": "crm", "platform": "MT5", "server": "AC CN MT5", "crmUserId": 23840,
                "ownIbDirectRebateChecked": True,
                "ownIbTotalAccounts": 40,
                "ownIbAbnormalAccounts": 2,
                "ibAnomalyPeriodStart": "2026-05-10 00:00:00",
                "ibAnomalyPeriodEnd": "2026-08-10 00:00:00",
                "ownIbDirectRebateAccounts": [
                    {"account": "300", "platform": "MT5", "server": "AC CN MT5", "databaseStatus": "P", "rebateOrderCount": 4, "rebateAmount": 100, "tradeProfit": 10, "combinedProfit": 110, "rebateShare": 100 / 110, "inclusionReasons": ["数据库状态 P", "返佣主导盈利"], "lastRebateAt": "2026-08-10 10:00:00"},
                    {"account": "301", "platform": "MT4", "server": "AC CN MT4", "databaseStatus": "B", "rebateOrderCount": 5, "rebateAmount": 80, "tradeProfit": 0, "combinedProfit": 80, "rebateShare": 1, "inclusionReasons": ["返佣主导盈利"], "lastRebateAt": "2026-08-09 10:00:00"},
                ],
            }]}
        return {}

    service = AccountRelationshipNetworkService(legacy_call)
    try:
        result = service.build("200", {"platform": "MT5", "server": "AC CN MT5"})
    finally:
        service.close()

    ib = next(entity for entity in result["entities"] if entity["type"] == "ib_user" and entity["label"] == "IB 23840")
    members = {entity["label"] for entity in result["entities"] if entity["type"] == "account"}
    identity = next(edge for edge in result["relationships"] if edge["type"] == "ib_identity")
    rebate_edges = [edge for edge in result["relationships"] if edge["type"] == "ib_direct_rebate"]
    assert {"200", "300", "301"}.issubset(members)
    assert identity["target"] == ib["id"]
    assert len(rebate_edges) == 2
    assert "异常 2 / 直属返佣账户共 40 个" in ib["detail"]
    assert next(entity for entity in result["entities"] if entity["label"] == "300")["databaseStatus"] == "P"
    assert any("返佣关联成交：4 笔" in item for item in rebate_edges[0]["evidence"])
    assert any("返佣占综合盈利：90.9%" in item for item in rebate_edges[0]["evidence"])


def test_relationship_evidence_only_expands_anomalies_below_the_direct_ib() -> None:
    def legacy_call(name: str, *_args: Any) -> dict[str, Any]:
        if name == "account_crm_ib_relationship_payload":
            return {"records": [{
                "crmSchema": "crm", "platform": "MT5", "server": "AC CN MT5", "crmUserId": 101,
                "directIbUserId": 202,
                "directIbAccounts": [{"account": "900", "platform": "MT5", "server": "AC CN MT5"}],
                "directIbTotalAccounts": 214,
                "directIbAbnormalAccounts": 2,
                "directIbHighestStatus": "T",
                "ibAnomalyPeriodStart": "2026-05-10 00:00:00",
                "ibAnomalyPeriodEnd": "2026-08-10 00:00:00",
                "directIbAnomalousRebateAccounts": [
                    {"account": "300", "platform": "MT5", "server": "AC CN MT5", "databaseStatus": "T", "rebateAmount": 0, "tradeProfit": -10, "combinedProfit": -10, "rebateShare": 0, "rebateOrderCount": 1, "inclusionReasons": ["数据库状态 T"]},
                    {"account": "301", "platform": "MT4", "server": "AC CN MT4", "databaseStatus": "B", "rebateAmount": 120, "tradeProfit": 5, "combinedProfit": 125, "rebateShare": 0.96, "rebateOrderCount": 9, "inclusionReasons": ["返佣主导盈利"]},
                ],
            }]}
        return {}

    service = AccountRelationshipNetworkService(legacy_call)
    try:
        result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"})
    finally:
        service.close()

    ib = next(entity for entity in result["entities"] if entity["type"] == "ib_user" and entity["label"] == "IB 202")
    anomaly_accounts = {entity["label"] for entity in result["entities"] if entity["type"] == "account"}
    anomaly_edges = [edge for edge in result["relationships"] if edge["type"] == "ib_direct_rebate"]
    assert {"100", "300", "301", "900"}.issubset(anomaly_accounts)
    assert "异常 2 / 直属返佣账户共 214 个" in ib["detail"]
    assert len(anomaly_edges) == 2
    assert all(edge["source"] == ib["id"] for edge in anomaly_edges)
    assert not any(edge["source"] == "account:100" for edge in anomaly_edges)
    assert any("纳入原因：数据库状态 T" in item for edge in anomaly_edges for item in edge["evidence"])


def test_relationship_evidence_deduplicates_the_same_ib_anomaly_edge_across_routes() -> None:
    member = {
        "account": "300", "platform": "MT5", "server": "AC CN MT5",
        "databaseStatus": "P", "rebateAmount": 10, "tradeProfit": -2,
        "combinedProfit": 8, "rebateShare": 1.25, "rebateOrderCount": 4,
        "inclusionReasons": ["数据库状态 P"],
    }

    def legacy_call(name: str, _login: str, _filters: dict[str, str]) -> dict[str, Any]:
        if name == "account_crm_ib_relationship_payload":
            return {"records": [{
                "crmSchema": "crm", "platform": "MT5", "server": "AC CN MT5",
                "crmUserId": 202, "directIbUserId": 202,
                "ownIbDirectRebateChecked": True,
                "ownIbDirectRebateAccounts": [member],
                "directIbAnomalyChecked": True,
                "directIbAnomalousRebateAccounts": [member],
            }]}
        return {}

    service = AccountRelationshipNetworkService(legacy_call)
    try:
        result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"})
    finally:
        service.close()

    edges = [edge for edge in result["relationships"] if edge["type"] == "ib_direct_rebate"]
    assert len(edges) == 1
    assert edges[0]["label"] == "IB 异常直属返佣账户"


def test_relationship_risk_expands_same_ip_peer_with_an_auditable_edge() -> None:
    evidence = _EvidenceNetwork()

    def shared_ip(login: str, filters: dict[str, str]) -> dict[str, Any]:
        if login != "100":
            return {"peers": [], "coverage": []}
        return {
            "peers": [{"account": "400", "platform": filters["platform"], "server": filters["server"], "ip": "203.0.113.8", "lastAccessAt": "2026-08-10 11:00:00"}],
            "coverage": [{"source": "sharedLastIp", "status": "available", "reason": ""}],
        }

    service = AccountRelationshipRiskService(evidence, _projection, shared_ip)
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert "400" in evidence.calls
    edge = next(item for item in result["relationships"] if item["type"] == "login_ip")
    assert edge["evidence"] == ["LastIP：203.0.113.8", "最后访问：2026-08-10 11:00:00"]


def test_relationship_risk_does_not_repeat_shared_last_ip_lookup_for_the_same_ip_cohort() -> None:
    class _FlatEvidenceNetwork:
        def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
            return {
                "entities": [{
                    "id": f"account:{login}", "type": "account", "label": login,
                    "platform": filters["platform"], "server": filters["server"], "isSubject": True,
                }],
                "relationships": [], "relationTypes": [{"id": "login_ip", "label": "同 IP"}], "coverage": [],
            }

    shared_calls: list[str] = []

    def shared_ip(login: str, filters: dict[str, str]) -> dict[str, Any]:
        shared_calls.append(login)
        if login == "100":
            return {
                "peers": [{"account": "200", "platform": filters["platform"], "server": filters["server"], "ip": "203.0.113.8"}],
                "coverage": [],
            }
        return {"peers": [], "coverage": []}

    service = AccountRelationshipRiskService(_FlatEvidenceNetwork(), _projection, shared_ip)
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert shared_calls == ["100"]
    assert {entity["label"] for entity in result["entities"]} == {"100", "200"}


def test_relationship_risk_expands_same_cid_peer_and_reads_the_cid_cohort_once() -> None:
    class _FlatEvidenceNetwork:
        def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
            return {
                "entities": [{
                    "id": f"account:{login}", "type": "account", "label": login,
                    "platform": filters["platform"], "server": filters["server"], "isSubject": True,
                }],
                "relationships": [], "relationTypes": [], "coverage": [],
            }

    cid_calls: list[str] = []

    def shared_cid(login: str, filters: dict[str, str]) -> dict[str, Any]:
        cid_calls.append(login)
        if login == "100":
            return {
                "peers": [{
                    "account": "500", "platform": filters["platform"], "server": filters["server"],
                    "cid": "987654", "lastAccessAt": "2026-08-24 01:09:03",
                }],
                "coverage": [{"source": "sharedCid", "status": "available", "reason": ""}],
            }
        return {"peers": [], "coverage": []}

    service = AccountRelationshipRiskService(
        _FlatEvidenceNetwork(), _projection,
        lambda _login, _filters: {"peers": [], "coverage": []},
        shared_cid_lookup=shared_cid,
    )
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert cid_calls == ["100"]
    assert {entity["label"] for entity in result["entities"]} == {"100", "500"}
    edge = next(item for item in result["relationships"] if item["type"] == "client_id")
    assert edge["label"] == "同当前 CID"
    assert edge["evidence"] == ["CID：987654", "最后访问：2026-08-24 01:09:03"]


def test_same_crm_relationship_is_presented_as_same_name_without_raw_schema_fields() -> None:
    def legacy_call(name: str, *_args, **_kwargs) -> dict[str, Any]:
        if name == "account_relationship_core_payload":
            return {
                "riskPanels": {
                    "available": True,
                    "databaseStatus": "P",
                    "sameName": [{
                        "account": "200", "platform": "MT5", "server": "AC CN MT5",
                        "databaseStatus": "M", "comprehensiveProfit": 12.3, "rebate": 1.2,
                        "currency": "USD",
                    }],
                }
            }
        return {}

    service = AccountRelationshipNetworkService(legacy_call)
    try:
        result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"})
    finally:
        service.close()

    edge = next(item for item in result["relationships"] if item["type"] == "same_crm_user")
    assert edge["typeLabel"] == "同名账户"
    assert edge["label"] == "同名账户"
    visible_text = " ".join(edge["evidence"])
    assert "mt_users_account" not in visible_text
    assert "user_id" not in visible_text
    assert "这些交易账户登记在同一客户名下" in visible_text


def test_relationship_risk_adds_toxic_sync_edges_only_for_nodes_with_investigation_score() -> None:
    evidence = _EvidenceNetwork()
    toxic_calls: list[str] = []

    def toxic(login: str, filters: dict[str, str]) -> dict[str, Any]:
        toxic_calls.append(login)
        if login != "100":
            return {"matches": [], "coverage": []}
        return {
            "matches": [{
                "account": "500", "platform": "MT5", "server": "DBG MT5",
                "relation": "opposite", "symbol": "XAUUSD", "orderId": "peer-1",
                "targetOrderId": "root-1", "openDeltaSeconds": 1.0,
                "closeDeltaSeconds": 2.0, "lotSimilarityPct": 92.0,
            }],
            "coverage": [{"source": "toxicSync", "status": "available", "reason": ""}],
        }

    service = AccountRelationshipRiskService(
        evidence, _projection, lambda _login, _filters: {"peers": [], "coverage": []}, toxic,
    )
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12, include_toxic=True)

    assert toxic_calls[0] == "100"
    edge = next(item for item in result["relationships"] if item["type"] == "toxic_sync_opposite")
    assert any("1s" in value for value in edge["evidence"])
    assert "500" in evidence.calls


def test_relationship_risk_aggregates_repeated_trade_pairs_into_one_peer_relation() -> None:
    evidence = _EvidenceNetwork()

    def toxic(_login: str, _filters: dict[str, str]) -> dict[str, Any]:
        if _login != "100":
            return {"matches": [], "coverage": []}
        return {
            "matches": [
                {
                    "account": "500", "platform": "MT5", "server": "AC CN MT5",
                    "relation": "same", "matchCount": 3, "matchRatioPct": 30.0,
                    "matchedVolumeRatioPct": 42.0, "orderPairs": [
                        {"symbol": "XAUUSD", "targetOrderId": "root-1", "orderId": "peer-1", "openDeltaSeconds": 1, "closeDeltaSeconds": 1},
                        {"symbol": "XAUUSD", "targetOrderId": "root-2", "orderId": "peer-2", "openDeltaSeconds": 1, "closeDeltaSeconds": 2},
                    ],
                },
                # Defensive duplicate from an adapter must merge into the same graph edge.
                {
                    "account": "500", "platform": "MT5", "server": "AC CN MT5",
                    "relation": "same", "symbol": "XAUUSD", "targetOrderId": "root-3",
                    "orderId": "peer-3", "openDeltaSeconds": 1, "closeDeltaSeconds": 1,
                },
            ],
            "coverage": [],
        }

    service = AccountRelationshipRiskService(
        evidence, _projection, lambda _login, _filters: {"peers": [], "coverage": []}, toxic,
    )
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12, include_toxic=True)

    edges = [item for item in result["relationships"] if item["type"] == "toxic_sync_same"]
    assert len(edges) == 1
    assert edges[0]["label"] == "主订单同向开平仓同步"
    assert any("命中 4 笔主订单" in value for value in edges[0]["evidence"])


def test_relationship_risk_expands_a_direct_ib_owned_account_but_not_a_top_ib_aggregate() -> None:
    class _IbEvidenceNetwork:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
            self.calls.append(login)
            subject = {
                "id": f"account:{login}", "type": "account", "label": login,
                "platform": filters["platform"], "server": filters["server"], "isSubject": True,
            }
            if login != "100":
                return {"entities": [subject], "relationships": [], "relationTypes": [], "coverage": []}
            ib_account = {**subject, "id": "account:200", "label": "200", "isSubject": False}
            ib_group = {"id": "ib_group:900", "type": "ib_group", "label": "顶级 IB 900", "detail": "聚合 600 个账户", "isSubject": False}
            return {
                "entities": [subject, ib_account, ib_group],
                "relationships": [
                    {"id": "direct-ib-account", "source": subject["id"], "target": ib_account["id"], "type": "ib_direct_account", "label": "直属 IB 自身交易账户", "evidence": ["CRM 直属上级账户"]},
                    {"id": "ib-group", "source": subject["id"], "target": ib_group["id"], "type": "top_ib_group", "label": "顶级 IB 群组（聚合）", "evidence": ["600 个账户，默认不展开"]},
                ],
                "relationTypes": [
                    {"id": "ib_direct_account", "label": "直属 IB 自身交易账户"},
                    {"id": "top_ib_group", "label": "顶级 IB 群组（聚合）"},
                ],
                "coverage": [],
            }

    evidence = _IbEvidenceNetwork()
    service = AccountRelationshipRiskService(evidence, _projection, lambda _login, _filters: {"peers": [], "coverage": []})

    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert evidence.calls == ["100", "200"]
    assert "200" in {entity["label"] for entity in result["entities"]}
    assert "顶级 IB 900" in {entity["label"] for entity in result["entities"]}
    assert not any(entity.get("type") == "account" and entity.get("label") == "600" for entity in result["entities"])


def test_relationship_risk_expands_direct_rebate_accounts_from_the_visible_ib_node() -> None:
    class _DirectRebateEvidenceNetwork:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
            self.calls.append(login)
            subject = {
                "id": f"account:{login}", "type": "account", "label": login,
                "platform": filters["platform"], "server": filters["server"], "isSubject": True,
            }
            if login == "100":
                owner = {**subject, "id": "account:200", "label": "200", "isSubject": False}
                return {
                    "entities": [subject, owner],
                    "relationships": [{"id": "owner", "source": subject["id"], "target": owner["id"], "type": "same_crm_user", "label": "同 CRM", "evidence": []}],
                    "relationTypes": [{"id": "same_crm_user", "label": "同 CRM"}], "coverage": [],
                }
            if login == "200":
                ib = {"id": "ib_user:23840", "type": "ib_user", "label": "IB 23840", "isSubject": False}
                member = {**subject, "id": "account:300", "label": "300", "isSubject": False}
                return {
                    "entities": [subject, ib, member],
                    "relationships": [
                        {"id": "identity", "source": subject["id"], "target": ib["id"], "type": "ib_identity", "label": "IB 身份确认", "evidence": []},
                        {"id": "rebate", "source": ib["id"], "target": member["id"], "type": "ib_direct_rebate", "label": "IB 直接返佣人员", "evidence": []},
                    ],
                    "relationTypes": [
                        {"id": "ib_identity", "label": "IB 身份确认"},
                        {"id": "ib_direct_rebate", "label": "IB 直接返佣人员"},
                    ], "coverage": [],
                }
            return {"entities": [subject], "relationships": [], "relationTypes": [], "coverage": []}

    evidence = _DirectRebateEvidenceNetwork()
    service = AccountRelationshipRiskService(evidence, _projection, lambda _login, _filters: {"peers": [], "coverage": []})
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=20)

    assert evidence.calls == ["100", "200", "300"]
    assert {"IB 23840", "300"}.issubset({entity["label"] for entity in result["entities"]})


def test_relationship_risk_stops_a_broad_ib_branch_at_the_account_safety_cap() -> None:
    class _BroadIbEvidenceNetwork:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
            self.calls.append(login)
            subject = {
                "id": f"account:{login}", "type": "account", "label": login,
                "platform": filters["platform"], "server": filters["server"], "isSubject": True,
            }
            if login != "100":
                return {"entities": [subject], "relationships": [], "relationTypes": [], "coverage": []}
            members = [
                {**subject, "id": f"account:{member}", "label": str(member), "isSubject": False}
                for member in range(200, 270)
            ]
            return {
                "entities": [subject, *members],
                "relationships": [
                    {"id": f"rebate-{member['label']}", "source": subject["id"], "target": member["id"],
                     "type": "ib_direct_rebate", "label": "IB 直接返佣人员", "evidence": []}
                    for member in members
                ],
                "relationTypes": [{"id": "ib_direct_rebate", "label": "IB 直接返佣人员"}], "coverage": [],
            }

    evidence = _BroadIbEvidenceNetwork()
    service = AccountRelationshipRiskService(
        evidence, _projection, lambda _login, _filters: {"peers": [], "coverage": []},
        max_account_expansions=12,
    )
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=20)

    assert len(evidence.calls) == 12
    assert result["discoveryTruncated"] is True
    assert "安全账户扩散上限 12" in result["limitations"][1]


def test_relationship_risk_only_requests_a_top_ib_aggregate_for_the_seed_account() -> None:
    class _TrackingEvidenceNetwork:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def build_with_budget(
            self,
            login: str,
            filters: dict[str, str],
            *,
            remaining_seconds: float,
            include_ib_aggregate: bool,
            include_automation: bool,
        ) -> dict[str, Any]:
            self.calls.append((login, include_ib_aggregate))
            subject = {
                "id": f"account:{login}", "type": "account", "label": login,
                "platform": filters["platform"], "server": filters["server"], "isSubject": True,
            }
            if login == "100":
                peer = {**subject, "id": "account:200", "label": "200", "isSubject": False}
                return {
                    "entities": [subject, peer],
                    "relationships": [{
                        "id": "ib-direct", "source": subject["id"], "target": peer["id"],
                        "type": "ib_direct_account", "label": "direct IB account", "evidence": [],
                    }],
                    "relationTypes": [{"id": "ib_direct_account", "label": "direct IB account"}],
                    "coverage": [],
                }
            return {"entities": [subject], "relationships": [], "relationTypes": [], "coverage": []}

    evidence = _TrackingEvidenceNetwork()
    service = AccountRelationshipRiskService(evidence, _projection, lambda _login, _filters: {"peers": [], "coverage": []})

    service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert evidence.calls == [("100", True), ("200", False)]


def test_relationship_risk_returns_partial_graph_when_shared_ip_ignores_its_budget() -> None:
    release = Event()

    def slow_shared_ip(_login: str, _filters: dict[str, str]) -> dict[str, Any]:
        release.wait(1)
        return {"peers": [], "coverage": []}

    service = AccountRelationshipRiskService(
        _EvidenceNetwork(),
        _projection,
        slow_shared_ip,
        discovery_timeout_seconds=0.05,
        shared_ip_timeout_seconds=0.01,
    )
    started = time.monotonic()
    try:
        result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)
    finally:
        release.set()

    assert time.monotonic() - started < 0.25
    assert any(
        item["source"] == "sharedLastIp" and item["status"] == "timeout"
        for item in result["coverage"]
    )


def test_relationship_risk_caps_kuzu_projection_before_materialization() -> None:
    class _BroadEvidenceNetwork:
        def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
            subject = {
                "id": f"account:{login}", "type": "account", "label": login,
                "platform": filters["platform"], "server": filters["server"], "isSubject": True,
            }
            if login != "100":
                return {"entities": [subject], "relationships": [], "relationTypes": [], "coverage": []}
            peers = [
                {**subject, "id": f"account:{index}", "label": str(index), "isSubject": False}
                for index in range(200, 650)
            ]
            edges = [
                {
                    "id": f"ea-{peer['label']}", "source": subject["id"], "target": peer["id"],
                    "type": "ea_feature", "label": "EA", "evidence": [],
                }
                for peer in peers
            ]
            return {
                "entities": [subject, *peers], "relationships": edges,
                "relationTypes": [{"id": "ea_feature", "label": "EA"}], "coverage": [],
            }

    projections: list[tuple[int, int]] = []

    def capped_projection(entities: list[dict[str, Any]], relationships: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
        projections.append((len(entities), len(relationships)))
        return _projection(entities, relationships, threshold)

    service = AccountRelationshipRiskService(
        _BroadEvidenceNetwork(), capped_projection, lambda _login, _filters: {"peers": [], "coverage": []},
    )
    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert projections[0][0] <= 400
    assert projections[0][1] <= 1_200
    assert result["truncated"] is True


def test_relationship_risk_returns_scored_fallback_when_kuzu_projection_is_unavailable() -> None:
    def unavailable_projection(
        _entities: list[dict[str, Any]], _relationships: list[dict[str, Any]], _threshold: float,
    ) -> dict[str, Any]:
        raise RuntimeError("Kuzu projection timed out")

    service = AccountRelationshipRiskService(
        _EvidenceNetwork(), unavailable_projection, lambda _login, _filters: {"peers": [], "coverage": []},
    )

    result = service.build("100", {"platform": "MT5", "server": "AC CN MT5"}, threshold=12)

    assert result["source"] == "risk-propagation-fallback"
    assert any(
        item["source"] == "kuzuProjection" and item["status"] == "failed"
        for item in result["coverage"]
    )
