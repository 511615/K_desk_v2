from __future__ import annotations

import time
from threading import Event, Lock
from typing import Any

from kdesk.application.relationship_expansion import AccountRelationshipExpansionCoordinator
from kdesk.application.relationship_network import AccountRelationshipNetworkService
from kdesk.application.relationship_risk import AccountRelationshipRiskService
from kdesk.domain.relationship_propagation import propagate_scores


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
