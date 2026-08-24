from __future__ import annotations

from kdesk.application.relationship_inspection import RelationshipInspectionService


def snapshot() -> dict:
    return {
        "subjectId": "account:100|MT5|AC CN MT5",
        "filters": {"platform": "MT5", "server": "AC CN MT5"},
        "entities": [
            {"id": "account:100|MT5|AC CN MT5", "type": "account", "label": "100", "isSubject": True, "databaseStatus": "TA", "score": 100},
            {"id": "account:101|MT5|AC CN MT5", "type": "account", "label": "101", "databaseStatus": "P", "score": 82, "depth": 1},
            {"id": "account:102|MT5|AC CN MT5", "type": "account", "label": "102", "databaseStatus": "", "score": 64, "depth": 2},
        ],
        "relationships": [
            {"id": "crm-1", "source": "account:100|MT5|AC CN MT5", "target": "account:101|MT5|AC CN MT5", "type": "same_crm_user", "evidenceKey": "crm:9", "evidence": ["user_id=9", "CRM mt_users_account"]},
            {"id": "crm-duplicate", "source": "account:101|MT5|AC CN MT5", "target": "account:100|MT5|AC CN MT5", "type": "same_crm_user", "evidenceKey": "crm:9"},
            {"id": "copy-1", "source": "account:100|MT5|AC CN MT5", "target": "account:101|MT5|AC CN MT5", "type": "copy_order", "evidenceKey": "copy:1", "metrics": {"matchedOrders": 8}},
            {"id": "sync-1", "source": "account:101|MT5|AC CN MT5", "target": "account:102|MT5|AC CN MT5", "type": "trade_open_close_sync", "evidenceKey": "sync:1", "metrics": {"matchedOrders": 6, "openDeltaSeconds": 2}},
            {"id": "lock-1", "source": "account:101|MT5|AC CN MT5", "target": "account:102|MT5|AC CN MT5", "type": "suspected_hedge", "evidenceKey": "lock:1", "metrics": {"matchedOrders": 3, "volumeSimilarity": .95}},
        ],
        "coverage": [], "limitations": [], "inProgress": False, "revision": 2,
    }


def test_status_is_preserved_and_only_empty_falls_back_to_b() -> None:
    service = RelationshipInspectionService()
    root = service.build_node_profile("100", "account:100|MT5|AC CN MT5", snapshot(), {}, {})
    empty = service.build_node_profile("100", "account:102|MT5|AC CN MT5", snapshot(), {}, {})
    assert root["account"]["database_status"] == "TA"
    assert empty["account"]["database_status"] == "B"


def test_same_crm_is_named_same_name_and_hides_internal_fields() -> None:
    detail = RelationshipInspectionService().build_relation_detail("crm-1", snapshot())
    encoded = repr(detail).lower()
    assert detail["relations"][0]["business_name"] == "同名账户"
    assert "user_id" not in encoded
    assert "mt_users_account" not in encoded


def test_copy_sync_and_hedge_are_separate_and_same_type_is_deduped() -> None:
    bundles = RelationshipInspectionService().build_relation_bundles(snapshot())
    first = next(item for item in bundles if set(item["endpoints"]) == {"account:100|MT5|AC CN MT5", "account:101|MT5|AC CN MT5"})
    second = next(item for item in bundles if set(item["endpoints"]) == {"account:101|MT5|AC CN MT5", "account:102|MT5|AC CN MT5"})
    assert {item["type"] for item in first["relations"]} == {"same_crm_user", "copy_order"}
    assert len([item for item in first["relations"] if item["type"] == "same_crm_user"]) == 1
    assert {item["type"] for item in second["relations"]} == {"trade_open_close_sync", "suspected_hedge"}


def test_relation_direction_and_metrics_are_business_facing() -> None:
    detail = RelationshipInspectionService().build_relation_detail("copy-1", snapshot())
    copy = next(item for item in detail["relations"] if item["type"] == "copy_order")
    assert copy["direction"] == "100 → 101"
    assert copy["metrics"] == {"匹配订单数": 8}
    assert "account:" not in copy["direction"]


def test_same_relation_type_with_multiple_evidence_keys_is_one_detail_section() -> None:
    data = snapshot()
    data["relationships"].append({
        "id": "crm-second-evidence",
        "source": "account:100|MT5|AC CN MT5",
        "target": "account:101|MT5|AC CN MT5",
        "type": "same_crm_user",
        "evidenceKey": "crm:secondary-route",
        "metrics": {"server": "AC CN MT5"},
    })
    detail = RelationshipInspectionService().build_relation_detail("crm-second-evidence", data)
    crm_sections = [item for item in detail["relations"] if item["type"] == "same_crm_user"]
    assert len(crm_sections) == 1
    assert detail["relation_count"] == 2


def test_recommendations_are_bounded_and_have_complete_root_path() -> None:
    profile = RelationshipInspectionService().build_node_profile("100", "account:101|MT5|AC CN MT5", snapshot(), {}, {})
    assert 0 < len(profile["recommendations"]) <= 8
    assert all(item["path"][0] == snapshot()["subjectId"] for item in profile["recommendations"])
    assert all(item["path"][-1] == item["node_id"] for item in profile["recommendations"])


def test_small_behavior_sample_does_not_force_a_tag() -> None:
    profile = RelationshipInspectionService().build_node_profile(
        "100", snapshot()["subjectId"], snapshot(),
        {"tradeBehavior": {"closedOrders": 2, "shortCloseOrders": 2}}, {},
    )
    assert "短平" not in {item["name"] for item in profile["tags"]}
    assert profile["metrics"]["behavior_status"] == "insufficient"


def test_profile_metrics_are_business_facing_and_hide_internal_fields() -> None:
    profile = RelationshipInspectionService().build_node_profile(
        "100",
        snapshot()["subjectId"],
        snapshot(),
        {
            "tradeBehavior": {
                "closedOrders": 12,
                "shortCloseOrders": 8,
                "user_id": 9,
                "sourceTable": "mt_users_account",
            }
        },
        {
            "ea": {
                "detected": True,
                "matchedOrders": 7,
                "comment": "ATM_DualAI",
                "user_id": 9,
            }
        },
    )
    encoded = repr(profile).lower()
    assert "user_id" not in encoded
    assert "mt_users_account" not in encoded
    assert profile["metrics"]["behavior"]["已平仓订单数"] == 12
    ea = next(item for item in profile["tags"] if item["name"] == "EA")
    assert ea["metrics"] == {"匹配订单数": 7, "Comment 归一结果": "ATM_DualAI"}
