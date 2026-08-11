from __future__ import annotations

from threading import Event
from typing import Any

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
