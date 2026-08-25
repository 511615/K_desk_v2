from kdesk.domain.relationship_graph import build_presentation_graph


def test_presentation_graph_collapses_repeated_account_edges_into_relation_group() -> None:
    entities = [
        {"id": "a:root", "type": "account", "label": "root", "isSubject": True, "databaseStatus": "TA"},
        {"id": "a:1", "type": "account", "label": "1", "databaseStatus": "P"},
        {"id": "a:2", "type": "account", "label": "2"},
    ]
    relationships = [
        {"id": "e1", "source": "a:root", "target": "a:1", "type": "same_crm_user", "label": "同 CRM", "evidence": ["user 9"]},
        {"id": "e2", "source": "a:root", "target": "a:2", "type": "same_crm_user", "label": "同 CRM", "evidence": ["user 9"]},
    ]
    result = build_presentation_graph(entities, relationships, subject_id="a:root")
    groups = [item for item in result["entities"] if item["type"] == "relation_group"]
    assert len(groups) == 1
    assert groups[0]["memberCount"] == 3
    assert any(edge["target"] == groups[0]["id"] for edge in result["relationships"])
    assert not any(edge["source"] == "a:root" and edge["target"] == "a:1" for edge in result["relationships"])
    root_group_edges = [
        edge
        for edge in result["relationships"]
        if {edge["source"], edge["target"]} == {"a:root", groups[0]["id"]}
    ]
    assert len(root_group_edges) == 1
    assert next(item for item in result["entities"] if item["id"] == "a:root")["databaseStatus"] == "TA"
    assert next(item for item in result["entities"] if item["id"] == "a:1")["databaseStatus"] == "P"


def test_presentation_graph_scopes_same_name_components_to_their_own_relation_family() -> None:
    entities = [
        {"id": "a:234889", "type": "account", "label": "234889", "isSubject": True},
        {"id": "a:216065", "type": "account", "label": "216065"},
        {"id": "a:241636", "type": "account", "label": "241636"},
        {"id": "a:ip-peer", "type": "account", "label": "ip-peer"},
        {"id": "a:other-root", "type": "account", "label": "other-root"},
        {"id": "a:other-peer", "type": "account", "label": "other-peer"},
    ]
    relationships = [
        {"id": "same-name-1", "source": "a:234889", "target": "a:216065", "type": "same_crm_user", "label": "同名账户", "evidence": []},
        {"id": "same-name-2", "source": "a:234889", "target": "a:241636", "type": "same_crm_user", "label": "同名账户", "evidence": []},
        {"id": "last-ip", "source": "a:234889", "target": "a:ip-peer", "type": "login_ip", "label": "同 LastIP", "evidence": []},
        {"id": "other-name", "source": "a:other-root", "target": "a:other-peer", "type": "same_crm_user", "label": "同名账户", "evidence": []},
    ]

    result = build_presentation_graph(entities, relationships, subject_id="a:234889")

    groups = [(item["relationType"], item["memberCount"]) for item in result["entities"] if item["type"] == "relation_group"]
    assert sorted(groups) == [("same_crm_user", 2), ("same_crm_user", 3)]
    assert any(edge["id"] == "last-ip" for edge in result["relationships"])


def test_presentation_graph_keeps_non_crm_account_relations_as_direct_lines() -> None:
    entities = [
        {"id": "a:root", "type": "account", "label": "root", "isSubject": True},
        {"id": "a:crm", "type": "account", "label": "crm"},
        {"id": "a:ip", "type": "account", "label": "ip"},
        {"id": "a:copy", "type": "account", "label": "copy"},
    ]
    relationships = [
        {"id": "crm", "source": "a:root", "target": "a:crm", "type": "same_crm_user", "label": "同 CRM"},
        {"id": "ip", "source": "a:root", "target": "a:ip", "type": "login_ip", "label": "同 LastIP"},
        {"id": "copy", "source": "a:root", "target": "a:copy", "type": "copy_order", "label": "跟单"},
    ]

    result = build_presentation_graph(entities, relationships, subject_id="a:root")

    groups = [item for item in result["entities"] if item["type"] == "relation_group"]
    assert [group["relationType"] for group in groups] == ["same_crm_user"]
    assert {edge["id"] for edge in result["relationships"]} >= {"ip", "copy"}


def test_presentation_graph_retains_existing_evidence_entity_and_limits_members() -> None:
    entities = [
        {"id": "a:root", "type": "account", "label": "root", "isSubject": True},
        {"id": "ip:1", "type": "ip", "label": "1.2.3.4"},
        {"id": "a:1", "type": "account", "label": "1"},
    ]
    relationships = [
        {"id": "e1", "source": "a:root", "target": "ip:1", "type": "login_ip", "label": "同 LastIP", "evidence": ["IP"]},
        {"id": "e2", "source": "ip:1", "target": "a:1", "type": "login_ip", "label": "同 LastIP", "evidence": ["IP"]},
    ]
    result = build_presentation_graph(entities, relationships, subject_id="a:root", max_members_per_group=1)
    assert any(edge["target"] == "ip:1" for edge in result["relationships"])
    assert any(entity["id"] == "ip:1" for entity in result["entities"])


def test_presentation_graph_reuses_explicit_ip_entity_for_shared_ip_pair() -> None:
    entities = [
        {"id": "a:root", "type": "account", "label": "root", "isSubject": True},
        {"id": "ip:1", "type": "ip", "label": "39.70.117.108"},
        {"id": "a:1", "type": "account", "label": "1"},
    ]
    relationships = [
        {"id": "ip-root", "source": "a:root", "target": "ip:1", "type": "login_ip", "label": "登录 IP 观察", "evidence": ["LastIP：39.70.117.108"]},
        {"id": "ip-peer", "source": "a:root", "target": "a:1", "type": "login_ip", "label": "同当前 LastIP", "evidence": ["LastIP：39.70.117.108"]},
    ]
    result = build_presentation_graph(entities, relationships, subject_id="a:root")
    assert not any(item["type"] == "relation_group" for item in result["entities"])
    assert any(edge["source"] == "ip:1" and edge["target"] == "a:1" for edge in result["relationships"])
