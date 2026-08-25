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


def test_relation_display_keeps_account_to_account_edge_in_single_mode() -> None:
    data = snapshot()
    data["relationships"][2].update({
        "display_group_key": "copy_order|account:100|outbound|MT5|AC CN MT5",
        "display_anchor_id": "account:100|MT5|AC CN MT5",
        "metrics": {"matchedOrders": 8, "orders": 8, "netProfit": 12.5, "currency": "USD"},
    })

    display = RelationshipInspectionService().build_relation_display("copy-1", data)

    assert display["mode"] == "single"
    assert display["summary_metrics"] == []
    assert display["single_metrics"]
    assert display["member_page"]["items"] == []
    assert display["group_actions"][0]["scope"] == "group"


def test_relation_display_ib_group_uses_materialised_members_and_explicit_coverage() -> None:
    data = {
        "revision": 8,
        "filters": {"platform": "MT5", "server": "AC CN MT5"},
        "entities": [
            {"id": "account:100", "type": "account", "label": "100", "isSubject": True},
            {"id": "ib_user:109094", "type": "ib_user", "label": "IB 109094"},
            {"id": "account:234889", "type": "account", "label": "234889", "databaseStatus": "P"},
            {"id": "account:234890", "type": "account", "label": "234890", "databaseStatus": "B"},
        ],
        "relationships": [
            {
                "id": "ib-1", "source": "ib_user:109094", "target": "account:234889", "type": "ib_direct_rebate",
                "display_group_key": "ib_direct_rebate|ib_user:109094|outbound|MT5|AC CN MT5",
                "display_anchor_id": "ib_user:109094", "display_member_count": 27,
                "metrics": {
                    "tradeProfit": 54234.12, "rebateAmount": 777.87, "combinedProfit": 55011.99,
                    "rebateShare": 0.014, "rebateOrderCount": 698, "lastRebateAt": "2026-08-21 12:40:00",
                    "currency": "USD", "inclusionReasons": ["返佣主导盈利"],
                },
            },
            {
                "id": "ib-2", "source": "ib_user:109094", "target": "account:234890", "type": "ib_direct_rebate",
                "display_group_key": "ib_direct_rebate|ib_user:109094|outbound|MT5|AC CN MT5",
                "display_anchor_id": "ib_user:109094", "display_member_count": 27,
                "metrics": {
                    "tradeProfit": 57152.20, "rebateAmount": 693.77, "combinedProfit": 57845.97,
                    "rebateShare": 0.012, "rebateOrderCount": 627, "lastRebateAt": "2026-08-21 12:40:02",
                    "currency": "USD", "inclusionReasons": ["数据库状态 P"],
                },
            },
        ],
        "coverage": [], "limitations": [], "inProgress": False,
    }

    display = RelationshipInspectionService().build_relation_display("ib-1", data, scope="group")

    assert display["mode"] == "group"
    assert display["coverage"] == {
        "known_members": 27,
        "included_members": 2,
        "statistic_members": 2,
        "omitted_members": 25,
        "status": "partial",
        "reason": "统计仅基于当前筛选范围内有完整证据的账户",
    }
    assert display["member_page"]["total"] == 2
    assert {item["account"]["login"] for item in display["member_page"]["items"]} == {"234889", "234890"}
    metrics = {item["id"]: item["value"] for item in display["summary_metrics"]}
    assert metrics["rebateAmount_USD"] == 1471.64
    assert metrics["rebateShare"] == 0.01304


def test_relation_display_group_scope_deduplicates_connected_same_ip_members() -> None:
    data = snapshot()
    data["relationships"] = [
        {"id": "ip-1", "source": "account:100|MT5|AC CN MT5", "target": "account:101|MT5|AC CN MT5", "type": "login_ip", "metrics": {"closedOrders": 4, "netProfit": 5, "currency": "USD"}},
        {"id": "ip-2", "source": "account:101|MT5|AC CN MT5", "target": "account:102|MT5|AC CN MT5", "type": "login_ip", "metrics": {"closedOrders": 6, "netProfit": -3, "currency": "USD"}},
    ]

    display = RelationshipInspectionService().build_relation_display("ip-1", data, scope="group", member_limit=1)

    assert display["mode"] == "group"
    assert display["coverage"]["included_members"] == 3
    assert display["member_page"] == {"page": 1, "limit": 1, "total": 3, "items": display["member_page"]["items"]}
    assert len(display["member_page"]["items"]) == 1


def test_relation_display_group_splits_currency_and_weights_holding_duration() -> None:
    data = snapshot()
    data["relationships"] = [
        {
            "id": "ip-1", "source": "account:100|MT5|AC CN MT5", "target": "account:101|MT5|AC CN MT5",
            "type": "login_ip", "metrics": {
                "netProfit": 10, "currency": "USD", "holdingSecondsTotal": 600, "holdingOrderCount": 2,
            },
        },
        {
            "id": "ip-2", "source": "account:101|MT5|AC CN MT5", "target": "account:102|MT5|AC CN MT5",
            "type": "login_ip", "metrics": {
                "netProfit": 20, "currency": "USC", "holdingSecondsTotal": 300, "holdingOrderCount": 1,
            },
        },
    ]

    display = RelationshipInspectionService().build_relation_display("ip-1", data, scope="group")

    metrics = {item["id"]: item["value"] for item in display["summary_metrics"]}
    assert metrics["netProfit_USD"] == 10
    assert metrics["netProfit_USC"] == 20
    assert "netProfit" not in metrics
    assert metrics["averageHoldingSeconds"] == 300


def test_relation_display_group_scope_safely_downgrades_when_only_one_member_exists() -> None:
    data = snapshot()
    data["entities"].append({"id": "ib_user:1", "type": "ib_user", "label": "IB 1"})
    data["relationships"] = [{
        "id": "identity", "source": "account:100|MT5|AC CN MT5", "target": "ib_user:1", "type": "ib_identity",
    }]

    display = RelationshipInspectionService().build_relation_display("identity", data, scope="group")

    assert display["mode"] == "single"
    assert display["member_page"]["total"] == 0
