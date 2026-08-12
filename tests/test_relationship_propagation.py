from __future__ import annotations

from kdesk.domain.relationship_propagation import propagate_scores


def _entities() -> list[dict]:
    return [
        {"id": "account:seed", "label": "639549", "isSubject": True},
        {"id": "account:ip-peer", "label": "639550", "isSubject": False},
        {"id": "account:toxic-peer", "label": "639551", "isSubject": False},
        {"id": "account:outer", "label": "639552", "isSubject": False},
    ]


def _relationships() -> list[dict]:
    return [
        {"id": "ip-1", "source": "account:seed", "target": "account:ip-peer", "type": "login_ip"},
        {"id": "toxic-1", "source": "account:ip-peer", "target": "account:toxic-peer", "type": "toxic_sync_same"},
        {"id": "name-1", "source": "account:toxic-peer", "target": "account:outer", "type": "same_name"},
    ]


def _node(payload: dict, node_id: str) -> dict:
    return next(node for node in payload["entities"] if node["id"] == node_id)


def test_propagation_has_no_depth_limit_and_stops_expansion_at_the_score_threshold() -> None:
    payload = propagate_scores(_entities(), _relationships(), threshold=30)

    ip_peer = _node(payload, "account:ip-peer")
    toxic_peer = _node(payload, "account:toxic-peer")
    outer = _node(payload, "account:outer")
    assert ip_peer["score"] > toxic_peer["score"] > outer["score"] > 0
    assert ip_peer["expandable"] is True
    assert toxic_peer["expandable"] is True
    assert outer["expandable"] is False
    assert payload["truncated"] is False


def test_independent_evidence_families_combine_without_double_counting_the_same_family() -> None:
    relationships = _relationships()[:1] + [
        {"id": "ea-1", "source": "account:seed", "target": "account:ip-peer", "type": "ea_feature"},
        {"id": "ip-duplicate", "source": "account:seed", "target": "account:ip-peer", "type": "login_ip"},
    ]

    payload = propagate_scores(_entities(), relationships, threshold=30)
    peer = _node(payload, "account:ip-peer")

    assert peer["score"] > 90
    assert {entry["type"] for entry in peer["scoreLedger"]} == {"login_ip", "ea_feature"}
    assert len(peer["scoreLedger"]) == 2


def test_cycle_terminates_and_renders_high_scores_with_an_urgent_risk_color() -> None:
    relationships = _relationships()[:2] + [
        {"id": "cycle-1", "source": "account:toxic-peer", "target": "account:ip-peer", "type": "toxic_sync_same"},
    ]

    payload = propagate_scores(_entities(), relationships, threshold=12)

    assert payload["truncated"] is False
    assert len(payload["entities"]) == 3
    assert _node(payload, "account:seed")["riskColor"] == "#ef4444"
    assert _node(payload, "account:ip-peer")["riskColor"] == "#ef4444"


def test_ib_identity_keeps_the_owner_score_and_direct_rebate_accounts_can_expand() -> None:
    entities = [
        {"id": "account:seed", "label": "100", "isSubject": True},
        {"id": "account:ib-owner", "label": "200", "isSubject": False},
        {"id": "ib_user:23840", "label": "IB 23840", "isSubject": False},
        {"id": "account:rebate-person", "label": "300", "isSubject": False},
    ]
    relationships = [
        {"id": "seed-owner", "source": "account:seed", "target": "account:ib-owner", "type": "same_crm_user"},
        {"id": "owner-ib", "source": "account:ib-owner", "target": "ib_user:23840", "type": "ib_identity"},
        {"id": "ib-person", "source": "ib_user:23840", "target": "account:rebate-person", "type": "ib_direct_rebate"},
    ]

    payload = propagate_scores(entities, relationships, threshold=20)

    owner = _node(payload, "account:ib-owner")
    ib = _node(payload, "ib_user:23840")
    rebate_person = _node(payload, "account:rebate-person")
    assert ib["score"] == owner["score"]
    assert rebate_person["score"] >= 20
    assert rebate_person["expandable"] is True
