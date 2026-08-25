import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app
import ea_comment_group


class SourceNotesTests(unittest.TestCase):
    def test_mt5_extended_volume_uses_the_exported_one_hundred_million_lot_scale(self):
        self.assertEqual(app.normalize_mt5_volume_ext(5_000_000), 0.05)

    def test_missing_optional_source_notes_returns_empty_text(self):
        missing_path = Path(tempfile.gettempdir()) / "kdesk-missing-source-notes.txt"
        if missing_path.exists():
            missing_path.unlink()

        with patch.object(app, "SOURCE_TXT", missing_path):
            self.assertEqual(app.read_source_text(), "")


class SourceRoutingCompatibilityTests(unittest.TestCase):
    def test_copy_pool_logical_server_aliases_select_account_detail_sources(self):
        expected = {
            "DBG CN MT4 Live1": "DBG MT4 CN1",
            "DBG CN MT4 Live2": "DBG MT4 CN2",
            "DBG VN MT4 Live3": "DBG MT4 VN3",
            "AC CN MT5 Live3": "AC CN MT5 live3",
        }

        for alias, canonical in expected.items():
            source = next(item for item in app.MYSQL_SOURCES if item["server"] == canonical)
            self.assertTrue(
                app.source_allowed(source, platform=source["platform"], server=alias),
                alias,
            )


class HierarchyNetDepositTests(unittest.TestCase):
    def test_query_validation_accepts_product_prefix_and_rejects_oversized_range(self):
        parsed = app.hierarchy_net_deposit.parse_query(
            "account:631395", "2026-05-01T00:00", "2026-06-30T23:59", "xauusd"
        )
        self.assertEqual(parsed["product"], "XAUUSD")
        self.assertEqual(parsed["start"].strftime("%Y-%m-%d %H:%M"), "2026-05-01 00:00")
        promotion = app.hierarchy_net_deposit.parse_query(
            "gb:126261", "2026-05-01", "2026-06-30", "@PROMOTION"
        )
        self.assertEqual(promotion["product"], "@PROMOTION")
        activity = app.hierarchy_net_deposit.parse_query(
            "gb:126261", "2026-05-01", "2026-06-30", "BTCUSD", True
        )
        self.assertTrue(activity["activityRules"])
        self.assertEqual(activity["product"], "@PROMOTION")
        with self.assertRaisesRegex(ValueError, "不能超过"):
            app.hierarchy_net_deposit.parse_query(
                "631395", "2025-01-01", "2026-07-01", ""
            )

    def test_promotion_product_filter_includes_forex_and_metals_only(self):
        self.assertTrue(app.hierarchy_net_deposit.is_promotion_product("XAUUSD"))
        self.assertTrue(app.hierarchy_net_deposit.is_promotion_product("EURUSD.ECN"))
        self.assertTrue(app.hierarchy_net_deposit.is_promotion_product("GOLDmicro"))
        self.assertFalse(app.hierarchy_net_deposit.is_promotion_product("BTCUSD"))
        self.assertFalse(app.hierarchy_net_deposit.is_promotion_product("USOILRoll"))

    def test_hierarchy_routes_dbg_live2_by_crm_schema_and_server_code(self):
        source = app.hierarchy_net_deposit._source_for_account(
            app.MYSQL_SOURCES, "crm_vn", "5"
        )

        self.assertEqual(source["name"], "DBG MT5 Live2")
        self.assertEqual(source["schema"], "crm_vn_mt5_live2")
        self.assertEqual(
            app.hierarchy_net_deposit._source_for_account(
                app.MYSQL_SOURCES, "crm_vn", "2"
            )["schema"],
            "mt5_export_new",
        )
        self.assertIsNone(
            app.hierarchy_net_deposit._source_for_account(
                app.MYSQL_SOURCES, "crm_vn", "999"
            )
        )

    def test_hierarchy_target_prefixes_cover_both_dbg_crm_environments(self):
        self.assertEqual(
            app.hierarchy_net_deposit._target_mode("dbg-cn:100"),
            ("user", "100", "crm_cn"),
        )
        self.assertEqual(
            app.hierarchy_net_deposit._target_mode("dbg-vn:200"),
            ("user", "200", "crm_vn"),
        )

    def test_hierarchy_account_lookup_uses_all_configured_codes_for_crm(self):
        sources = [
            {
                "name": "DBG GB MT5", "host": "dbg", "schema": "mt5_export_new",
                "table": "mt5_deals", "kind": "mt5_deals",
                "account_route": {"schema": "crm_vn", "mt_server_code": "2"},
            },
            {
                "name": "DBG MT5 Live2", "host": "dbg", "schema": "crm_vn_mt5_live2",
                "table": "mt5_deals", "kind": "mt5_deals",
                "account_route": {"schema": "crm_vn", "mt_server_code": "5"},
            },
        ]
        cursor = MagicMock()
        cursor.fetchall.return_value = [{
            "id": 88, "supper_id": 1, "top_ib_id": 1, "user_type": 2,
            "customer_type": "VN", "ib_level": None, "status": 0,
            "full_name": "Live2 User", "matched_account": 5200101,
        }]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection

        subject = app.hierarchy_net_deposit.resolve_subject(
            "account:5200101", sources, connect
        )

        sql, parameters = cursor.execute.call_args.args
        self.assertIn("a.mt_server_code in (%s,%s)", " ".join(sql.split()))
        self.assertEqual(parameters, [5200101, "2", "5"])
        self.assertEqual(subject["schema"], "crm_vn")

    def test_hierarchy_tree_account_query_includes_live2_code(self):
        sources = [
            {
                "name": "DBG GB MT5", "host": "dbg", "schema": "mt5_export_new",
                "table": "mt5_deals", "kind": "mt5_deals",
                "account_route": {"schema": "crm_vn", "mt_server_code": "2"},
            },
            {
                "name": "DBG MT5 Live2", "host": "dbg", "schema": "crm_vn_mt5_live2",
                "table": "mt5_deals", "kind": "mt5_deals",
                "account_route": {"schema": "crm_vn", "mt_server_code": "5"},
            },
        ]
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "id": 88, "supper_id": None, "top_ib_id": 88, "user_type": 2,
            "customer_type": "VN", "ib_level": None, "status": 0,
            "full_name": "Live2 User",
        }
        cursor.fetchall.side_effect = [[], [{
            "user_id": 88, "mt_login": 5200101, "mt_server_code": "5",
            "mt_type_name": "Standard", "status": 0,
        }]]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection

        _, accounts = app.hierarchy_net_deposit._fetch_tree_and_accounts(
            {"schema": "crm_vn", "source": sources[0], "userId": 88},
            sources,
            connect,
        )

        sql, parameters = cursor.execute.call_args.args
        self.assertIn("mt_server_code in (%s,%s)", " ".join(sql.split()))
        self.assertEqual(parameters, [88, "2", "5"])
        self.assertEqual(accounts[0]["mt_login"], 5200101)

    def test_hierarchy_product_list_scans_live2_and_deduplicates_physical_sources(self):
        sources = [
            {
                "name": "DBG CN MT5", "host": "dbg", "schema": "mt5_export_new",
                "table": "mt5_deals", "kind": "mt5_deals",
                "account_route": {"schema": "crm_cn", "mt_server_code": "4"},
            },
            {
                "name": "DBG GB MT5", "host": "dbg", "schema": "mt5_export_new",
                "table": "mt5_deals", "kind": "mt5_deals",
                "account_route": {"schema": "crm_vn", "mt_server_code": "2"},
            },
            {
                "name": "DBG MT5 Live2", "host": "dbg", "schema": "crm_vn_mt5_live2",
                "table": "mt5_deals", "kind": "mt5_deals",
                "account_route": {"schema": "crm_vn", "mt_server_code": "5"},
            },
        ]
        queried = []

        def connect(source):
            queried.append(source["schema"])
            cursor = MagicMock()
            cursor.fetchall.return_value = [{
                "Product": "LIVE2ONLY" if source["schema"] == "crm_vn_mt5_live2" else "XAUUSD"
            }]
            connection = MagicMock()
            connection.cursor.return_value.__enter__.return_value = cursor
            context = MagicMock()
            context.__enter__.return_value = connection
            return context

        payload = app.hierarchy_net_deposit.list_products(sources, connect)

        self.assertEqual(queried.count("mt5_export_new"), 1)
        self.assertEqual(queried.count("crm_vn_mt5_live2"), 1)
        self.assertIn("LIVE2ONLY", payload["products"])

    def test_home_ui_shows_orders_and_lots_as_separate_metrics(self):
        self.assertIn("`${product}订单数`", app.WORKBENCH_HTML)
        self.assertIn("`${product}总手数`", app.WORKBENCH_HTML)
        self.assertIn("`${fmt(s.lots)} 手`", app.WORKBENCH_HTML)
        self.assertNotIn("`${product}订单 / 手数`", app.WORKBENCH_HTML)
        self.assertIn('id="hierarchyActivityRules"', app.WORKBENCH_HTML)
        self.assertIn("活动归属逐级核验", app.WORKBENCH_HTML)

    def test_activity_rules_use_bottom_tier_priority_without_double_counting(self):
        users = [
            {"userId": 10, "parentUserId": None, "depth": 0, "name": "Root", "role": "referral", "roleLabel": "Referral", "ibLevel": 1, "customerType": "VN"},
            {"userId": 11, "parentUserId": 10, "depth": 1, "name": "Child IB", "role": "referral", "roleLabel": "Referral", "ibLevel": 2, "customerType": "VN"},
            {"userId": 12, "parentUserId": 10, "depth": 1, "name": "Direct Client", "role": "customer", "roleLabel": "普通客户", "ibLevel": None, "customerType": "VN"},
            {"userId": 13, "parentUserId": 11, "depth": 2, "name": "Qualified Client", "role": "customer", "roleLabel": "普通客户", "ibLevel": None, "customerType": "VN"},
            {"userId": 14, "parentUserId": 11, "depth": 2, "name": "Rolled Client", "role": "customer", "roleLabel": "普通客户", "ibLevel": None, "customerType": "VN"},
        ]
        def account(user_id, login, net_deposit, lots):
            return {
                "userId": user_id, "account": login, "isCent": False, "role": "customer",
                "deposit": net_deposit, "withdrawal": 0, "netDeposit": net_deposit,
                "depositCount": 1, "withdrawalCount": 0, "orders": 1, "lots": lots,
                "tradingProfit": 0, "symbols": ["EURUSD"],
            }
        account_rows = [account(12, 10012, 30000, 300), account(13, 10013, 70000, 700), account(14, 10014, 40000, 400)]
        rules = app.hierarchy_net_deposit._promotion_rules_payload(
            {"userId": 10, "role": "referral"}, users, account_rows
        )
        decisions = {row["userId"]: row for row in rules["decisions"]}
        self.assertTrue(rules["subjectQualified"])
        self.assertEqual(rules["includedCustomerIds"], [12, 14])
        self.assertEqual(rules["summary"]["netDeposit"], 70000)
        self.assertEqual(rules["summary"]["lots"], 700)
        self.assertTrue(decisions[13]["qualified"])
        self.assertFalse(decisions[11]["qualified"])
        self.assertEqual(decisions[11]["rollsToUserId"], 10)

    def test_activity_rules_count_child_referral_own_trading_only_for_parent(self):
        users = [
            {"userId": 10, "parentUserId": None, "depth": 0, "name": "Root", "role": "referral", "roleLabel": "Referral", "ibLevel": 1, "customerType": "VN"},
            {"userId": 11, "parentUserId": 10, "depth": 1, "name": "Child IB", "role": "referral", "roleLabel": "Referral", "ibLevel": 2, "customerType": "VN"},
            {"userId": 12, "parentUserId": 11, "depth": 2, "name": "Grandchild A", "role": "customer", "roleLabel": "普通客户", "ibLevel": None, "customerType": "VN"},
            {"userId": 13, "parentUserId": 11, "depth": 2, "name": "Grandchild B", "role": "customer", "roleLabel": "普通客户", "ibLevel": None, "customerType": "VN"},
        ]
        accounts = [
            {"userId": 11, "account": 10011, "isCent": False, "role": "referral", "deposit": 65000, "withdrawal": 0, "netDeposit": 65000, "depositCount": 1, "withdrawalCount": 0, "orders": 1, "lots": 650, "tradingProfit": 0, "symbols": ["EURUSD"]},
            {"userId": 12, "account": 10012, "isCent": False, "role": "customer", "deposit": 35000, "withdrawal": 0, "netDeposit": 35000, "depositCount": 1, "withdrawalCount": 0, "orders": 1, "lots": 350, "tradingProfit": 0, "symbols": ["EURUSD"]},
            {"userId": 13, "account": 10013, "isCent": False, "role": "customer", "deposit": 35000, "withdrawal": 0, "netDeposit": 35000, "depositCount": 1, "withdrawalCount": 0, "orders": 1, "lots": 350, "tradingProfit": 0, "symbols": ["EURUSD"]},
        ]
        rules = app.hierarchy_net_deposit._promotion_rules_payload(
            {"userId": 10, "role": "referral"}, users, accounts
        )
        decisions = {row["userId"]: row for row in rules["decisions"]}
        self.assertTrue(decisions[11]["qualified"])
        self.assertTrue(rules["subjectQualified"])
        self.assertEqual(rules["includedUserIds"], [11])
        self.assertEqual(rules["summary"]["netDeposit"], 65000)
        self.assertEqual(rules["summary"]["lots"], 650)
        self.assertFalse(accounts[1]["activityIncluded"])
        self.assertFalse(accounts[2]["activityIncluded"])

    def test_payload_sums_target_and_descendant_accounts_with_cent_values_in_usd(self):
        subject = {
            "schema": "int_sass_crm_ac",
            "source": {"name": "CRM"},
            "userId": 10,
            "parentUserId": None,
            "topIbId": 10,
            "userType": 1,
            "role": "referral",
            "roleLabel": "Referral",
            "name": "Referral A",
            "customerType": "VN",
            "ibLevel": 1,
            "status": 0,
            "matchedBy": "account",
            "matchedAccount": 900001,
        }
        users = {
            10: {
                "id": 10, "supper_id": None, "user_type": 1, "depth": 0,
                "full_name": "Referral A", "ib_level": 1,
            },
            11: {
                "id": 11, "supper_id": 10, "user_type": 2, "depth": 1,
                "full_name": "Client B", "ib_level": None,
            },
        }
        accounts = [
            {"user_id": 10, "mt_login": 900001, "mt_server_code": "1", "mt_type_name": "Standard", "status": 0},
            {"user_id": 11, "mt_login": 900002, "mt_server_code": "1", "mt_type_name": "Cent", "status": 0},
        ]
        metrics = {
            ("int_sass_crm_ac", "1", 900001): {
                "deposit": 100, "withdrawal": 20, "netDeposit": 80,
                "depositCount": 1, "withdrawalCount": 1, "orders": 2,
                "lots": 1.5, "tradingProfit": 10, "symbols": ["XAUUSD"],
            },
            ("int_sass_crm_ac", "1", 900002): {
                "deposit": 50, "withdrawal": 30, "netDeposit": 20,
                "depositCount": 1, "withdrawalCount": 1, "orders": 3,
                "lots": 2.5, "tradingProfit": -4, "symbols": ["XAUUSD.C"],
            },
        }
        with patch.object(app.hierarchy_net_deposit, "resolve_subject", return_value=subject), \
             patch.object(app.hierarchy_net_deposit, "_fetch_tree_and_accounts", return_value=(users, accounts)), \
             patch.object(app.hierarchy_net_deposit, "_collect_metrics", return_value=metrics):
            payload = app.hierarchy_net_deposit.build_payload(
                "900001", "2026-05-01", "2026-05-31", "XAUUSD",
                sources=[{
                    "name": "AC GB MT5", "crm_schema": "int_sass_crm_ac",
                    "mt_server_code": "1", "kind": "mt5_deals",
                    "platform": "MT5", "server": "AC GB MT5",
                }],
                connect=MagicMock(),
                classify_mt5_cashflows=MagicMock(),
                classify_mt4_cashflows=MagicMock(),
                refreshed_at="2026-07-14 15:00:00",
            )

        self.assertEqual(payload["summary"]["users"], 2)
        self.assertEqual(payload["summary"]["accounts"], 2)
        self.assertEqual(payload["summary"]["netDeposit"], 100)
        self.assertEqual(payload["summary"]["standardNetDeposit"], 80)
        self.assertEqual(payload["summary"]["centNetDeposit"], 20)
        self.assertEqual(payload["summary"]["orders"], 5)
        self.assertEqual(payload["summary"]["lots"], 4)
        self.assertEqual(payload["users"][1]["netDeposit"], 20)
        self.assertTrue(payload["accounts"][1]["isCent"])


class MoneyScalingTests(unittest.TestCase):
    def test_ac_mt5_sources_cover_gb_cn_and_cn_live3(self):
        sources = {source["name"]: source["schema"] for source in app.MYSQL_SOURCES}
        self.assertEqual(sources["AC GB MT5"], "int_sass_crm_ac_mt5_live_new")
        self.assertEqual(sources["AC CN MT5"], "sass_crm_ac_mt5_live")
        self.assertEqual(sources["AC CN MT5 live3"], "sass_crm_ac_mt5_live3")
        live3 = next(source for source in app.MYSQL_SOURCES if source["name"] == "AC CN MT5 live3")
        self.assertEqual(app.source_crm_routes(live3), [
            {"schema": "sass_crm_ac", "mt_server_code": "3"},
        ])

    def test_dbg_mt5_live2_uses_its_own_code_five_route(self):
        sources = {source["name"]: source for source in app.MYSQL_SOURCES}
        live2 = sources["DBG MT5 Live2"]

        self.assertEqual(live2["schema"], "crm_vn_mt5_live2")
        self.assertEqual(live2["server"], "DBG MT5 Live2")
        self.assertEqual(live2["aliases"], ["DBG MT5", "DBG GB MT5 Live2"])
        self.assertEqual(app.source_crm_routes(live2), [
            {"schema": "crm_vn", "mt_server_code": "5"},
        ])
        self.assertIs(app.source_for_crm_route("crm_vn", "5"), live2)
        self.assertEqual(app.source_for_crm_route("crm_vn", "2")["schema"], "mt5_export_new")

    def test_rebate_routes_are_isolated_for_shared_trade_schemas(self):
        sources = {source["name"]: source for source in app.MYSQL_SOURCES}
        self.assertEqual(app.source_crm_routes(sources["AC MT4"]), [
            {"schema": "sass_crm_ac", "mt_server_code": "2"},
        ])
        self.assertEqual(app.source_crm_routes(sources["AC GB MT4"]), [
            {"schema": "int_sass_crm_ac", "mt_server_code": "2"},
        ])
        self.assertEqual(app.source_crm_routes(sources["DBG MT5"]), [
            {"schema": "crm_cn", "mt_server_code": "4"},
        ])
        self.assertEqual(app.source_crm_routes(sources["DBG GB MT5"]), [
            {"schema": "crm_vn", "mt_server_code": "2"},
        ])
        self.assertEqual(app.source_crm_routes(sources["DBG MT4 CN2"]), [
            {"schema": "crm_cn", "mt_server_code": "3"},
        ])

    def test_account_rebate_sums_all_configured_crm_routes(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"RebateRows": 3, "RebateAmount": "12.50"},
            {"RebateRows": 2, "RebateAmount": "7.25"},
        ]
        rows, amount = app.query_account_rebate(cursor, {
            "crm_routes": [
                {"schema": "crm_cn", "mt_server_code": "4"},
                {"schema": "crm_vn", "mt_server_code": "2"},
            ],
        }, "2012060")

        self.assertEqual(rows, 5)
        self.assertEqual(amount, 19.75)
        self.assertIn("`crm_cn`.`rebate_task_detail`", cursor.execute.call_args_list[0].args[0])
        self.assertIn("`crm_vn`.`rebate_task_detail`", cursor.execute.call_args_list[1].args[0])

    def test_source_account_route_rejects_wrong_crm_server(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        source = {"account_route": {"schema": "crm_cn", "mt_server_code": "4"}}

        self.assertFalse(app.source_account_exists(cursor, source, "10002"))
        sql, args = cursor.execute.call_args.args
        self.assertIn("`crm_cn`.`mt_users_account`", sql)
        self.assertEqual(args, (10002, "4"))

    def test_route_missing_uses_unique_physical_trade_user_fallback(self):
        source = {
            "name": "DBG MT5", "host": "dbg", "schema": "mt5_export_new",
            "table": "mt5_deals", "kind": "mt5_deals", "platform": "MT5",
            "server": "DBG CN MT5",
            "account_route": {"schema": "crm_cn", "mt_server_code": "4"},
        }
        other = {
            "name": "DBG MT5 Live2", "host": "dbg", "schema": "crm_vn_mt5_live2",
            "table": "mt5_deals", "kind": "mt5_deals", "platform": "MT5",
            "server": "DBG MT5 Live2",
            "account_route": {"schema": "crm_vn", "mt_server_code": "5"},
        }
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, {"Login": 309361}, None]

        with patch.object(app, "MYSQL_SOURCES", [source, other]):
            status = app.source_account_route_status(cursor, source, "309361")
            self.assertTrue(app.source_account_exists(cursor, source, "309361"))

        self.assertEqual(status, "unique_trade_user_fallback")

    def test_route_missing_rejects_trade_user_found_in_another_physical_source(self):
        source = {
            "name": "DBG MT5", "host": "dbg", "schema": "mt5_export_new",
            "table": "mt5_deals", "kind": "mt5_deals", "platform": "MT5",
            "server": "DBG CN MT5",
            "account_route": {"schema": "crm_cn", "mt_server_code": "4"},
        }
        other = {
            "name": "DBG MT5 Live2", "host": "dbg", "schema": "crm_vn_mt5_live2",
            "table": "mt5_deals", "kind": "mt5_deals", "platform": "MT5",
            "server": "DBG MT5 Live2",
            "account_route": {"schema": "crm_vn", "mt_server_code": "5"},
        }
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, {"Login": 309362}, {"Login": 309362}]

        with patch.object(app, "MYSQL_SOURCES", [source, other]):
            status = app.source_account_route_status(cursor, source, "309362")
            self.assertFalse(app.source_account_exists(cursor, source, "309362"))

        self.assertEqual(status, "ambiguous_trade_user_fallback")

    def test_dbg_cn_mt4_live2_alias_and_route_are_isolated(self):
        sources = {source["name"]: source for source in app.MYSQL_SOURCES}
        cn2 = sources["DBG MT4 CN2"]

        self.assertEqual(cn2["schema"], "crm_cn_mt4_live2")
        self.assertEqual(cn2["account_route"], {"schema": "crm_cn", "mt_server_code": "3"})
        self.assertTrue(app.source_allowed(cn2, platform="MT4", server="DBG CN MT4 Live2"))
        self.assertIs(app.source_for_crm_route("crm_cn", "3"), cn2)

    def test_live3_cent_group_detects_usc_without_daily_currency(self):
        meta = app.account_money_meta(
            group=r"Live3\TX\Cent_STD\F00\B00",
            source_name="AC CN MT5 live3",
            currency_source="mt5_users_view.Group",
        )

        self.assertEqual(meta["currency"], "USC")
        self.assertEqual(meta["displayCurrency"], "USD")
        self.assertEqual(meta["moneyScale"], 0.01)
        self.assertTrue(meta["isCentAccount"])
        self.assertEqual(meta["currencySource"], "mt5_users_view.Group")
        self.assertFalse(app.group_indicates_cent_account(r"Live3\TX\Standard\F00\B00"))
        self.assertFalse(app.group_indicates_cent_account("Incentive_STD"))

    def test_mt5_meta_uses_users_group_without_scanning_daily_view(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"AccountGroup": r"Live3\TX\Cent_STD\F00\B00"}
        source = {"name": "AC CN MT5 live3", "schema": "sass_crm_ac_mt5_live3"}

        meta = app.query_mysql_mt5_account_meta(cursor, source, "241003365")

        self.assertEqual(meta["currency"], "USC")
        self.assertEqual(meta["moneyScale"], 0.01)
        self.assertEqual(meta["currencySource"], "mt5_users_view.Group")
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertIn("`mt5_users_view`", cursor.execute.call_args.args[0])
        self.assertNotIn("`mt5_daily_view`", cursor.execute.call_args.args[0])

    def test_mt5_reversal_deal_is_visible_when_no_open_close_pair_exists(self):
        deals = [{
            "Deal": 11, "Order": 22, "PositionID": 33, "Login": 900003,
            "Action": 0, "Entry": 2, "Time": "2026-08-18 10:00:00",
            "TimeMsc": "2026-08-18 10:00:00.100", "Symbol": "XAUUSD",
            "Volume": 100, "VolumeClosed": 100, "Price": 3300,
            "Profit": 12, "Commission": -1, "Storage": 0, "Fee": 0,
            "Comment": "reversal", "Reason": 0,
        }]

        rows = app.mt5_deals_to_trades(
            deals, {"name": "Live", "platform": "MT5", "server": "Live"}, "900003",
            app.account_money_meta("USD", "Standard", "Live"),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticket"], "33")
        self.assertEqual(rows[0]["open_time"], rows[0]["close_time"])
        self.assertEqual(rows[0]["profit"], 12)

    def test_mt5_trade_query_keeps_reversal_entries_for_conversion(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"mt_login": 900003}, {"AccountGroup": "STANDARD"}]
        cursor.fetchall.return_value = []
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "name": "Live", "server": "Live", "platform": "MT5", "schema": "live",
            "table": "mt5_deals", "kind": "mt5_deals", "default_currency": "USD",
            "account_route": {"schema": "crm", "mt_server_code": "1"},
        }

        with patch.object(app, "mysql_trade_connect", return_value=connection):
            app.query_mysql_mt5_source(source, "900003")

        self.assertTrue(any("Entry in (0, 1, 2, 3)" in call.args[0] for call in cursor.execute.call_args_list))

    def test_mt5_standard_group_uses_source_default_currency_without_daily_view(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"AccountGroup": r"Live1\PXM\B\STD\F00D00"}
        source = {"name": "AC CN MT5", "schema": "sass_crm_ac_mt5_live", "default_currency": "USD"}

        meta = app.query_mysql_mt5_account_meta(cursor, source, "245856")

        self.assertEqual(meta["currency"], "USD")
        self.assertEqual(meta["moneyScale"], 1.0)
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertNotIn("`mt5_daily_view`", cursor.execute.call_args.args[0])

    def test_account_lookup_exposes_cent_meta_for_new_live3_account(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"mt_login": 241003365},
            {
                "RawRows": 2, "OrderCount": 1,
                "FirstTime": "2026-07-20 01:53:17", "LastTime": "2026-07-20 02:04:20",
                "Symbols": "XAUUSD.cs",
            },
            {"AccountGroup": r"Live3\TX\Cent_STD\F00\B00"},
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "name": "AC CN MT5 live3", "server": "AC CN MT5 live3", "platform": "MT5",
            "schema": "sass_crm_ac_mt5_live3", "table": "mt5_deals", "kind": "mt5_deals",
            "account_route": {"schema": "sass_crm_ac", "mt_server_code": "3"},
        }

        with patch.object(app, "mysql_trade_connect", return_value=connection):
            payload = app.query_mysql_account_lookup_source(source, "241003365")

        self.assertTrue(payload["accountMeta"]["isCentAccount"])
        self.assertEqual(payload["accountMeta"]["currency"], "USC")
        self.assertEqual(payload["accountMeta"]["moneyScale"], 0.01)
        self.assertEqual(payload["routeValidation"], "crm_confirmed")

    def test_account_lookup_exposes_fallback_route_and_cent_meta(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            None,
            {"Login": 309361},
            {
                "RawRows": 4, "OrderCount": 2,
                "FirstTime": "2026-06-18 06:10:37", "LastTime": "2026-08-05 04:56:36",
                "Symbols": "XAUUSD",
            },
            {"AccountGroup": r"GLOBAL\B\CENT"},
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "name": "DBG MT5", "host": "dbg", "server": "DBG CN MT5", "platform": "MT5",
            "schema": "mt5_export_new", "table": "mt5_deals", "kind": "mt5_deals",
            "default_currency": "USD", "account_route": {"schema": "crm_cn", "mt_server_code": "4"},
        }

        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "mysql_trade_connect", return_value=connection):
            payload = app.query_mysql_account_lookup_source(source, "309361")

        self.assertEqual(payload["routeValidation"], "unique_trade_user_fallback")
        self.assertTrue(payload["accountMeta"]["isCentAccount"])
        self.assertEqual(payload["accountMeta"]["displayCurrency"], "USD")
        self.assertEqual(payload["accountMeta"]["moneyScale"], 0.01)

    def test_account_lookup_keeps_crm_confirmed_server_when_new_account_has_no_orders(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "RawRows": 0, "OrderCount": 0, "FirstTime": None, "LastTime": None, "Symbols": None,
        }
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "name": "AC GB MT5", "server": "AC GB MT5", "platform": "MT5",
            "schema": "int_sass_crm_ac_mt5_live_new", "table": "mt5_deals", "kind": "mt5_deals",
            "default_currency": "USD", "account_route": {"schema": "int_sass_crm_ac", "mt_server_code": "1"},
        }

        with patch.object(app, "mysql_trade_connect", return_value=connection), \
             patch.object(app, "source_account_exists", return_value=True), \
             patch.object(app, "source_account_route_status", return_value="crm_confirmed"):
            payload = app.query_mysql_account_lookup_source(source, "954059")

        self.assertFalse(payload["exists"])
        self.assertEqual(payload["latestSource"], {"platform": "MT5", "server": "AC GB MT5"})
        self.assertEqual(payload["routeValidation"], "crm_confirmed")
        self.assertIn("账户暂未做单", payload["error"])

    def test_account_lookup_orders_are_sorted_before_empty_confirmed_sources(self):
        def lookup(source, account):
            return {
                "exists": source["name"] == "AC CN MT5",
                "account": account,
                "orderCount": 3 if source["name"] == "AC CN MT5" else 0,
                "latestSource": {"platform": "MT5", "server": source["server"]},
            }

        sources = [
            {"name": "AC GB MT5", "platform": "MT5", "server": "AC GB MT5"},
            {"name": "AC CN MT5", "platform": "MT5", "server": "AC CN MT5"},
        ]
        with patch.object(app, "MYSQL_SOURCES", sources), \
             patch.object(app, "query_mysql_account_lookup_source", side_effect=lookup), \
             patch.object(app, "TRADE_DB_SOURCE", "mysql"):
            matches = app.account_lookup_databases("532573")

        self.assertEqual([row["latestSource"]["server"] for row in matches], ["AC CN MT5", "AC GB MT5"])

    def test_account_lookup_does_not_turn_all_source_failures_into_no_order(self):
        source = {"name": "AC GB MT5", "platform": "MT5", "server": "AC GB MT5"}
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_mysql_account_lookup_source", side_effect=RuntimeError("连接超时")), \
             patch.object(app, "TRADE_DB_SOURCE", "mysql"):
            matches = app.account_lookup_databases("532574")

        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]["queryFailed"])
        self.assertIn("查询失败", matches[0]["error"])

    def test_detail_requires_server_selection_before_merging_multiple_sources(self):
        routes = [
            {"exists": True, "orderCount": 2, "latestSource": {"platform": "MT5", "server": "AC GB MT5"}},
            {"exists": True, "orderCount": 4, "latestSource": {"platform": "MT5", "server": "AC CN MT5"}},
        ]
        with patch.object(app, "account_lookup_databases", return_value=routes), \
             patch.object(app, "account_trade_analysis") as analysis:
            detail = app._account_database_detail_uncached("532573")

        self.assertTrue(detail["requiresSourceSelection"])
        self.assertEqual(detail["sourceCandidates"], [
            {"platform": "MT5", "server": "AC GB MT5", "orderCount": 2},
            {"platform": "MT5", "server": "AC CN MT5", "orderCount": 4},
        ])
        analysis.assert_not_called()

    def test_mt4_trade_query_excludes_open_position_sentinel(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"mt_login": 5013015},
            {"CURRENCY": "USD", "AccountGroup": r"AC\STD"},
        ]
        cursor.fetchall.return_value = [
            {
                "TICKET": 1, "LOGIN": 5013015, "CMD": 0, "SYMBOL": "XAUUSD", "VOLUME": 50,
                "OPEN_TIME": "2026-07-20 03:00:00", "CLOSE_TIME": "2026-07-20 03:10:00",
                "OPEN_PRICE": 3300, "CLOSE_PRICE": 3301, "PROFIT": 50,
                "COMMISSION": 0, "TAXES": 0, "SWAPS": 0,
            },
            {
                "TICKET": 2, "LOGIN": 5013015, "CMD": 0, "SYMBOL": "XAUUSD", "VOLUME": 50,
                "OPEN_TIME": "2026-07-20 05:00:00", "CLOSE_TIME": "1970-01-01 00:00:00",
                "OPEN_PRICE": 3300, "CLOSE_PRICE": 0, "PROFIT": -100,
                "COMMISSION": 0, "TAXES": 0, "SWAPS": 0,
            },
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "name": "AC MT4", "server": "AC CN MT4", "platform": "MT4",
            "schema": "mt4_export_syc", "table": "mt4_trades", "kind": "mt4_trades",
            "account_route": {"schema": "sass_crm_ac", "mt_server_code": "2"},
        }

        with patch.object(app, "mysql_trade_connect", return_value=connection):
            rows = app.query_mysql_mt4_source(source, "5013015")

        self.assertEqual([row["ticket"] for row in rows], ["1"])
        self.assertEqual(rows[0]["holding_seconds"], 600)
        trade_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("CLOSE_TIME > OPEN_TIME", trade_sql)

    @staticmethod
    def deals():
        return [
            {
                "Deal": 1, "Order": 10, "PositionID": 100, "Action": 0, "Entry": 0,
                "Time": "2026-07-01 10:00:00", "Symbol": "XAUUSD", "Price": 3300,
                "Volume": 100000, "Commission": -100, "Storage": -25,
                "Reason": 1, "Comment": "auto trade by sc", "ExpertID": 234000,
            },
            {
                "Deal": 2, "Order": 11, "PositionID": 100, "Action": 0, "Entry": 1,
                "Time": "2026-07-01 10:01:00", "Symbol": "XAUUSD", "Price": 3301,
                "Volume": 100000, "VolumeClosed": 100000, "Profit": 12345, "Commission": -50,
                "Reason": 1, "Comment": "close by script", "ExpertID": 234000,
            },
        ]

    def test_usc_scales_only_money_fields(self):
        rows = app.mt5_deals_to_trades(
            self.deals(), {"name": "Live", "platform": "MT5", "server": "Live"}, "900001",
            app.account_money_meta("USC", "Cent", "Live"),
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["profit"], 123.45)
        self.assertEqual(row["commission"], -1.5)
        self.assertEqual(row["swap"], -0.25)
        self.assertEqual(row["volume"], 10)
        self.assertEqual(row["open_price"], 3300)
        self.assertEqual(row["account_currency"], "USC")
        self.assertTrue(row["is_cent_account"])
        self.assertEqual(row["reason"], "Expert")
        self.assertEqual(row["open_comment"], "auto trade by sc")
        self.assertEqual(row["comment"], "auto trade by sc / close by script")
        self.assertEqual(row["expert_id"], "234000")

    def test_usd_keeps_money_fields_unscaled(self):
        rows = app.mt5_deals_to_trades(
            self.deals(), {"name": "Live", "platform": "MT5", "server": "Live"}, "900002",
            app.account_money_meta("USD", "Standard", "Live"),
        )
        row = rows[0]
        self.assertEqual(row["profit"], 12345)
        self.assertEqual(row["commission"], -150)
        self.assertEqual(row["swap"], -25)
        self.assertEqual(row["volume"], 10)
        self.assertEqual(row["account_currency"], "USD")
        self.assertFalse(row["is_cent_account"])


class AccountLookupPerformanceTests(unittest.TestCase):
    def setUp(self):
        with app.ACCOUNT_QUERY_CACHE_LOCK:
            app.ACCOUNT_QUERY_CACHE.clear()

    def test_lookup_keeps_same_login_from_different_platforms(self):
        def lookup(source, account):
            return {
                "exists": True, "account": account, "orderCount": 1, "chartableOrderCount": 1,
                "firstTime": "2026-07-01 00:00:00", "lastTime": "2026-07-02 00:00:00",
                "platforms": [{"value": source["platform"], "label": source["platform"]}],
                "servers": [{"value": source["server"], "label": source["server"]}],
                "symbols": ["XAUUSD"], "latestSource": {"platform": source["platform"], "server": source["server"]},
                "accountMeta": {}, "refreshedAt": "2026-07-13 12:00:00", "dbSource": "mysql",
            } if source["name"] in {"AC GB MT5", "AC MT4"} else None

        with patch.object(app, "query_mysql_account_lookup_source", side_effect=lookup), \
             patch.object(app, "TRADE_DB_SOURCE", "mysql"):
            matches = app.account_lookup_databases("532573")
        self.assertEqual([(row["latestSource"]["platform"], row["latestSource"]["server"]) for row in matches], [
            ("MT5", "AC GB MT5"), ("MT4", "AC CN MT4"),
        ])

    def test_detail_scopes_source_and_reuses_rows_without_detail_filters(self):
        trade = {
            "data_source": "mysql", "platform": "MT5", "server": "AC GB MT5", "symbol": "XAUUSD",
            "type": "buy", "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00",
            "volume": 0.1, "profit": 1, "commission": 0, "swap": 0, "taxes": 0, "holding_seconds": 60,
        }
        empty_costs = {"commission": 0, "swap": 0, "taxes": 0, "complete": True, "sources": [], "bySymbol": {}}
        analysis = {
            "rows": [trade], "costs": empty_costs, "metrics": app.trade_metrics([trade], empty_costs),
            "usesMysql": True, "historyLimit": 50000,
        }
        with patch.object(app, "account_trade_analysis", return_value=analysis) as query_analysis:
            detail = app._account_database_detail_uncached("532573", {"platform": "MT5", "server": "AC GB MT5"})
        self.assertTrue(detail["exists"])
        query_analysis.assert_called_once_with("532573", platform="MT5", server="AC GB MT5")

    def test_detail_keeps_confirmed_server_when_account_has_no_orders(self):
        analysis = {
            "rows": [], "costs": None, "metrics": app.trade_metrics([]),
            "usesMysql": True, "historyLimit": 50000,
        }
        route = {
            "exists": False, "dbSource": "mysql", "account": "954059", "orderCount": 0,
            "chartableOrderCount": 0, "firstTime": "", "lastTime": "", "symbols": [],
            "latestSource": {"platform": "MT5", "server": "AC GB MT5"},
            "accountMeta": app.account_money_meta(source_name="AC GB MT5"),
            "routeValidation": "crm_confirmed", "error": "账户暂未做单", "refreshedAt": "2026-08-06 11:17:50",
        }

        with patch.object(app, "account_trade_analysis", return_value=analysis), \
             patch.object(app, "account_lookup_databases", return_value=[route]):
            detail = app._account_database_detail_uncached("954059")

        self.assertFalse(detail["exists"])
        self.assertEqual(detail["latestSource"], {"platform": "MT5", "server": "AC GB MT5"})
        self.assertEqual(detail["platforms"], [{"value": "MT5", "label": "MT5"}])
        self.assertEqual(detail["servers"], [{"value": "AC GB MT5", "label": "AC GB MT5"}])
        self.assertIn("账户暂未做单", detail["error"])

    def test_lookup_finance_returns_database_local_status_and_comprehensive_profit(self):
        source = {"name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals"}
        trade = {"data_source": "mysql", "platform": "MT5", "server": "Live", "profit": 10}
        analysis = {"rows": [trade], "metrics": app.trade_metrics([trade])}
        ledger = {"建议动作": "P", "状态": "观察中"}
        finance = {"comprehensiveProfit": 37918.02, "displayCurrency": "USD"}
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "account_trade_analysis", return_value=analysis), \
             patch.object(app, "query_mt5_finance_panel", return_value=finance), \
             patch.object(app, "query_mt5_database_statuses", return_value={"37103": "P"}), \
             patch.object(app, "ledger_record_for_login", return_value=ledger):
            payload = app.account_lookup_finance_payload("37103", "MT5", "Live")

        self.assertEqual(payload["databaseStatus"], "P")
        self.assertEqual(payload["localStatus"], "P")
        self.assertEqual(payload["workflowStatus"], "观察中")
        self.assertEqual(payload["comprehensiveProfit"], 37918.02)
        self.assertEqual(payload["currency"], "USD")

    def test_lookup_finance_old_ac_mt4_alias_uses_server_resolved_from_rows(self):
        cn_source = {"name": "AC MT4", "platform": "MT4", "server": "AC CN MT4", "aliases": ["AC MT4"], "kind": "mt4_trades"}
        gb_source = {"name": "AC GB MT4", "platform": "MT4", "server": "AC GB MT4", "kind": "mt4_trades"}
        trade = {"data_source": "mysql", "platform": "MT4", "server": "AC GB MT4", "profit": 10}
        analysis = {"rows": [trade], "metrics": app.trade_metrics([trade])}
        finance = {"comprehensiveProfit": 243.38, "displayCurrency": "USD"}
        with patch.object(app, "MYSQL_SOURCES", [cn_source, gb_source]), \
             patch.object(app, "account_trade_analysis", return_value=analysis), \
             patch.object(app, "query_mt4_finance_panel", return_value=finance) as finance_query, \
             patch.object(app, "query_mt4_database_statuses", return_value={"5010772": "Enabled"}), \
             patch.object(app, "ledger_record_for_login", return_value=None):
            app.account_lookup_finance_payload("5010772", "MT4", "AC MT4")

        finance_query.assert_called_once_with(gb_source, "5010772", [trade], unittest.mock.ANY)

    def test_lookup_finance_old_dbg_mt5_alias_uses_server_resolved_from_rows(self):
        cn_source = {"name": "DBG MT5", "platform": "MT5", "server": "DBG CN MT5", "aliases": ["DBG MT5"], "kind": "mt5_deals"}
        gb_source = {"name": "DBG GB MT5", "platform": "MT5", "server": "DBG GB MT5", "kind": "mt5_deals"}
        trade = {"data_source": "mysql", "platform": "MT5", "server": "DBG GB MT5", "profit": 10}
        analysis = {"rows": [trade], "metrics": app.trade_metrics([trade])}
        finance = {"comprehensiveProfit": 15.25, "displayCurrency": "USD"}
        with patch.object(app, "MYSQL_SOURCES", [cn_source, gb_source]), \
             patch.object(app, "account_trade_analysis", return_value=analysis), \
             patch.object(app, "query_mt5_finance_panel", return_value=finance) as finance_query, \
             patch.object(app, "query_mt5_database_statuses", return_value={"3067746": "Enabled"}), \
             patch.object(app, "ledger_record_for_login", return_value=None):
            app.account_lookup_finance_payload("3067746", "MT5", "DBG MT5")

        finance_query.assert_called_once_with(gb_source, "3067746", [trade], unittest.mock.ANY)


class TradeMetricsTests(unittest.TestCase):
    def test_calculates_requested_order_metrics(self):
        rows = [
            {
                "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "buy",
                "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:00:30",
                "volume": 0.1, "profit": 10, "commission": -1, "swap": 0, "taxes": 0,
                "holding_seconds": 30,
            },
            {
                "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "sell",
                "open_time": "2026-07-01 10:01:00", "close_time": "2026-07-01 10:11:00",
                "volume": 0.2, "profit": -4, "commission": -2, "swap": -0.5, "taxes": 0,
                "holding_seconds": 600,
            },
            {
                "platform": "MT4", "server": "CN1", "symbol": "EURUSD", "type": "buy",
                "open_time": "2026-07-02 09:00:00", "close_time": "2026-07-02 09:03:00",
                "volume": 0.3, "profit": 6, "commission": -1, "swap": 0, "taxes": 0,
                "holding_seconds": 180,
            },
        ]

        metrics = app.trade_metrics(rows)

        self.assertEqual(metrics["orderCount"], 3)
        self.assertEqual(metrics["chartableOrderCount"], 3)
        self.assertEqual(metrics["symbolCount"], 2)
        self.assertEqual(metrics["grossProfit"], 12)
        self.assertEqual(metrics["netProfit"], 7.5)
        self.assertEqual(metrics["totalProfit"], 7.5)
        self.assertEqual(metrics["winRate"], 66.67)
        self.assertEqual(metrics["averageProfit"], 2.5)
        self.assertEqual(metrics["medianProfit"], 5)
        self.assertEqual(metrics["totalVolume"], 0.6)
        self.assertEqual(metrics["medianHoldingSeconds"], 180)
        self.assertEqual(metrics["shortHoldingRatio"], 66.67)
        self.assertEqual(metrics["feesTotal"], -4.5)
        self.assertEqual(metrics["activeDays"], 2)
        self.assertEqual(len(metrics["bySymbol"]), 2)
        self.assertEqual(len(metrics["bySource"]), 2)
        xau = next(row for row in metrics["bySymbol"] if row["symbol"] == "XAUUSD")
        self.assertEqual(xau["firstTime"], "2026-07-01 10:00:00")
        self.assertEqual(xau["lastTime"], "2026-07-01 10:11:00")

    def test_account_cost_summary_includes_open_trade_fees(self):
        row = {
            "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "buy",
            "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00",
            "volume": 0.1, "profit": 10, "commission": -1, "swap": 0, "taxes": 0,
            "holding_seconds": 60,
        }
        costs = {
            "commission": -3, "swap": -1, "taxes": 0, "complete": True,
            "includesOpenTradeFees": True,
            "sources": [{"platform": "MT5", "server": "Live", "commission": -3, "swap": -1, "taxes": 0}],
            "bySymbol": {"XAUUSD": {"commission": -3, "swap": -1, "taxes": 0}},
        }

        metrics = app.trade_metrics([row], costs)

        self.assertEqual(metrics["grossProfit"], 10)
        self.assertEqual(metrics["closedNetProfit"], 9)
        self.assertEqual(metrics["netProfit"], 6)
        self.assertEqual(metrics["commissionTotal"], -3)
        self.assertTrue(metrics["costsIncludeOpenTradeFees"])
        self.assertEqual(metrics["bySource"][0]["profit"], 6)
        self.assertEqual(metrics["bySymbol"][0]["profit"], 6)

    def test_unfiltered_mt4_detail_uses_full_history_and_reuses_metrics(self):
        rows = [{
            "platform": "MT4", "server": "DBG MT4 CN1", "symbol": "XAUUSD", "type": "buy",
            "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00",
            "volume": 0.1, "profit": 1, "commission": 0, "swap": 0, "taxes": 0,
            "holding_seconds": 60, "data_source": "mysql",
        }]
        with patch.object(app, "account_cache_get", return_value=None), \
             patch.object(app, "account_cache_set", side_effect=lambda _key, value: value), \
             patch.object(app, "query_db_trades", return_value=rows) as query, \
             patch.object(app, "query_mysql_trade_costs", return_value={}) as costs, \
             patch.object(app, "trade_metrics", wraps=app.trade_metrics) as metrics:
            analysis = app.account_trade_analysis("8208074", "MT4", "DBG MT4 CN1")

        query.assert_called_once_with(
            "8208074", limit=None, platform="MT4", server="DBG MT4 CN1"
        )
        costs.assert_called_once_with("8208074", platform="MT4", server="DBG MT4 CN1")
        self.assertEqual(metrics.call_count, 1)

        with patch.object(app, "account_trade_analysis", return_value=analysis), \
             patch.object(app, "trade_metrics", wraps=app.trade_metrics) as metrics:
            detail = app._account_database_detail_uncached(
                "8208074", {"platform": "MT4", "server": "DBG MT4 CN1"}
            )
        self.assertEqual(metrics.call_count, 0)
        self.assertIs(detail["metrics"], detail["allMetrics"])


class VisualizationTests(unittest.TestCase):
    def test_visualization_total_matches_net_profit_with_unallocated_cost_adjustment(self):
        rows = [
            {
                "ticket": "1", "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00",
                "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "buy",
                "volume": 1, "profit": 10, "commission": -1, "swap": -1, "taxes": 0, "holding_seconds": 60,
            },
            {
                "ticket": "2", "open_time": "2026-07-02 10:00:00", "close_time": "2026-07-02 10:02:00",
                "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "sell",
                "volume": 1, "profit": -4, "commission": -2, "swap": 0, "taxes": 0, "holding_seconds": 120,
            },
        ]
        costs = {
            "commission": -5, "swap": -1, "taxes": 0, "complete": True,
            "includesOpenTradeFees": True, "sources": [], "bySymbol": {},
        }
        metrics = app.trade_metrics(rows, costs)
        visual = app.trade_visualizations(rows, metrics)

        self.assertEqual(metrics["netProfit"], 0)
        self.assertEqual(visual["netTotal"], 0)
        self.assertEqual(visual["feeAdjustment"], -2)
        self.assertEqual(visual["pnlSeries"][-1]["value"], 0)
        self.assertEqual(sum(row["profit"] for row in visual["dailyPnl"]), 0)
        self.assertEqual(visual["maxDrawdown"], 8)
        self.assertEqual(visual["outcomes"], {"winning": 1, "losing": 1, "breakeven": 0})


class QuickActionTests(unittest.TestCase):
    def test_quick_actions_can_be_added_and_deleted_without_changing_builtin_choices(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(app, "QUICK_ACTIONS_PATH", Path(temp_dir) / "quick_actions.json"):
            original_choices = list(app.ACTION_CHOICES)
            actions = app.add_quick_action("重点复核")
            self.assertIn("重点复核", actions)
            self.assertEqual(actions.count("重点复核"), 1)
            self.assertEqual(app.add_quick_action("重点复核").count("重点复核"), 1)
            actions = app.delete_quick_action("重点复核")
            self.assertNotIn("重点复核", actions)
            self.assertIn("自定义", actions)
            self.assertEqual(app.ACTION_CHOICES, original_choices)

    def test_protected_custom_action_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(app, "QUICK_ACTIONS_PATH", Path(temp_dir) / "quick_actions.json"):
            with self.assertRaises(ValueError):
                app.delete_quick_action("自定义")


class RiskPanelTests(unittest.TestCase):
    @staticmethod
    def trade(opened, closed, profit, volume=1, currency="USD"):
        return {
            "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "buy",
            "open_time": opened, "close_time": closed, "volume": volume, "profit": profit,
            "commission": 0, "swap": 0, "taxes": 0,
            "holding_seconds": (
                app.parse_trade_time(closed) - app.parse_trade_time(opened)
            ).total_seconds(),
            "account_currency": currency,
            "display_currency": "USD",
            "money_scale": 0.01 if currency == "USC" else 1,
            "is_cent_account": currency == "USC",
        }

    def test_high_frequency_buckets_and_cent_volume_scale(self):
        rows = [
            self.trade("2026-07-01 10:00:00", "2026-07-01 10:00:05", 10, 2, "USC"),
            self.trade("2026-07-01 10:01:00", "2026-07-01 10:02:00", -2, 3, "USC"),
            self.trade("2026-07-01 10:03:00", "2026-07-01 10:06:00", 5, 5, "USC"),
            self.trade("2026-07-01 10:10:00", "2026-07-01 10:30:00", -4, 10, "USC"),
        ]

        panel = app.riskdash_high_frequency(rows)

        self.assertEqual(panel["orderCount"], 4)
        self.assertEqual(panel["highFrequencyOrderRatio"], 50)
        self.assertEqual(panel["volumeScale"], 0.01)
        self.assertEqual(panel["buckets"][0]["orders"], 1)
        self.assertEqual(panel["buckets"][0]["volume"], 0.02)
        self.assertEqual(panel["buckets"][1]["volume"], 0.03)
        self.assertEqual(panel["buckets"][4]["grossProfit"], -4)

    def test_classifies_cashflows_without_counting_internal_transfers_as_deposit(self):
        rows = [
            {"Action": 2, "Profit": 100000, "Comment": "DEP-123"},
            {"Action": 2, "Profit": -25000, "Comment": "WDR-123"},
            {"Action": 2, "Profit": 2000, "Comment": "RST-negative balance"},
            {"Action": 2, "Profit": 3000, "Comment": "COMP case"},
            {"Action": 6, "Profit": 4000, "Comment": "BONUS"},
            {"Action": 2, "Profit": 5000, "Comment": "TFM-123"},
        ]

        result = app.classify_mt5_cashflows(rows, 0.01)

        self.assertEqual(result["netDeposit"], 750)
        self.assertEqual(result["negativeBalanceClear"], 20)
        self.assertEqual(result["compensation"], 30)
        self.assertEqual(result["reward"], 40)
        self.assertEqual(result["internalTransfer"], 50)
        self.assertEqual(result["other"], 0)
        self.assertEqual(result["depositTotal"], 1000)
        self.assertEqual(result["withdrawalTotal"], 250)
        self.assertEqual(result["depositCount"], 1)
        self.assertEqual(result["withdrawalCount"], 1)

    def test_classifies_mt4_balance_operations_and_adjustments(self):
        rows = [
            {"CMD": 6, "PROFIT": 100000, "COMMENT": "DEP-123"},
            {"CMD": 6, "PROFIT": -25000, "COMMENT": "Withdrawal"},
            {"CMD": 6, "PROFIT": 2000, "COMMENT": "RST-negative balance"},
            {"CMD": 6, "PROFIT": 3000, "COMMENT": "COMP case"},
            {"CMD": 7, "PROFIT": 4000, "COMMENT": "BONUS"},
            {"CMD": 6, "PROFIT": 5000, "COMMENT": "TFM-123"},
        ]

        result = app.classify_mt4_cashflows(rows, 0.01)

        self.assertEqual(result["netDeposit"], 750)
        self.assertEqual(result["negativeBalanceClear"], 20)
        self.assertEqual(result["compensation"], 30)
        self.assertEqual(result["reward"], 40)
        self.assertEqual(result["internalTransfer"], 50)
        self.assertEqual(result["other"], 0)
        self.assertEqual(result["depositTotal"], 1000)
        self.assertEqual(result["withdrawalTotal"], 250)

    def test_classifies_riskdash_cashflow_prefixes(self):
        mt5 = app.classify_mt5_cashflows([
            {"Action": 2, "Profit": 100, "Comment": "CRM-DP-NePayV2-1"},
            {"Action": 2, "Profit": -40, "Comment": "CRM-CW123"},
        ])
        self.assertEqual(mt5["netDeposit"], 60)
        self.assertEqual(mt5["depositTotal"], 100)
        self.assertEqual(mt5["withdrawalTotal"], 40)

        mt4 = app.classify_mt4_cashflows([
            {"CMD": 6, "PROFIT": 100, "COMMENT": "DEP-1"},
            {"CMD": 6, "PROFIT": 1.65, "COMMENT": "CPS_260525"},
            {"CMD": 6, "PROFIT": 2.79, "COMMENT": "CCB-Reward"},
        ])
        self.assertEqual(mt4["netDeposit"], 100)
        self.assertEqual(mt4["compensation"], 1.65)
        self.assertEqual(mt4["negativeBalanceClear"], 2.79)
        self.assertEqual(mt4["reward"], 0)

    def test_cashflow_timing_measures_withdrawal_after_trading(self):
        cashflows = {
            "depositTotal": 5000, "withdrawalTotal": 3500, "depositCount": 1, "withdrawalCount": 1,
            "depositTimes": ["2026-07-01 08:00:00"], "withdrawalTimes": ["2026-07-02 12:00:00"],
        }
        trades = [{"open_time": "2026-07-01 09:00:00", "close_time": "2026-07-02 10:00:00"}]
        result = app.cashflow_timing_summary(cashflows, trades)
        self.assertEqual(result["firstDepositToTradeHours"], 1)
        self.assertEqual(result["lastTradeToWithdrawalHours"], 2)

    def test_max_concurrent_volume_sweeps_open_and_close_events(self):
        rows = [
            self.trade("2026-07-01 10:00:00", "2026-07-01 10:10:00", 1, 2),
            self.trade("2026-07-01 10:05:00", "2026-07-01 10:15:00", 1, 3),
            self.trade("2026-07-01 10:10:00", "2026-07-01 10:20:00", 1, 4),
        ]

        self.assertEqual(app.max_concurrent_volume(rows), 7)

    def test_comprehensive_profit_uses_riskdash_formula(self):
        result = app.calculate_comprehensive_profit(
            closed_net_profit=1944.32,
            rebate=3746.70,
            holding_profit=-1572.33,
            negative_balance_clear=0,
            compensation=0,
            reward=0,
        )

        self.assertEqual(result, 4118.69)

    def test_same_name_local_column_uses_risk_action_not_workflow_status(self):
        finance = {
            "currency": "USD", "displayCurrency": "USD", "balance": 1, "equity": 1,
            "netDeposit": 1, "holdingProfit": 0, "closedNetProfit": 0,
            "negativeBalanceClear": 0, "compensation": 0, "reward": 0, "rebate": 0,
            "comprehensiveProfit": 0, "highestHoldingVolume": 0,
        }
        record = {field: "" for field in app.HEADERS}
        record.update({"账号": "900001", "建议动作": "M", "状态": "观察中"})
        source = {"server": "Live", "platform": "MT5", "kind": "mt5_deals"}
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_mt5_finance_panel", return_value=finance), \
             patch.object(app, "load_records", return_value=[record]), \
             patch.object(app, "query_same_name_accounts", return_value=[{"account": "900001", "source": source}]), \
             patch.object(app, "query_mt5_database_statuses", return_value={"900001": "M"}):
            panel = app.build_riskdash_panels("900001", [{"platform": "MT5", "server": "Live"}], {}, [])
        self.assertEqual(panel["sameName"][0]["databaseStatus"], "M")
        self.assertEqual(panel["sameName"][0]["localStatus"], "M")
        self.assertNotEqual(panel["sameName"][0]["localStatus"], "观察中")

    def test_relationship_core_carries_database_statuses_without_local_ledger_marks(self):
        source = {"server": "Live", "platform": "MT5", "kind": "mt5_deals"}
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_same_name_accounts", return_value=[
                 {"account": "900001", "source": source}, {"account": "900002", "source": source},
             ]), \
             patch.object(app, "query_mt5_database_statuses", return_value={"900001": "TA", "900002": "P"}) as status_query:
            payload = app.account_relationship_core_payload("900001", {"platform": "MT5", "server": "Live"})

        panels = payload["riskPanels"]
        self.assertEqual(panels["databaseStatus"], "TA")
        self.assertEqual([row["databaseStatus"] for row in panels["sameName"]], ["TA", "P"])
        status_query.assert_called_once()
        self.assertEqual(set(status_query.call_args.args[1]), {"900001", "900002"})

    def test_mt4_risk_panel_uses_mt4_finance_and_shows_current_account(self):
        finance = {
            "currency": "USD", "displayCurrency": "USD", "balance": 100, "equity": 95,
            "netDeposit": 80, "holdingProfit": -5, "closedNetProfit": 20,
            "negativeBalanceClear": 0, "compensation": 0, "reward": 0, "rebate": 0,
            "comprehensiveProfit": 15, "highestHoldingVolume": 1,
        }
        source = {"server": "AC MT4", "platform": "MT4", "kind": "mt4_trades"}
        rows = [{"platform": "MT4", "server": "AC MT4"}]
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_mt4_finance_panel", return_value=finance) as finance_query, \
             patch.object(app, "load_records", return_value=[]), \
             patch.object(app, "query_same_name_accounts", return_value=[{"account": "900004", "source": source}]), \
             patch.object(app, "query_mt4_database_statuses", return_value={"900004": "Enabled"}):
            panel = app.build_riskdash_panels("900004", rows, {}, rows)

        self.assertTrue(panel["available"])
        self.assertEqual(panel["sameName"][0]["platform"], "MT4")
        self.assertEqual(panel["sameName"][0]["account"], "900004")
        self.assertEqual(panel["sameName"][0]["databaseStatus"], "Enabled")
        self.assertEqual(panel["finance"]["balance"], 100)
        finance_query.assert_called_once_with(source, "900004", rows, {})

    def test_same_name_query_keeps_accounts_on_other_crm_server_codes(self):
        live1 = {
            "server": "AC CN MT5", "platform": "MT5", "kind": "mt5_deals",
            "crm_routes": [{"schema": "sass_crm_ac", "mt_server_code": "1"}],
        }
        live3 = {
            "server": "AC CN MT5 live3", "platform": "MT5", "kind": "mt5_deals",
            "crm_routes": [{"schema": "sass_crm_ac", "mt_server_code": "3"}],
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = {"user_id": 133018}
        cursor.fetchall.return_value = [
            {"mt_login": 245856, "mt_server_code": 1},
            {"mt_login": 241003365, "mt_server_code": 3},
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context

        with patch.object(app, "MYSQL_SOURCES", [live1, live3]), \
             patch.object(app, "mysql_trade_connect", return_value=connection):
            accounts = app.query_same_name_accounts(live3, "241003365")

        self.assertEqual([item["account"] for item in accounts], ["245856", "241003365"])
        self.assertIs(accounts[0]["source"], live1)
        self.assertIs(accounts[1]["source"], live3)
        self.assertNotIn("mt_server_code = %s", cursor.execute.call_args_list[1].args[0])
        self.assertEqual(cursor.execute.call_args_list[1].args[1], (133018,))

    def test_same_name_panel_queries_each_account_through_its_own_server(self):
        live1 = {"server": "AC CN MT5", "platform": "MT5", "kind": "mt5_deals"}
        live3 = {"server": "AC CN MT5 live3", "platform": "MT5", "kind": "mt5_deals"}
        current_rows = [{"platform": "MT5", "server": "AC CN MT5 live3", "account": "241003365"}]

        def finance_for_source(item_source, account, rows, metrics):
            amount = 10 if item_source is live1 else 20
            return {
                "currency": "USD", "balance": amount, "equity": amount, "netDeposit": amount,
                "holdingProfit": 0, "closedNetProfit": 0, "negativeBalanceClear": 0,
                "compensation": 0, "reward": 0, "rebate": 0, "comprehensiveProfit": amount,
                "highestHoldingVolume": 0,
            }

        with patch.object(app, "MYSQL_SOURCES", [live1, live3]), \
             patch.object(app, "query_same_name_accounts", return_value=[
                 {"account": "245856", "source": live1},
                 {"account": "241003365", "source": live3},
             ]), \
             patch.object(app, "query_mt5_finance_panel", side_effect=finance_for_source), \
             patch.object(app, "query_mysql_mt5_source", return_value=[]) as trade_query, \
             patch.object(app, "query_mysql_trade_costs", return_value={}), \
             patch.object(app, "query_mt5_database_statuses", side_effect=lambda _, accounts: {item: "Enabled" for item in accounts}), \
             patch.object(app, "load_records", return_value=[]):
            panel = app.build_riskdash_panels("241003365", current_rows, {}, current_rows)

        self.assertEqual(
            [(row["account"], row["server"]) for row in panel["sameName"]],
            [("245856", "AC CN MT5"), ("241003365", "AC CN MT5 live3")],
        )
        self.assertEqual(panel["sameNameTotals"]["balance"], 30)
        trade_query.assert_called_once_with(live1, "245856", limit=50000)


class OrderListTests(unittest.TestCase):
    def test_reason_labels_and_comment_merging(self):
        self.assertEqual(app.trade_reason_label("MT5", 1), "Expert")
        self.assertEqual(app.trade_reason_label("MT5", 16), "Web")
        self.assertEqual(app.trade_reason_label("MT4", 1), "Expert")
        self.assertEqual(app.combined_trade_comment("EA alpha", "EA alpha", "close by script"), "EA alpha / close by script")

    def test_ea_trade_detection_uses_reason_expert_id_and_explicit_comment(self):
        self.assertTrue(app.is_ea_trade({"reason": "Expert"}))
        self.assertTrue(app.is_ea_trade({"expert_id": "86666159"}))
        self.assertTrue(app.is_ea_trade({"comment": "EA scalper v2"}))
        self.assertFalse(app.is_ea_trade({"reason": "Client", "comment": "manual review"}))
        self.assertFalse(app.is_ea_trade({"reason": "Expert", "comment": "@14@95002113@19"}))
        self.assertFalse(app.is_ea_trade({"reason": "Expert", "comment": "1/521/58439466"}))
        self.assertFalse(app.is_ea_trade({"reason": "Expert", "comment": "so: 49.8%/50.0%"}))

    def test_cpt_comment_marks_copy_trade(self):
        row = {"comment": "CPT-SS#348815929 / CPT-SS#348821201"}
        self.assertTrue(app.is_copy_trade(row))
        self.assertEqual(app.copy_trade_order_ids(row), ["348815929"])
        self.assertEqual(app.copy_trade_channels(row), ["CPT-SS"])
        self.assertEqual(
            app.copy_trade_order_ids({"open_comment": "CPT-SS#100", "comment": "CPT-SS#100 / CPT-SS#200"}),
            ["100"],
        )
        self.assertTrue(app.is_copy_trade({"comment": "[CPT-SS#348815929]"}))
        self.assertTrue(app.is_copy_trade({"platform": "MT4", "reason_code": 3}))
        self.assertTrue(app.is_copy_trade({"platform": "MT5", "reason_code": 9}))
        self.assertTrue(app.is_copy_trade({"platform": "MT5", "reason": "Synchronization"}))
        self.assertTrue(app.is_copy_trade({"comment": "Signal #5009780 IN"}))
        self.assertTrue(app.is_copy_trade({"comment": "trade copier alpha"}))
        self.assertFalse(app.is_copy_trade({"comment": "manual trade"}))
        metrics = app.trade_metrics([row])
        self.assertTrue(metrics["hasCopyTrades"])
        self.assertEqual(metrics["copyOrderCount"], 1)
        self.assertTrue(app.public_trade_order(row)["isCopyTrade"])

    def test_mt4_order_page_uses_database_pagination_and_exact_total(self):
        source = {"platform": "MT4", "server": "DBG MT4 CN1", "kind": "mt4_trades"}
        row = {
            "ticket": "99", "platform": "MT4", "server": "DBG MT4 CN1", "symbol": "XAUUSD",
            "type": "buy", "open_time": "2026-07-20 10:00:00", "close_time": "2026-07-20 10:01:00",
            "holding_seconds": 60, "volume": 0.1, "profit": 2, "commission": 0,
            "swap": 0, "taxes": 0,
        }
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_mysql_mt4_orders_page_source", return_value=(59504, [row])) as page_query, \
             patch.object(app, "query_db_trades") as legacy_query:
            payload = app.account_orders_payload(
                "8208074", page=1, page_size=100, platform="MT4", server="DBG MT4 CN1"
            )

        page_query.assert_called_once_with(source, "8208074", 1, 100)
        legacy_query.assert_not_called()
        self.assertEqual(payload["total"], 59504)
        self.assertEqual(payload["orders"][0]["ticket"], "99")
        self.assertFalse(payload["truncated"])

    def test_copy_origin_lookup_groups_initiating_accounts_by_cpt_order_id(self):
        copied_rows = [{"comment": "CPT-SS#348815929 / CPT-SS#348821201"}]
        source = {"name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals"}
        candidates = [
            {"account": "700001", "platform": "MT5", "server": "Live", "ticket": "348815929", "matchedOrderIds": ["348815929"], "time": "2026-07-01 10:00:00", "symbol": "XAUUSD", "comment": "source"},
        ]
        follower_rows = [
            {"account": "700002", "platform": "MT5", "server": "Live", "ticket": "5001", "matchedSourceOrderIds": ["348815929"], "openTime": "2026-07-01 10:00:01", "closeTime": "2026-07-01 10:01:01", "symbol": "XAUUSD", "volume": 0.2, "grossProfit": 12, "commission": -1, "swap": 0, "taxes": 0, "netProfit": 11, "currency": "USD", "displayCurrency": "USD"},
        ]
        with patch.object(app, "query_db_trades", return_value=copied_rows), \
             patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_copy_origin_source", return_value=candidates) as origin_query, \
             patch.object(app, "query_copy_followers_source", return_value={"rows": follower_rows, "sourceOrdersScanned": 1, "sourceOrdersTruncated": False, "candidateRowsTruncated": False}) as follower_query:
            payload = app.account_copy_origins_payload("700002", {"platform": "MT5", "server": "Live"})

        self.assertTrue(payload["detected"])
        self.assertEqual(payload["primaryOrigin"]["account"], "700001")
        self.assertEqual(payload["primaryOrigin"]["matchedOrders"], 1)
        self.assertEqual(payload["primaryOrigin"]["sampleOrderIds"], ["348815929"])
        self.assertEqual(payload["primaryOrigin"]["copyChannels"], ["CPT-SS"])
        self.assertEqual(len(payload["primaryOrigin"]["sourceOrders"]), 1)
        self.assertEqual(payload["primaryOrigin"]["orders"], 1)
        self.assertEqual(payload["primaryOrigin"]["copyOrderRatio"], 100)
        self.assertEqual(payload["primaryOrigin"]["followerSummary"]["accounts"], 1)
        self.assertEqual(payload["primaryOrigin"]["followerSummary"]["orders"], 1)
        self.assertEqual(payload["primaryOrigin"]["followerSummary"]["netProfit"], 11)
        self.assertEqual(payload["primaryOrigin"]["followerOrders"], follower_rows)
        self.assertTrue(payload["primaryOrigin"]["followers"][0]["isCurrentAccount"])
        origin_query.assert_called_once_with(source, ["348815929"])
        follower_query.assert_called_once_with(
            source,
            payload["primaryOrigin"]["sourceOrders"],
            copy_channels=["CPT-SS"],
        )

    def test_copy_origin_time_range_uses_opening_time_and_is_forwarded_to_followers(self):
        source = {"name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals"}
        copied_rows = [
            {"comment": "CPT-SS#100", "open_time": "2026-07-10 09:00:00"},
            {"comment": "CPT-SS#200", "open_time": "2026-07-12 09:00:00"},
        ]
        candidates = [{
            "account": "700001", "platform": "MT5", "server": "Live", "ticket": "200",
            "matchedOrderIds": ["200"], "time": "2026-07-12 09:00:00", "symbol": "XAUUSD",
        }]
        with patch.object(app, "query_db_trades", return_value=copied_rows) as trade_query, \
             patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_copy_origin_source", return_value=candidates), \
             patch.object(app, "query_copy_followers_source", return_value={"rows": []}) as follower_query:
            payload = app.account_copy_origins_payload("700101", {
                "platform": "MT5", "server": "Live", "start": "2026-07-11 00:00:00",
                "end": "2026-07-12 23:59:59",
            })

        trade_query.assert_called_once_with(
            "700101", platform="MT5", server="Live", start="2026-07-11 00:00:00",
            end="2026-07-12 23:59:59", limit=50000,
        )
        self.assertEqual(payload["copyOrders"], 1)
        self.assertEqual(payload["orderIds"], ["200"])
        follower_query.assert_called_once_with(
            source,
            payload["primaryOrigin"]["sourceOrders"],
            copy_channels=["CPT-SS"], start="2026-07-11 00:00:00", end="2026-07-12 23:59:59",
        )

    def test_signal_group_time_range_is_forwarded_to_trade_and_rebate_statistics(self):
        service = app.SignalCopyGroupService(app)
        source = {"name": "Live", "platform": "MT4", "server": "Live", "kind": "mt4_trades"}
        seed = {"account": "700102", "signalId": "42", "signalTag": "Signal #42 IN"}
        members = [{"account": "700102"}, {"account": "700103"}]
        with patch.object(service, "query_seed", return_value=seed), \
             patch.object(service, "query_members", return_value=(members, False)), \
             patch.object(service, "query_mt4_stats", return_value=([], [])) as stats_query:
            service.query_group_for_source(
                source, "700102", start="2026-07-11 00:00:00", end="2026-07-12 23:59:59",
            )

        stats_query.assert_called_once_with(
            source, members, start="2026-07-11 00:00:00", end="2026-07-12 23:59:59",
        )

    def test_copy_origin_lookup_does_not_truncate_more_than_one_thousand_open_ids(self):
        copied_rows = [{"comment": f"CPT-SS#{order_id}"} for order_id in range(1, 1202)]
        source = {"name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals"}
        with patch.object(app, "query_db_trades", return_value=copied_rows), \
             patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_copy_origin_source", return_value=[]) as origin_query:
            payload = app.account_copy_origins_payload("700099", {"platform": "MT5", "server": "Live"})

        queried_ids = origin_query.call_args.args[1]
        self.assertEqual(len(queried_ids), 1201)
        self.assertEqual(queried_ids[-1], "1201")
        self.assertEqual(payload["searchedOrders"], 1201)

    def test_copy_origin_regression_assigns_all_641903_orders_to_two_sources(self):
        copied_rows = [
            {
                "comment": f"CPT-SS#{order_id}", "type": "buy", "volume": 0.1,
                "profit": 439.89 / 625, "commission": 0, "swap": 0, "taxes": 0,
            }
            for order_id in range(1, 626)
        ] + [
            {
                "comment": f"CPT-SS#{order_id}", "type": "buy", "volume": 0.1,
                "profit": 64.43 / 270, "commission": 0, "swap": 0, "taxes": 0,
            }
            for order_id in range(626, 896)
        ]
        candidates = [
            {
                "account": "640598" if order_id <= 625 else "632824",
                "platform": "MT5", "server": "AC GB MT5", "ticket": str(order_id),
                "matchedOrderIds": [str(order_id)], "time": "2026-07-01 10:00:00",
                "symbol": "XAUUSD", "comment": "source",
            }
            for order_id in range(1, 896)
        ]
        source = {"name": "AC GB MT5", "platform": "MT5", "server": "AC GB MT5", "kind": "mt5_deals"}
        empty_discovery = {
            "rows": [], "sourceOrdersScanned": 0, "sourceOrdersTruncated": False,
            "candidateRowsTruncated": False, "queryStrategy": "exact-comment",
        }
        with patch.object(app, "query_db_trades", return_value=copied_rows), \
             patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_copy_origin_source", return_value=candidates), \
             patch.object(app, "query_copy_followers_source", return_value=empty_discovery):
            payload = app.account_copy_origins_payload(
                "641903", {"platform": "MT5", "server": "AC GB MT5"}
            )

        origins = {row["account"]: row for row in payload["origins"]}
        self.assertEqual(payload["copyOrders"], 895)
        self.assertEqual(payload["mappedCopyOrders"], 895)
        self.assertEqual(payload["unmappedCopyOrders"], 0)
        self.assertEqual(origins["640598"]["orders"], 625)
        self.assertEqual(origins["640598"]["netProfit"], 439.89)
        self.assertEqual(origins["632824"]["orders"], 270)
        self.assertEqual(origins["632824"]["netProfit"], 64.43)

    def test_copy_origin_source_batches_large_id_sets(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [[], [], []]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals",
            "schema": "live", "table": "mt5_deals",
        }

        with patch.object(app, "mysql_trade_connect", return_value=connection):
            rows = app.query_copy_origin_source(source, [str(value) for value in range(1, 1002)])

        self.assertEqual(rows, [])
        self.assertEqual(cursor.execute.call_count, 3)
        self.assertEqual([len(call.args[1]) for call in cursor.execute.call_args_list], [500, 500, 1])

    def test_copy_follower_query_scans_all_source_orders_with_exact_comments(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{
                "Deal": 1, "Login": 700002, "PositionID": 9001, "Time": "2026-07-01 10:00:01",
                "Action": 0, "Entry": 0, "Symbol": "XAUUSD", "Comment": "CPT-SS#1",
            }],
            [{"Login": 700002, "AccountGroup": "Standard"}],
            [{
                "Login": 700002, "PositionID": 9001, "OpenTime": "2026-07-01 10:00:01",
                "CloseTime": "2026-07-01 10:01:01", "Symbol": "XAUUSD", "OpenVolume": 10000,
                "GrossProfit": 12, "CommissionFee": -1, "Swap": 0,
            }],
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals",
            "schema": "live", "table": "mt5_deals", "default_currency": "USD",
        }
        source_orders = [
            {"orderId": str(value), "time": "2026-07-01 10:00:00"}
            for value in range(1, 202)
        ]

        with patch.object(app, "mysql_trade_connect", return_value=connection):
            result = app.query_copy_followers_source(source, source_orders, copy_channels=["CPT-SS"])

        self.assertEqual(result["sourceOrdersScanned"], 201)
        self.assertFalse(result["sourceOrdersTruncated"])
        self.assertFalse(result["candidateRowsTruncated"])
        self.assertEqual(result["queryStrategy"], "exact-comment")
        self.assertEqual(result["rows"][0]["netProfit"], 11)
        self.assertEqual(result["rows"][0]["ticket"], "9001")
        self.assertEqual(result["rows"][0]["orders"], 1)
        self.assertIn("Comment in", cursor.execute.call_args_list[0].args[0])

    def test_copy_source_windows_are_hour_bounded_and_limited(self):
        orders = [
            {"orderId": "100", "time": "2026-07-01 10:00:00"},
            {"orderId": "101", "time": "2026-07-01 10:30:00"},
            {"orderId": "102", "time": "2026-07-01 11:00:00"},
        ]
        windows, truncated = app._copy_source_windows(orders, limit=2)

        self.assertTrue(truncated)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0][2], {"100", "101"})
        self.assertEqual(windows[0][0].strftime("%H:%M:%S"), "09:55:00")
        self.assertEqual(windows[0][1].strftime("%H:%M:%S"), "10:35:00")

    def test_copy_origin_lookup_lists_each_source_with_ratio_and_profit(self):
        copied_rows = [
            {"comment": "CPT-SS#100", "type": "buy", "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00", "volume": 1, "profit": 10, "commission": -1},
            {"comment": "CPT-SS#200", "type": "sell", "open_time": "2026-07-01 11:00:00", "close_time": "2026-07-01 11:01:00", "volume": 2, "profit": -5, "commission": -1},
            {"comment": "manual", "type": "buy", "open_time": "2026-07-01 12:00:00", "close_time": "2026-07-01 12:01:00", "volume": 1, "profit": 20},
        ]
        source = {"name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals"}
        candidates = [
            {"account": "6002742", "platform": "MT5", "server": "Live", "ticket": "100", "matchedOrderIds": ["100"], "time": "2026-07-01 10:00:00", "symbol": "XAUUSD", "comment": "source a"},
            {"account": "6003000", "platform": "MT5", "server": "Live", "ticket": "200", "matchedOrderIds": ["200"], "time": "2026-07-01 11:00:00", "symbol": "EURUSD", "comment": "source b"},
        ]
        with patch.object(app, "query_db_trades", return_value=copied_rows), \
             patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_copy_origin_source", return_value=candidates):
            payload = app.account_copy_origins_payload("700005", {"platform": "MT5", "server": "Live"})

        by_account = {row["account"]: row for row in payload["origins"]}
        self.assertEqual(set(by_account), {"6002742", "6003000"})
        self.assertEqual(payload["copyOrders"], 2)
        self.assertEqual(payload["totalOrders"], 3)
        self.assertEqual(payload["mappedCopyOrders"], 2)
        self.assertAlmostEqual(by_account["6002742"]["orderRatio"], 33.33, places=2)
        self.assertEqual(by_account["6002742"]["copyOrderRatio"], 50)
        self.assertEqual(by_account["6002742"]["volumeRatio"], 25)
        self.assertEqual(by_account["6002742"]["netProfit"], 9)
        self.assertEqual(by_account["6003000"]["volumeRatio"], 50)
        self.assertEqual(by_account["6003000"]["netProfit"], -6)

    def test_automation_analysis_reports_copy_and_ea_ratios_and_profit(self):
        rows = [
            {"ticket": "1", "type": "buy", "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00", "volume": 1, "profit": 100, "commission": -2, "swap": -1, "taxes": 0, "comment": "CPT-SS#9001", "platform": "MT5", "server": "Live", "symbol": "XAUUSD"},
            {"ticket": "2", "type": "sell", "open_time": "2026-07-01 11:00:00", "close_time": "2026-07-01 11:01:00", "volume": 2, "profit": -40, "commission": -1, "swap": 0, "taxes": 0, "reason": "Expert", "expert_id": "77", "comment": "robot", "platform": "MT5", "server": "Live", "symbol": "EURUSD"},
            {"ticket": "3", "type": "buy", "open_time": "2026-07-01 12:00:00", "close_time": "2026-07-01 12:01:00", "volume": 1, "profit": 10, "commission": 0, "swap": 0, "taxes": 0, "comment": "manual", "platform": "MT5", "server": "Live", "symbol": "EURUSD"},
        ]
        origins = {"origins": [{"account": "700001", "platform": "MT5", "server": "Live", "sampleOrderIds": ["9001"], "matchedOrderIds": ["9001"]}], "errors": []}
        with patch.object(app, "query_db_trades", return_value=rows), \
             patch.object(app, "account_signal_copy_seeds", return_value=([], [])), \
             patch.object(app, "account_copy_origins_payload", return_value=origins):
            payload = app.account_automation_payload("700002", {"platform": "MT5", "server": "Live"})

        self.assertEqual(payload["totalOrders"], 3)
        self.assertEqual(payload["copy"]["orders"], 1)
        self.assertAlmostEqual(payload["copy"]["orderRatio"], 33.33, places=2)
        self.assertAlmostEqual(payload["copy"]["volumeRatio"], 25.0, places=2)
        self.assertEqual(payload["copy"]["netProfit"], 97)
        self.assertEqual(payload["copy"]["origins"][0]["account"], "700001")
        self.assertEqual(payload["copy"]["origins"][0]["netProfit"], 97)
        self.assertEqual(payload["ea"]["orders"], 1)
        self.assertEqual(payload["ea"]["groups"][0]["expertId"], "77")
        self.assertEqual(payload["ea"]["groups"][0]["netProfit"], -41)

    def test_automation_analysis_returns_empty_sections_without_automation(self):
        rows = [{"ticket": "1", "type": "buy", "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00", "volume": 1, "profit": 5, "comment": "manual"}]
        with patch.object(app, "query_db_trades", return_value=rows), \
             patch.object(app, "account_signal_copy_seeds", return_value=([], [])):
            payload = app.account_automation_payload("700003")
        self.assertFalse(payload["copy"]["detected"])
        self.assertFalse(payload["ea"]["detected"])
        self.assertEqual(payload["copy"]["origins"], [])
        self.assertEqual(payload["ea"]["groups"], [])

    def test_signal_account_treats_mt4_magic_as_copy_source_ticket_not_ea(self):
        rows = [
            {"ticket": "15471550", "type": "buy", "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00", "volume": 0.2, "profit": 3.4, "expert_id": "15471548", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD"},
            {"ticket": "15471543", "type": "sell", "open_time": "2026-07-01 11:00:00", "close_time": "2026-07-01 11:01:00", "volume": 0.2, "profit": -1, "expert_id": "15471541", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD"},
        ]
        seeds = [{"signalId": "5009780", "signalTag": "Signal #5009780 IN", "platform": "MT4", "server": "AC MT4"}]
        with patch.object(app, "query_db_trades", return_value=rows), \
             patch.object(app, "account_signal_copy_seeds", return_value=(seeds, [])), \
             patch.object(app, "account_copy_origins_payload", return_value={"origins": [], "errors": []}):
            payload = app.account_automation_payload("700004", {"platform": "MT4", "server": "AC MT4"})
        self.assertEqual(payload["copy"]["orders"], 2)
        self.assertEqual(payload["copy"]["origins"][0]["account"], "Signal #5009780 IN")
        self.assertEqual(payload["ea"]["orders"], 0)
        self.assertEqual(payload["ea"]["groups"], [])

    def test_signal_in_comment_parser_accepts_spacing_and_case(self):
        self.assertEqual(app.signal_in_identifier("Signal #5009780 IN"), "5009780")
        self.assertEqual(app.signal_in_identifier(" signal  #  ABC_12  in "), "ABC_12")
        self.assertEqual(app.signal_in_tag("Signal #5009780 IN extra"), "Signal #5009780 IN")
        self.assertEqual(app.signal_in_identifier("manual account"), "")

    def test_ea_comment_parser_keeps_ea_and_route_comments_but_rejects_system_comments(self):
        self.assertEqual(app.ea_comment_parts("ChanGold V33 / tp"), ["ChanGold V33"])
        self.assertEqual(app.ea_comment_parts("KLine_Breakout[tp]"), ["KLine_Breakout"])
        self.assertEqual(app.ea_comment_parts("AlphaBot / AlphaBot"), ["AlphaBot"])
        self.assertEqual(app.ea_comment_parts("@8@44968558@7"), ["@8@44968558@7"])
        self.assertEqual(app.ea_comment_parts("@8@44968558@7[tp]"), ["@8@44968558@7"])
        identity = app.ea_comment_identity("@8@44968558@7", 7)
        self.assertEqual(identity["comment"], "@8@44968558@7")
        self.assertEqual(identity["signatureType"], "exact-comment")
        self.assertEqual(identity["classification"], "possible_copy_route")
        self.assertEqual(identity["normalizedTemplate"], "@8@{SOURCE_ID}@7")
        self.assertFalse(identity["countedAsEa"])
        self.assertEqual(app.ea_comment_parts("EA"), [])
        self.assertEqual(app.ea_comment_parts("CPT-SS#348815929"), ["CPT-SS#348815929"])
        self.assertEqual(app.ea_comment_parts("Signal #5009780 IN"), ["Signal #5009780 IN"])
        self.assertEqual(app.ea_comment_parts("from #27060824"), [])
        self.assertEqual(app.ea_comment_parts("[tp 4029.00]"), [])
        self.assertEqual(app.ea_comment_parts("[sl 4031.50]"), [])
        self.assertEqual(app.ea_comment_parts("[so 20%]"), [])

    def test_ea_comment_classifier_covers_known_dynamic_and_route_families(self):
        route_cases = {
            "CPT-SS#353764633": "CPT-SS#{SOURCE_ID}",
            "CPT #353764633": "CPT #{SOURCE_ID}",
            "@14@95002113@19": "@14@{SOURCE_ID}@19",
            "1/521/58439466": "1/521/{SOURCE_ID}",
            "9200768-58436291": "9200768-{SOURCE_ID}",
        }
        for comment, template in route_cases.items():
            with self.subTest(comment=comment):
                result = app.classify_ea_comment(comment, ea_hint=True)
                self.assertEqual(result["classification"], "possible_copy_route")
                self.assertEqual(result["classificationLabel"], "可能是跟单路由")
                self.assertEqual(result["normalizedTemplate"], template)
                self.assertFalse(result["countedAsEa"])

        dynamic_cases = {
            "B1:743494061": "B1:{ORDER_REF}",
            "EAName{743494061}": "EAName{{ORDER_REF}}",
            "RST_RESTART_S_134567": "RST_RESTART_{SIDE}_{INSTANCE}",
            "DCA_GOLD_134567": "DCA_GOLD_{INSTANCE}",
            "VTRADE Alpha [CID=33]": "VTRADE Alpha [CID={CLIENT}]",
            "BuyOrder#3": "BuyOrder#{LEVEL}",
            "BR01": "BR{LEVEL}",
            "SR02": "SR{LEVEL}",
            "Grid_12": "Grid_{LEVEL}",
        }
        for comment, template in dynamic_cases.items():
            with self.subTest(comment=comment):
                result = app.classify_ea_comment(comment, ea_hint=True)
                self.assertEqual(result["classification"], "dynamic_ea")
                self.assertEqual(result["normalizedTemplate"], template)
                self.assertTrue(result["countedAsEa"])

    def test_ea_comment_classifier_excludes_platform_events_and_contact_only_comments(self):
        for comment in (
            "[sl 4031.50]", "[tp 4029.00]", "[so 20%]", "so: 49.8%/50.0%",
            "from #27060824", "to #27060825", "deposit", "withdrawal", "credit",
            "manual",
        ):
            with self.subTest(comment=comment):
                self.assertEqual(
                    app.classify_ea_comment(comment, ea_hint=True)["classification"],
                    "system_excluded",
                )

    def test_ea_comment_classifier_keeps_pure_contact_comment_as_exact_ea(self):
        for comment in ("QQ: 123456789", "微信: 13800138000", "WhatsApp: +852 1234 5678"):
            with self.subTest(comment=comment):
                result = app.classify_ea_comment(comment)
                self.assertEqual(result["classification"], "exact_ea")
                self.assertTrue(result["countedAsEa"])
                self.assertEqual(result["normalizedComment"], comment)

    def test_ea_comment_classifier_keeps_meaningful_chinese_comment_when_mt5_marks_expert(self):
        result = app.classify_ea_comment("手动下单3", ea_hint=True)

        self.assertEqual(result["classification"], "exact_ea")
        self.assertTrue(result["countedAsEa"])
        self.assertIn("Comment", result["classificationEvidence"])

    def test_ea_groups_keep_the_current_account_when_no_comment_peer_exists(self):
        runtime = SimpleNamespace(
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
        )
        service = app.EaCommentGroupService(runtime)
        seed = {
            **app.ea_comment_identity("手动下单3", 103899, ea_hint=True),
            "originDatabase": "AC", "originPlatform": "MT5", "originServer": "AC CN MT5",
            "currentOrders": 1, "currentVolume": 0.16, "currentNetProfit": -8.96,
        }
        record = {
            "signatureKey": seed["signatureKey"], "account": "247026", "comment": "手动下单3",
            "database": "AC", "platform": "MT5", "server": "AC CN MT5", "source": "AC CN MT5",
            "ticket": "744751865", "symbol": "XAUUSD", "openTime": "2026-08-13 06:08:48",
            "closeTime": "2026-08-13 06:09:05", "volume": 0.16, "grossProfit": -8.96,
            "commission": 0, "swap": 0, "taxes": 0, "netProfit": -8.96, "currency": "USD",
            "isCentAccount": False, "matchedExpertId": 103899,
            "matchClue": "同服务器：Comment「手动下单3」相同，ExpertID 103899 相同",
        }

        groups = service._build_groups([seed], [record], "247026", source={"platform": "MT5", "server": "AC CN MT5"})

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["members"][0]["account"], "247026")
        self.assertEqual(groups[0]["peerAccounts"], 0)
        self.assertTrue(any("尚未找到其他账号" in item for item in groups[0]["limitations"]))

    def test_ea_match_evidence_uses_comment_on_same_server_and_keeps_expert_as_evidence(self):
        seed = {
            **app.ea_comment_identity("GOLDFORGE", 777555),
            "originPlatform": "MT5",
            "originServer": "AC GB MT5",
        }

        same_server = app.ea_match_evidence(
            seed, {"platform": "MT5", "server": "AC GB MT5"}, 777555,
        )
        self.assertEqual(
            same_server["matchClue"],
            "同服务器：Comment「GOLDFORGE」相同（ExpertID 777555）",
        )
        different_expert = app.ea_match_evidence(
            seed, {"platform": "MT5", "server": "AC GB MT5"}, 777000,
        )
        self.assertEqual(
            different_expert["matchClue"],
            "同服务器：Comment「GOLDFORGE」相同（ExpertID 777000）",
        )

        cross_server = app.ea_match_evidence(
            seed, {"platform": "MT5", "server": "DBG CN MT5"}, 123456,
        )
        self.assertEqual(cross_server["matchClue"], "跨服务器：Comment「GOLDFORGE」相同")
        self.assertEqual(cross_server["matchedExpertId"], 123456)

        mt4_seed = {
            **app.ea_comment_identity("GoldBot", 42),
            "originPlatform": "MT4",
            "originServer": "DBG MT4 CN1",
        }
        mt4_match = app.ea_match_evidence(
            mt4_seed, {"platform": "MT4", "server": "DBG MT4 CN1"}, 42,
        )
        self.assertIn("MAGIC 42", mt4_match["matchClue"])

    def test_ea_groups_aggregate_one_comment_across_expert_ids(self):
        runtime = SimpleNamespace(
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
        )
        service = app.EaCommentGroupService(runtime)
        seed_a = {
            **app.ea_comment_identity("手动下单3", 119713, ea_hint=True),
            "originDatabase": "AC", "originPlatform": "MT5", "originServer": "AC CN MT5",
        }
        seed_b = {
            **app.ea_comment_identity("手动下单3", 103899, ea_hint=True),
            "originDatabase": "DBG", "originPlatform": "MT5", "originServer": "DBG CN MT5",
        }
        def record(account, expert_id, profit):
            return {
                "signatureKey": seed_a["signatureKey"], "account": account, "comment": "手动下单3",
                "database": "AC", "platform": "MT5", "server": "AC CN MT5", "source": "AC CN MT5",
                "ticket": str(expert_id), "symbol": "XAUUSD", "openTime": "2026-08-13 06:08:48",
                "closeTime": "2026-08-13 06:09:05", "volume": 0.16, "grossProfit": profit,
                "commission": 0, "swap": 0, "taxes": 0, "netProfit": profit, "currency": "USD",
                "isCentAccount": False, "matchedExpertId": expert_id,
                "matchClue": f"同服务器：Comment「手动下单3」相同（ExpertID {expert_id}）",
            }
        groups = service._build_groups(
            [seed_a, seed_b],
            [record("247026", 119713, 3.68), record("201234", 103899, 8.12)],
            "247026", source={"platform": "MT5", "server": "AC CN MT5"},
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["comment"], "手动下单3")
        self.assertEqual(groups[0]["totals"]["accounts"], 2)
        self.assertEqual({row["account"] for row in groups[0]["members"]}, {"247026", "201234"})
        self.assertEqual(groups[0]["peerAccounts"], 1)

    def test_exact_comment_seeds_and_targets_cross_mt4_mt5_boundaries(self):
        runtime = SimpleNamespace(
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            MYSQL_SOURCES=[
                {"name": "AC MT4", "platform": "MT4", "kind": "mt4_trades", "host": "ac", "schema": "mt4", "table": "trades", "account_route": {"schema": "crm", "mt_server_code": 1}},
                {"name": "DBG MT5", "platform": "MT5", "kind": "mt5_deals", "host": "dbg", "schema": "mt5", "table": "deals", "account_route": {"schema": "crm", "mt_server_code": 2}},
            ],
        )
        service = app.EaCommentGroupService(runtime)
        mt4_seed = {**app.ea_comment_identity("QQ: 123456789", 42), "originPlatform": "MT4", "originServer": "AC MT4"}
        mt5_seed = {**app.ea_comment_identity("QQ: 123456789", 77), "originPlatform": "MT5", "originServer": "DBG MT5"}

        merged = service._merge_seeds([mt4_seed, mt5_seed])

        self.assertEqual(len(merged), 1)
        self.assertEqual({source["platform"] for source in service._exact_target_sources()}, {"MT4", "MT5"})

    def test_global_exact_comment_lookup_has_parallel_source_budget(self):
        self.assertGreaterEqual(ea_comment_group._GLOBAL_COMMENT_QUERY_MAX_WORKERS, 8)

    def test_ea_dynamic_numeric_comment_query_uses_indexable_prefix_pattern(self):
        exact, dynamic = app.ea_comment_query_plan([
            "ChanGold V33", "@8@44968558@7", "@8@44968558@7",
        ])

        self.assertEqual(exact, [
            "ChanGold V33", "ChanGold V33[tp]", "ChanGold V33[sl]", "ChanGold V33[so]",
            "@8@44968558@7", "@8@44968558@7[tp]", "@8@44968558@7[sl]", "@8@44968558@7[so]",
        ])
        self.assertEqual(dynamic, ["@8@{SOURCE_ID}@7"])

    def test_ea_expert_sequence_requires_complete_ids_and_conservative_overlap(self):
        base = datetime(2026, 6, 30, 20, 0, 0)

        def events(expert_ids, account, *, shift_seconds=0, action=0):
            return [{
                "account": account,
                "positionId": f"{account}-{index}",
                "expertId": expert_id,
                "openTime": base + timedelta(seconds=index * 70 + shift_seconds),
                "symbol": "XAUUSD",
                "action": action,
            } for index, expert_id in enumerate(expert_ids)]

        seed_ids = [15783001, 15783009, 15783017, 15783025, 15783033, 15783041]
        seed = events(seed_ids, "2014201")
        exact_peer = events(seed_ids, "2014202", shift_seconds=1)
        matched = app.ea_expert_sequence_match(seed, exact_peer)

        self.assertIsNotNone(matched)
        self.assertEqual(matched["sharedCount"], 6)
        self.assertEqual(matched["seedOverlap"], 1)
        self.assertEqual(matched["candidateOverlap"], 1)

        same_prefix_only = events([15799001, 15799009, 15799017, 15799025, 15799033, 15799041], "2014999")
        self.assertIsNone(app.ea_expert_sequence_match(seed, same_prefix_only))
        self.assertIsNone(app.ea_expert_sequence_match(seed, events(seed_ids[:4], "2014998")))
        self.assertIsNone(app.ea_expert_sequence_match(seed, events(seed_ids, "2014997", action=1)))

        diluted_peer = [
            *exact_peer,
            *events([15800001, 15800002], "2014202", shift_seconds=10),
        ]
        self.assertIsNone(app.ea_expert_sequence_match(seed, diluted_peer))

    def test_ea_expert_sequence_rejects_one_time_batch_even_with_five_shared_ids(self):
        opened = datetime(2026, 6, 30, 20, 0, 0)
        seed = [{
            "account": "1", "positionId": f"s-{index}", "expertId": 15783000 + index,
            "openTime": opened, "symbol": "XAUUSD", "action": 0,
        } for index in range(5)]
        candidate = [{
            **event, "account": "2", "positionId": f"c-{index}",
        } for index, event in enumerate(seed)]

        self.assertIsNone(app.ea_expert_sequence_match(seed, candidate))

    def test_ea_exact_route_payload_is_kept_visible_and_excluded_from_ea_summary(self):
        sources = [
            {
                "name": "AC CN MT5", "platform": "MT5", "server": "AC CN MT5", "kind": "mt5_deals",
                "schema": "sass_crm_ac_mt5_live", "table": "mt5_deals", "host": "ac",
            },
            {
                "name": "DBG MT5", "platform": "MT5", "server": "DBG CN MT5", "kind": "mt5_deals",
                "schema": "mt5_export_new", "table": "mt5_deals", "host": "dbg",
            },
        ]
        runtime = SimpleNamespace(
            MYSQL_SOURCES=sources,
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
            is_ea_trade=lambda _row: True,
            is_copy_trade=lambda _row: False,
            source_allowed=lambda source, platform="", server="": not server or server in {source["name"], source["server"]},
            query_db_trades=lambda *_args, **_kwargs: [{
                "platform": "MT5", "server": "DBG CN MT5", "comment": "@8@48972818@7",
                "expert_id": "7", "volume": 0.1, "profit": 1,
                "open_time": "2026-07-06", "close_time": "2026-07-21",
            }],
            now_text=lambda: "2026-07-22 10:00:00",
        )
        service = app.EaCommentGroupService(runtime)

        def fake_mt5(source, seeds, _row_limit):
            accounts = ["201518", "221698", "207357", "201628", "33553"] if source["name"].startswith("AC") else [
                "2013674", "2014359", "2014169", "2013651",
            ]
            records = [{
                "database": "AC" if source["name"].startswith("AC") else "DBG",
                "platform": "MT5", "server": source["server"], "source": source["name"],
                "account": account, "comment": seeds[0]["comment"], "ticket": f"{index}",
                "volume": 0.1, "grossProfit": 1, "commission": 0, "swap": 0, "taxes": 0,
                "netProfit": 1, "currency": "USD", "openTime": "2026-07-01", "closeTime": "2026-07-02",
            } for index, account in enumerate(accounts, 1)]
            return records, False, []

        with patch.object(service, "_query_mt5", side_effect=fake_mt5):
            payload = service.payload("2013674", {"platform": "MT5", "server": "DBG CN MT5"})

        self.assertEqual(len(payload["groups"]), 1)
        group = payload["groups"][0]
        self.assertEqual(group["comment"], "@8@48972818@7")
        self.assertEqual(group["classificationLabel"], "可能是跟单路由")
        self.assertFalse(group["countedAsEa"])
        self.assertEqual(group["databases"], ["AC", "DBG"])
        self.assertEqual(group["totals"]["accounts"], 9)
        self.assertEqual(payload["eaSummary"]["groups"], 0)
        self.assertEqual(payload["possibleCopyRouteSummary"]["groups"], 1)
        self.assertEqual({row["account"] for row in group["members"]}, {
            "2013674", "2014359", "2014169", "2013651", "201518", "221698", "207357", "201628", "33553",
        })

    def test_ea_payload_runs_dynamic_format_only_after_successful_empty_exact_lookup(self):
        source = {
            "name": "DBG CN MT5", "platform": "MT5", "server": "DBG CN MT5", "kind": "mt5_deals",
            "schema": "mt5_export_new", "table": "mt5_deals", "host": "dbg",
        }
        runtime = SimpleNamespace(
            MYSQL_SOURCES=[source],
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
            is_ea_trade=lambda _row: True,
            is_copy_trade=lambda _row: False,
            source_allowed=lambda *_args, **_kwargs: True,
            query_db_trades=lambda *_args, **_kwargs: [{
                "platform": "MT5", "server": "DBG CN MT5", "comment": "B1:743494061",
                "expert_id": "77", "volume": 0.1, "profit": 1,
                "open_time": "2026-07-01", "close_time": "2026-07-02",
            }],
            now_text=lambda: "2026-07-24 10:00:00",
        )
        service = app.EaCommentGroupService(runtime)
        stages = []

        def fake_mt5(_source, seeds, _row_limit):
            stages.append(seeds[0]["signatureType"])
            if seeds[0]["signatureType"] == "exact-comment":
                return [], False, []
            records = [{
                "database": "DBG", "platform": "MT5", "server": "DBG CN MT5", "source": "DBG CN MT5",
                "account": account, "comment": seeds[0]["comment"], "signatureKey": seeds[0]["signatureKey"],
                "ticket": ticket, "volume": 0.1, "grossProfit": 2, "commission": 0, "swap": 0,
                "taxes": 0, "netProfit": 2, "currency": "USD", "openTime": "2026-07-01",
                "closeTime": "2026-07-02", "matchedExpertId": 77, "matchClue": "动态模板匹配",
            } for account, ticket in (("700001", "1"), ("700002", "2"))]
            return records, False, []

        with patch.object(service, "_query_mt5", side_effect=fake_mt5):
            payload = service.payload("700001", {"platform": "MT5", "server": "DBG CN MT5"})

        self.assertEqual(stages, ["exact-comment", "dynamic-template"])
        self.assertEqual(payload["groups"][0]["comment"], "B1:{ORDER_REF}")
        self.assertEqual(payload["groups"][0]["classification"], "dynamic_ea")
        self.assertTrue(payload["groups"][0]["countedAsEa"])
        self.assertEqual(payload["eaSummary"]["netProfit"], 4)

    def test_ea_payload_passes_open_time_range_to_subject_and_peer_queries(self):
        source = {
            "name": "DBG CN MT5", "platform": "MT5", "server": "DBG CN MT5", "kind": "mt5_deals",
            "schema": "mt5_export_new", "table": "mt5_deals", "host": "dbg",
        }
        query_db_trades = MagicMock(return_value=[{
            "platform": "MT5", "server": "DBG CN MT5", "comment": "ChanGold V33",
            "expert_id": "77", "volume": 0.1, "profit": 1,
            "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 11:00:00",
        }])
        runtime = SimpleNamespace(
            MYSQL_SOURCES=[source],
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
            is_ea_trade=lambda _row: True,
            is_copy_trade=lambda _row: False,
            source_allowed=lambda *_args, **_kwargs: True,
            query_db_trades=query_db_trades,
            now_text=lambda: "2026-07-24 10:00:00",
        )
        service = app.EaCommentGroupService(runtime)
        observed_scopes = []

        def fake_mt5(_source, seeds, _row_limit):
            observed_scopes.extend((seed.get("scopeStart"), seed.get("scopeEnd")) for seed in seeds)
            return [], False, []

        with patch.object(service, "_query_mt5", side_effect=fake_mt5):
            service.payload("700001", {
                "platform": "MT5", "server": "DBG CN MT5",
                "start": "2026-07-01 00:00:00", "end": "2026-07-02 23:59:59",
            })

        query_db_trades.assert_called_once_with(
            "700001", platform="MT5", server="DBG CN MT5",
            start="2026-07-01 00:00:00", end="2026-07-02 23:59:59", limit=50000,
        )
        self.assertEqual(observed_scopes, [("2026-07-01 00:00:00", "2026-07-02 23:59:59")])

    def test_ea_payload_does_not_fallback_after_exact_provider_error(self):
        source = {
            "name": "DBG CN MT5", "platform": "MT5", "server": "DBG CN MT5", "kind": "mt5_deals",
            "schema": "mt5_export_new", "table": "mt5_deals", "host": "dbg",
        }
        runtime = SimpleNamespace(
            MYSQL_SOURCES=[source],
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
            is_ea_trade=lambda _row: True,
            is_copy_trade=lambda _row: False,
            source_allowed=lambda *_args, **_kwargs: True,
            query_db_trades=lambda *_args, **_kwargs: [{
                "platform": "MT5", "server": "DBG CN MT5", "comment": "B1:743494061",
                "expert_id": "77", "volume": 0.1, "profit": 1,
                "open_time": "2026-07-01", "close_time": "2026-07-02",
            }],
            now_text=lambda: "2026-07-24 10:00:00",
        )
        service = app.EaCommentGroupService(runtime)
        with patch.object(service, "_query_mt5", side_effect=RuntimeError("provider timeout")) as query:
            payload = service.payload("700001", {"platform": "MT5", "server": "DBG CN MT5"})

        self.assertEqual(query.call_count, 1)
        self.assertEqual(payload["groups"], [])
        self.assertIn("provider timeout", payload["errors"][0])

    def test_ea_unknown_dynamic_format_is_persisted_in_local_pattern_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = SimpleNamespace(
                EA_PATTERN_DB_PATH=Path(temp_dir) / "ea-patterns.sqlite",
                normalize_text=lambda value: str(value or "").strip(),
                numeric_value=lambda value: float(value or 0),
                rounded=lambda value, digits=2: round(float(value or 0), digits),
                mysql_datetime_text=lambda value: str(value or ""),
                is_ea_trade=lambda _row: True,
                is_copy_trade=lambda _row: False,
                now_text=lambda: "2026-07-24 10:00:00",
            )
            service = app.EaCommentGroupService(runtime)
            rows = [{
                "comment": "NovelAlpha_93847561", "expert_id": "88", "volume": 0.1, "profit": 1,
                "open_time": "2026-07-01", "close_time": "2026-07-02",
            }]
            seeds = service._seed_comments(rows)
            connection = app.sqlite3.connect(runtime.EA_PATTERN_DB_PATH)
            try:
                learned = connection.execute(
                    "select normalized_template, classification, observations from learned_ea_comment_patterns"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(seeds[0]["normalizedTemplate"], "NovelAlpha_{ID}")
        self.assertEqual(learned, ("NovelAlpha_{ID}", "dynamic_ea", 1))

    def test_ea_payload_runs_dynamic_matching_only_after_successful_empty_exact_lookup(self):
        source = {
            "name": "DBG CN MT5", "platform": "MT5", "server": "DBG CN MT5", "kind": "mt5_deals",
            "schema": "mt5_export_new", "table": "mt5_deals", "host": "dbg",
        }
        runtime = SimpleNamespace(
            MYSQL_SOURCES=[source],
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
            is_ea_trade=lambda _row: False,
            is_copy_trade=lambda _row: False,
            source_allowed=lambda _source, platform="", server="": True,
            query_db_trades=lambda *_args, **_kwargs: [{
                "platform": "MT5", "server": "DBG CN MT5", "comment": "1/521/58439466",
                "expert_id": "58439466", "volume": 0.1, "profit": 1,
                "open_time": "2026-07-01", "close_time": "2026-07-02",
            }],
            now_text=lambda: "2026-07-24 10:00:00",
        )
        service = app.EaCommentGroupService(runtime)
        stages = []

        def fake_mt5(_source, seeds, _row_limit):
            stages.append(seeds[0]["signatureType"])
            if seeds[0]["signatureType"] == "exact-comment":
                return [], False, []
            records = [{
                "database": "DBG", "platform": "MT5", "server": "DBG CN MT5", "source": "DBG CN MT5",
                "account": account, "comment": seeds[0]["comment"], "signatureKey": seeds[0]["signatureKey"],
                "ticket": ticket, "volume": 0.1, "grossProfit": 2, "commission": 0, "swap": 0,
                "taxes": 0, "netProfit": 2, "currency": "USD", "openTime": "2026-07-01",
                "closeTime": "2026-07-02", "matchClue": "动态模板匹配", "matchedExpertId": 0,
            } for account, ticket in (("700001", "1"), ("700002", "2"))]
            return records, False, []

        with patch.object(service, "_query_mt5", side_effect=fake_mt5):
            payload = service.payload("700001", {"platform": "MT5", "server": "DBG CN MT5"})

        self.assertEqual(stages, ["exact-comment", "dynamic-template"])
        self.assertEqual(payload["groups"][0]["comment"], "1/521/{SOURCE_ID}")
        self.assertFalse(payload["groups"][0]["countedAsEa"])

    def test_ea_payload_does_not_fallback_when_exact_provider_fails(self):
        source = {
            "name": "DBG CN MT5", "platform": "MT5", "server": "DBG CN MT5", "kind": "mt5_deals",
            "schema": "mt5_export_new", "table": "mt5_deals", "host": "dbg",
        }
        runtime = SimpleNamespace(
            MYSQL_SOURCES=[source],
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
            is_ea_trade=lambda _row: False,
            is_copy_trade=lambda _row: False,
            source_allowed=lambda _source, platform="", server="": True,
            query_db_trades=lambda *_args, **_kwargs: [{
                "platform": "MT5", "server": "DBG CN MT5", "comment": "@14@95002113@19",
                "expert_id": "19", "volume": 0.1, "profit": 1,
                "open_time": "2026-07-01", "close_time": "2026-07-02",
            }],
            now_text=lambda: "2026-07-24 10:00:00",
        )
        service = app.EaCommentGroupService(runtime)
        with patch.object(service, "_query_mt5", side_effect=RuntimeError("provider unavailable")) as query:
            payload = service.payload("700001", {"platform": "MT5", "server": "DBG CN MT5"})

        self.assertEqual(query.call_count, 1)
        self.assertEqual(payload["groups"], [])
        self.assertIn("provider unavailable", payload["errors"][0])

    def test_ea_unknown_dynamic_format_is_learned_in_local_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ea_patterns.sqlite"
            runtime = SimpleNamespace(
                EA_PATTERN_DB_PATH=path,
                normalize_text=lambda value: str(value or "").strip(),
                numeric_value=lambda value: float(value or 0),
                rounded=lambda value, digits=2: round(float(value or 0), digits),
                mysql_datetime_text=lambda value: str(value or ""),
                is_ea_trade=lambda _row: True,
                is_copy_trade=lambda _row: False,
                now_text=lambda: "2026-07-24 10:00:00",
            )
            service = app.EaCommentGroupService(runtime)
            seeds = service._seed_comments([{
                "comment": "NovaAlpha_987654321", "expert_id": "77", "volume": 0.1,
                "profit": 1, "open_time": "2026-07-01", "close_time": "2026-07-02",
            }])
            connection = app.sqlite3.connect(path)
            try:
                learned = connection.execute(
                    "select normalized_template, classification, observations from learned_ea_comment_patterns"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(seeds[0]["normalizedTemplate"], "NovaAlpha_{ID}")
        self.assertEqual(learned, ("NovaAlpha_{ID}", "dynamic_ea", 1))

    def test_ea_dynamic_ac_discovery_uses_two_digit_index_shards(self):
        runtime = SimpleNamespace()
        service = app.EaCommentGroupService(runtime)
        patterns = service._dynamic_discovery_patterns({"schema": "sass_crm_ac_mt5_live"}, "@8@")

        self.assertEqual(len(patterns), 110)
        self.assertIn("@8@00%", patterns)
        self.assertIn("@8@99%", patterns)
        self.assertIn("@8@7@%", patterns)

    def test_ea_dynamic_sql_uses_mysql_safe_like_escape(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        runtime = SimpleNamespace(mysql_trade_connect=lambda _source: connection)
        service = app.EaCommentGroupService(runtime)
        seed = app.ea_dynamic_identity(app.ea_comment_identity("DCA_GOLD_134567", 77))
        pattern = service._dynamic_discovery_patterns({"schema": "mt5_export_new"}, seed["stablePrefix"])

        service._query_dynamic_pattern_batch(
            {"schema": "mt5_export_new", "table": "mt5_deals"}, pattern, seed,
        )

        sql, parameters = cursor.execute.call_args.args
        self.assertIn("escape '!'", sql)
        self.assertEqual(parameters[0], "DCA!_GOLD!_%")
        self.assertEqual(parameters[1], 77)

    def test_ea_mt5_exact_query_scopes_matching_positions_by_open_time(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        runtime = SimpleNamespace(
            mysql_trade_connect=lambda _source: connection,
            parse_trade_time=lambda value: datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S"),
            normalize_text=lambda value: str(value or "").strip(),
        )
        service = app.EaCommentGroupService(runtime)

        service._query_mt5(
            {"schema": "mt5_export_new", "table": "mt5_deals"},
            [{
                "comment": "ChanGold V33", "signatureKey": "exact:test", "scopeStart": "2026-07-01 00:00:00",
                "scopeEnd": "2026-07-02 23:59:59",
            }],
            50000,
        )

        sql, parameters = cursor.execute.call_args.args
        self.assertIn("Time >= %s", sql)
        self.assertIn("Time <= %s", sql)
        self.assertEqual(parameters[-3:-1], [datetime(2026, 7, 1), datetime(2026, 7, 2, 23, 59, 59)])

    def test_ea_dynamic_numeric_prefix_adaptively_splits_truncated_shard(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [[{}] * 5001, *([[]] * 11)]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        service = app.EaCommentGroupService(SimpleNamespace(mysql_trade_connect=lambda _source: connection))
        seed = app.ea_dynamic_identity(app.ea_comment_identity("@8@65123456@7", 7))

        rows, truncated = service._query_dynamic_pattern_batch(
            {"schema": "sass_crm_ac_mt5_live", "table": "mt5_deals"}, ["@8@65%"], seed,
        )

        self.assertEqual(rows, [])
        self.assertEqual(truncated, [])
        self.assertEqual(cursor.execute.call_count, 12)
        child_patterns = [call.args[1][0] for call in cursor.execute.call_args_list[1:]]
        self.assertIn("@8@650%", child_patterns)
        self.assertIn("@8@65@%", child_patterns)

    def test_ea_dynamic_targets_include_dbg_mt5_live2(self):
        sources = [
            {"kind": "mt5_deals", "schema": "sass_crm_ac_mt5_live", "host": "ac", "table": "mt5_deals"},
            {"kind": "mt5_deals", "schema": "mt5_export_new", "host": "dbg", "table": "mt5_deals"},
            {"kind": "mt5_deals", "schema": "crm_vn_mt5_live2", "host": "dbg", "table": "mt5_deals"},
        ]
        service = app.EaCommentGroupService(SimpleNamespace(MYSQL_SOURCES=sources))

        self.assertEqual(
            {source["schema"] for source in service._dynamic_target_sources([])},
            {"sass_crm_ac_mt5_live", "mt5_export_new", "crm_vn_mt5_live2"},
        )

    def test_ea_group_current_summary_uses_complete_reconstructed_member(self):
        runtime = SimpleNamespace(
            normalize_text=lambda value: str(value or "").strip(),
            numeric_value=lambda value: float(value or 0),
            rounded=lambda value, digits=2: round(float(value or 0), digits),
            mysql_datetime_text=lambda value: str(value or ""),
        )
        service = app.EaCommentGroupService(runtime)
        seed = {
            "comment": "ExpertID 7 · @8@动态备注", "currentOrders": 1, "currentVolume": 0.1,
            "currentNetProfit": 10, "firstTime": "2026-07-01", "lastTime": "2026-07-01",
        }
        records = [
            {
                "account": "2013674", "comment": "ExpertID 7 · @8@动态备注", "ticket": "1", "volume": 0.1,
                "netProfit": 10, "openTime": "2026-07-01", "closeTime": "2026-07-01",
            },
            {
                "account": "2013674", "comment": "ExpertID 7 · @8@动态备注", "ticket": "2", "volume": 0.2,
                "netProfit": 20, "openTime": "2026-07-02", "closeTime": "2026-07-02",
            },
            {
                "account": "2010861", "comment": "ExpertID 7 · @8@动态备注", "ticket": "3", "volume": 0.3,
                "netProfit": -5, "openTime": "2026-07-01", "closeTime": "2026-07-01",
            },
        ]
        source = {"kind": "mt5_deals", "platform": "MT5", "server": "DBG CN MT5"}

        with patch.object(service, "_seed_comments", return_value=[seed]), \
             patch.object(service, "_query_mt5", return_value=(records, False, [])):
            group = service.query_source(source, [], "2013674")[0]

        self.assertEqual(group["currentOrders"], 2)
        self.assertEqual(group["currentVolume"], 0.3)
        self.assertEqual(group["currentNetProfit"], 30)

    def test_ea_comment_totals_list_account_profit_and_costs_separately(self):
        totals = app.ea_comment_totals([
            {"orders": 2, "volume": 0.3, "grossProfit": 12, "commission": -1, "swap": -0.5, "taxes": 0, "netProfit": 10.5, "currency": "USD"},
            {"orders": 1, "volume": 0.2, "grossProfit": -4, "commission": -1, "swap": 0, "taxes": 0, "netProfit": -5, "currency": "USD"},
        ])
        self.assertEqual(totals["accounts"], 2)
        self.assertEqual(totals["profitableAccounts"], 1)
        self.assertEqual(totals["losingAccounts"], 1)
        self.assertEqual(totals["orders"], 3)
        self.assertEqual(totals["volume"], 0.5)
        self.assertEqual(totals["grossProfit"], 8)
        self.assertEqual(totals["commission"], -2)
        self.assertEqual(totals["netProfit"], 5.5)

    def test_ea_comment_profit_payload_uses_isolated_service(self):
        expected = {"ok": True, "account": "700002", "detected": True, "groups": [{"comment": "ChanGold V33"}]}
        with patch.object(app.EaCommentGroupService, "payload", return_value=expected) as payload_query:
            payload = app.account_ea_comment_profit_payload("700002", {"platform": "MT5", "server": "DBG MT5"})

        self.assertEqual(payload["groups"][0]["comment"], "ChanGold V33")
        payload_query.assert_called_once_with("700002", {"platform": "MT5", "server": "DBG MT5"})

    def test_account_detail_ui_exposes_ea_query_next_to_copy_query(self):
        copy_index = app.ACCOUNT_DETAIL_HTML.index('id="copyOriginBtn"')
        ea_index = app.ACCOUNT_DETAIL_HTML.index('id="eaCommentBtn"')
        relationship_index = app.ACCOUNT_DETAIL_HTML.index('id="relationshipNetworkBtn"')
        toxic_index = app.ACCOUNT_DETAIL_HTML.index('id="toxicBtn"')
        self.assertLess(copy_index, ea_index)
        self.assertLess(ea_index, relationship_index)
        self.assertLess(relationship_index, toxic_index)
        self.assertIn('$("relationshipNetworkBtn").addEventListener(\'click\',openRelationshipNetwork)', app.ACCOUNT_DETAIL_HTML)
        self.assertIn('$("resetRelationshipNetworkBtn").addEventListener(\'click\',resetRelationshipNetwork)', app.ACCOUNT_DETAIL_HTML)
        self.assertIn("点击切换成员", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("network.expanded.has(entity.id)?network.expanded.delete(entity.id):network.expanded.add(entity.id)", app.ACCOUNT_DETAIL_HTML)
        self.assertIn('<canvas id="relationshipNetworkGraph"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationCanvasEdgeLabel", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("edge.typeLabel||edge.label||'关系证据'", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationCanvasContextFor(viewport)", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationshipGraph.getContext('2d',{alpha:false,desynchronized:true})", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationWorldViewport", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationEdgeIntersectsViewport", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationEdgeLabelMetric", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("RELATIONSHIP_GRAPH_CACHE_SCALE=3", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationSceneContext(network)", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationBuildSceneCache(network)", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("context.drawImage(scene", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationDrawDragOverlay", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("network.dragNodeId=hit.entity.id", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationshipGraph.dataset.frameMs", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationshipGraph.dataset.cacheBuildMs", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("window.__kdeskRelationshipPerf=stats", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationScheduleCanvas(network)", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("relationHitTest(network,point)", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("pending.delta+=event.deltaY", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("Math.exp(-Math.max(-360,Math.min(360,wheel.delta))*0.00075)", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("drag.moved&&Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>=4", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("requestAnimationFrame", app.ACCOUNT_DETAIL_HTML)
        self.assertNotIn("relationshipNetworkStage", app.ACCOUNT_DETAIL_HTML)
        self.assertNotIn("relationScheduleComposite", app.ACCOUNT_DETAIL_HTML)
        self.assertNotIn("relationApplyStageTransform", app.ACCOUNT_DETAIL_HTML)
        self.assertNotIn("relationDrawBaseGraph", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("/ea-comment-profit", app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="eaCommentStart"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="eaCommentEnd"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="applyEaCommentRange"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn("function eaCommentDialogQuery()", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("EA 开始时间不能晚于结束时间", app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="copyOriginStart"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="copyOriginEnd"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="applyCopyOriginRange"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn("function copyOriginDialogQuery()", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("跟单开始时间不能晚于结束时间", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("let q;try{q=copyOriginDialogQuery();}", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("const cacheKey=q.toString()", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("kind==='ea'?eaCommentDialogQuery():copyOriginDialogQuery()", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("相同 Comment 的 EA 账户收益", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("匹配线索", app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="exportCopyReportBtn"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn('id="exportEaReportBtn"', app.ACCOUNT_DETAIL_HTML)
        self.assertIn("copy-report.xlsx", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("ea-report.xlsx", app.ACCOUNT_DETAIL_HTML)
        self.assertIn('class="copy-group-block ea-group-block" open', app.ACCOUNT_DETAIL_HTML)
        self.assertIn('<summary class="copy-group-head">', app.ACCOUNT_DETAIL_HTML)
        self.assertIn(".ea-group-block[open] > summary::before", app.ACCOUNT_DETAIL_HTML)

    def test_account_detail_keeps_all_analysis_actions_visible_for_zero_order_accounts(self):
        html = app.ACCOUNT_DETAIL_HTML

        self.assertNotIn('id="copyOriginBtn" type="button" hidden', html)
        self.assertNotIn('id="eaCommentBtn" class="ea-query-entry" type="button" hidden', html)
        self.assertNotIn('id="relationshipNetworkBtn" class="relationship-entry" type="button" hidden', html)
        self.assertNotIn('$("copyOriginBtn").hidden=!db.exists', html)
        self.assertNotIn('$("eaCommentBtn").hidden=!db.exists', html)
        self.assertNotIn('$("relationshipNetworkBtn").hidden=!db.exists', html)
        self.assertNotIn('$("generateBtn").disabled=!db.exists', html)
        self.assertNotIn('$("toxicBtn").disabled=!db.exists', html)
        self.assertNotIn('$("historicalFundsBtn").disabled=!db.exists', html)

    def test_account_detail_ui_exposes_header_account_search(self):
        html = app.ACCOUNT_DETAIL_HTML
        self.assertIn('id="detailAccountSearchForm"', html)
        self.assertIn('id="detailAccountSearch"', html)
        self.assertIn('id="detailAccountSearchStatus"', html)
        self.assertIn("async function openAccountFromDetailSearch", html)
        self.assertIn("/api/account-lookup?account=", html)
        self.assertIn("matches.find(item=>item.latestSource?.platform===current.platform&&item.latestSource?.server===current.server)", html)
        self.assertIn('id="accountSourceDialog"', html)
        self.assertIn("matches.length>1", html)

    def test_account_detail_embeds_a_full_page_direct_kline_without_a_job_submission(self):
        html = app.ACCOUNT_DETAIL_HTML
        self.assertIn('id="inlineKlineFrame"', html)
        self.assertIn('scrolling="no"', html)
        self.assertIn('window.addEventListener(\'message\'', html)
        self.assertIn("event.source!==frame.contentWindow", html)
        self.assertIn("kdesk-inline-kline-height", html)
        self.assertNotIn('height:680px', html)
        self.assertNotIn('id="orderDetails"', html)
        self.assertNotIn('<span>所有订单</span>', html)
        self.assertIn("async function loadInlineKline()", html)
        self.assertIn("recentOrders:'300'", html)
        self.assertIn("/inline-kline?${query}", html)
        self.assertIn("cache:'no-store'", html)
        self.assertIn("query.set('inlineVersion',Date.now().toString())", html)
        self.assertNotIn("headers:{'Cache-Control':'no-cache'}", html)
        self.assertIn("function inlineKlineDocument(html)", html)
        self.assertIn("frame.srcdoc=inlineKlineDocument(await response.text())", html)
        self.assertIn("loadInlineKline();", html)
        self.assertNotIn("async function autoLoadKline()", html)

    def test_recent_chartable_kline_trades_use_latest_completed_orders(self):
        rows = [
            {"ticket": "old", "type": "buy", "open_time": "2026-08-01 10:00:00", "close_time": "2026-08-01 10:01:00"},
            {"ticket": "open", "type": "buy", "open_time": "2026-08-04 10:00:00", "close_time": ""},
            {"ticket": "new", "type": "sell", "open_time": "2026-08-03 10:00:00", "close_time": "2026-08-03 10:01:00"},
        ]
        selected = app.recent_chartable_kline_trades(rows, 1)
        self.assertEqual([row["ticket"] for row in selected], ["new"])

    def test_inline_kline_keeps_current_positions_beside_the_bounded_closed_window(self):
        closed = [
            {"ticket": "old", "type": "buy", "open_time": "2026-08-01 10:00:00", "close_time": "2026-08-01 10:01:00"},
            {"ticket": "new", "type": "sell", "open_time": "2026-08-03 10:00:00", "close_time": "2026-08-03 10:01:00"},
        ]
        current = [{"ticket": "open", "type": "buy", "open_time": "2026-08-04 10:00:00", "is_open_position": True}]

        selected = app.inline_kline_trade_rows(closed, current, 1)

        self.assertEqual([row["ticket"] for row in selected], ["new", "open"])
        self.assertTrue(selected[-1]["is_open_position"])

    def test_account_detail_embedded_script_has_valid_javascript(self):
        script = re.search(r"<script>(.*?)</script>", app.ACCOUNT_DETAIL_HTML, re.DOTALL)
        self.assertIsNotNone(script)
        node = Path(r"C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
        self.assertTrue(node.exists(), "Bundled Node.js runtime is required for detail-page syntax validation")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script.group(1))
            script_path = Path(handle.name)
        try:
            result = subprocess.run(
                [str(node), "--check", str(script_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            script_path.unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_account_detail_does_not_embed_copy_experiment(self):
        html = app.ACCOUNT_DETAIL_HTML
        self.assertNotIn('id="copyExperimentSection"', html)
        self.assertNotIn("/api/copy-pool/dashboard?timeline_limit=30", html)
        self.assertNotIn("copyExperimentStatusLabel", html)
        self.assertNotIn("loadCopyExperiment", html)

    def test_account_detail_caches_automation_and_navigates_relationship_investigation(self):
        html = app.ACCOUNT_DETAIL_HTML
        self.assertIn("dialogCache:{copy:new Map(),ea:new Map(),relationship:new Map()}", html)
        self.assertIn("state.dialogCache.copy.get(cacheKey)", html)
        self.assertIn("state.dialogCache.copy.set(cacheKey,request)", html)
        self.assertIn("state.dialogCache.ea.get(cacheKey)", html)
        self.assertIn("state.dialogCache.ea.set(cacheKey,request)", html)
        self.assertIn("query.set('account',LOGIN)", html)
        self.assertIn("location.assign(`/kuzu-risk?${query.toString()}`)", html)
        self.assertIn("function clearAutomationDialogCache(){state.dialogCache.copy.clear();state.dialogCache.ea.clear();state.dialogCache.relationship.clear();state.relationshipNetwork=null;}", html)
        self.assertIn("clearAutomationDialogCache();load(true)", html)

    def test_signal_group_totals_separates_trade_profit_and_rebate(self):
        rows = [
            {"status": "L", "closedOrders": 10, "openOrders": 1, "closedLots": 2, "closedNetProfit": -100, "floatingNetProfit": 10, "combinedNetProfit": -90, "rebate": 50},
            {"status": "", "closedOrders": 5, "openOrders": 0, "closedLots": 1, "closedNetProfit": 20, "floatingNetProfit": 0, "combinedNetProfit": 20, "rebate": 25},
        ]
        totals = app.signal_group_totals(rows)
        self.assertEqual(totals["accounts"], 2)
        self.assertEqual(totals["profitableAccounts"], 1)
        self.assertEqual(totals["losingAccounts"], 1)
        self.assertEqual(totals["combinedNetProfit"], -70)
        self.assertEqual(totals["rebate"], 75)
        self.assertEqual(totals["rebatePerLot"], 25)
        self.assertEqual(totals["estimatedPlatformAfterRebate"], -5)
        self.assertEqual(totals["statusCounts"], {"L": 1, "未填": 1})

    def test_signal_group_rebates_sum_all_configured_crm_routes(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{"Login": 2012060, "Rebate": "100.25"}],
            [{"Login": 2012060, "Rebate": "20.50"}],
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        runtime = SimpleNamespace(
            normalize_text=app.normalize_text,
            numeric_value=app.numeric_value,
            source_crm_routes=app.source_crm_routes,
            mysql_trade_connect=MagicMock(return_value=connection),
        )
        service = app.SignalCopyGroupService(runtime)
        rebates, error = service.query_rebates({
            "crm_routes": [
                {"schema": "crm_cn", "mt_server_code": "4"},
                {"schema": "crm_vn", "mt_server_code": "2"},
            ],
        }, [2012060])

        self.assertEqual(error, "")
        self.assertEqual(rebates, {"2012060": 120.75})
        self.assertEqual(cursor.execute.call_count, 2)

    def test_copy_group_profit_payload_returns_signal_groups_without_raw_comments(self):
        group = {
            "account": "5012810", "signalId": "5009780", "signalTag": "Signal #5009780 IN",
            "platform": "MT4", "server": "AC MT4", "status": "L", "members": [],
            "totals": app.signal_group_totals([]), "truncated": False, "limitations": [],
        }
        expected = {"ok": True, "account": "5012810", "detected": True, "groups": [group]}
        with patch.object(app.SignalCopyGroupService, "payload", return_value=expected) as payload_query:
            payload = app.account_copy_group_profit_payload("5012810", {"platform": "MT4", "server": "AC MT4"})

        self.assertTrue(payload["detected"])
        self.assertEqual(payload["groups"][0]["signalTag"], "Signal #5009780 IN")
        self.assertNotIn("UserComment", json.dumps(payload))
        payload_query.assert_called_once_with("5012810", {"platform": "MT4", "server": "AC MT4"})

    def test_order_payload_is_newest_first_and_uses_public_whitelist(self):
        rows = [
            {
                "ticket": "1", "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "buy",
                "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00",
                "holding_seconds": 60, "volume": 0.1, "profit": 10, "commission": -1,
                "swap": -0.5, "taxes": 0, "account_currency": "USD", "display_currency": "USD",
                "raw_json": '{"email":"hidden@example.com"}',
            },
            {
                "ticket": "2", "platform": "MT5", "server": "Live", "symbol": "EURUSD", "type": "sell",
                "open_time": "2026-07-02 10:00:00", "close_time": "2026-07-02 10:02:00",
                "holding_seconds": 120, "volume": 0.2, "profit": -3, "commission": -2,
                "swap": 0, "taxes": -0.1, "account_currency": "USD", "display_currency": "USD",
                "reason": "Expert", "comment": "auto trade by sc", "expert_id": "234000",
            },
        ]

        with patch.object(app, "query_db_trades", return_value=rows):
            payload = app.account_orders_payload("900001", page=1, page_size=20)

        self.assertEqual(payload["total"], 2)
        self.assertEqual([row["ticket"] for row in payload["orders"]], ["2", "1"])
        self.assertEqual(payload["orders"][0]["netProfit"], -5.1)
        self.assertEqual(payload["orders"][0]["reason"], "Expert")
        self.assertEqual(payload["orders"][0]["comment"], "auto trade by sc")
        self.assertEqual(payload["orders"][0]["expertId"], "234000")
        encoded = json.dumps(payload, ensure_ascii=False).lower()
        self.assertNotIn("email", encoded)
        self.assertNotIn("raw_json", encoded)


class LoginIpTests(unittest.TestCase):
    class FakeCursor:
        def __init__(self, row):
            self.row = row

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, args):
            self.sql = sql
            self.args = args

        def fetchone(self):
            return self.row

    class FakeConnection:
        def __init__(self, row):
            self.row = row

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return LoginIpTests.FakeCursor(self.row)

    def test_login_ip_payload_records_mt5_ip_and_marks_mt4_not_exported(self):
        sources = [
            {"name": "Live MT5", "platform": "MT5", "server": "Live MT5", "kind": "mt5_deals", "schema": "live"},
            {"name": "Live MT4", "platform": "MT4", "server": "Live MT4", "kind": "mt4_trades", "schema": "mt4"},
        ]
        geo = {"country": "China", "region": "Anhui", "city": "Hefei", "isp": "Test ISP", "asn": "123", "latitude": 1, "longitude": 2, "status": "ok"}
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(app, "IP_HISTORY_DB_PATH", Path(temp_dir) / "ips.sqlite"), \
             patch.object(app, "MYSQL_SOURCES", sources), \
             patch.object(app, "mysql_trade_connect", return_value=self.FakeConnection({"Login": 900001, "LastIP": "8.8.8.8", "LastAccess": "2026-07-10 10:00:00"})), \
             patch.object(app, "query_public_ip_geo", return_value=geo):
            payload = app.account_login_ips_payload("900001")
            payload_again = app.account_login_ips_payload("900001")

        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["ip"], "8.8.8.8")
        self.assertEqual(payload["records"][0]["geo"]["city"], "Hefei")
        self.assertEqual(len(payload_again["records"]), 1)
        self.assertFalse(payload["sources"][1]["available"])
        self.assertTrue(payload["sources"][1]["accountExists"])
        self.assertIn("未包含登录 IP 字段", payload["sources"][1]["reason"])
        encoded = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in ("phone", "email", "idcard", "firstname", "lastname", "address"):
            self.assertNotIn(forbidden, encoded)

    def test_private_ip_does_not_call_public_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(app, "IP_HISTORY_DB_PATH", Path(temp_dir) / "ips.sqlite"), \
             patch.object(app, "query_public_ip_geo", side_effect=AssertionError("public lookup must not run")):
            geo = app.cached_ip_geo("127.0.0.1", "private")
        self.assertEqual(geo["status"], "private")
        self.assertEqual(geo["isp"], "内网或保留地址")

    def test_shared_cid_payload_returns_same_server_mt5_peers_and_ignores_zero(self):
        class Cursor:
            def __init__(self, cid):
                self.cid = cid
                self.executed = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, args):
                self.executed.append((sql, args))

            def fetchone(self):
                return {"ClientID": self.cid}

            def fetchall(self):
                return [{"Login": 900002, "ClientID": self.cid, "LastAccess": "2026-08-24 10:00:00"}]

        class Connection:
            def __init__(self, cursor):
                self.value = cursor

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return self.value

        source = {"name": "Live MT5", "platform": "MT5", "server": "Live MT5", "kind": "mt5_deals", "schema": "live"}
        cursor = Cursor(987654)
        with patch.object(app, "MYSQL_SOURCES", [source]), patch.object(
            app, "mysql_trade_connect", return_value=Connection(cursor)
        ):
            payload = app.account_shared_cid_payload("900001", {"platform": "MT5", "server": "Live MT5"})

        self.assertEqual(payload["peers"][0]["account"], "900002")
        self.assertEqual(payload["peers"][0]["cid"], "987654")
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("ClientID", cursor.executed[0][0])
        self.assertIn("ClientID = %s", cursor.executed[1][0])

        zero_cursor = Cursor(0)
        with patch.object(app, "MYSQL_SOURCES", [source]), patch.object(
            app, "mysql_trade_connect", return_value=Connection(zero_cursor)
        ):
            zero_payload = app.account_shared_cid_payload("900001", {"platform": "MT5", "server": "Live MT5"})
        self.assertEqual(zero_payload["peers"], [])
        self.assertEqual(len(zero_cursor.executed), 1)


class MarkAccountTests(unittest.TestCase):
    def test_batch_mark_creates_and_updates_each_local_ledger_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            workbook = out_dir / "ledger.xlsx"
            with patch.object(app, "OUT_DIR", out_dir), patch.object(app, "WORKBOOK_PATH", workbook):
                app.write_workbook([], [])

                saved, records = app.mark_account_records(
                    {"action": "M", "status": "观察中", "note": "同名账户批量记录"},
                    ["900011", "900012"],
                )
                self.assertEqual([row["账号"] for row in saved], ["900011", "900012"])
                self.assertEqual(len(records), 2)
                self.assertEqual([row["操作"] for row in app.read_history_rows()], ["加入", "加入"])

                saved, records = app.mark_account_records({"status": "已确认"}, ["900011", "900012"])
                self.assertEqual({row["状态"] for row in saved}, {"已确认"})
                self.assertEqual(len(records), 2)
                self.assertEqual([row["操作"] for row in app.read_history_rows()], ["加入", "加入", "修改", "修改"])

    def test_fast_ledger_payload_does_not_query_trade_database(self):
        record = {field: "" for field in app.HEADERS}
        record.update({"记录ID": "ACC-900020", "账号": "900020", "状态": "待复核"})
        with patch.object(app, "load_records", return_value=[record]), \
             patch.object(app, "query_db_trades", side_effect=AssertionError("trade database should not be queried")):
            payload = app.account_ledger_payload("900020")
        self.assertTrue(payload["marked"])
        self.assertEqual(payload["record"]["状态"], "待复核")

    def test_create_and_update_keep_excel_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            workbook = out_dir / "ledger.xlsx"
            with patch.object(app, "OUT_DIR", out_dir), patch.object(app, "WORKBOOK_PATH", workbook):
                app.write_workbook([], [])

                created, records = app.mark_account_record({
                    "account": "900001",
                    "action": "M观察",
                    "tags": "短线",
                    "note": "首条备注",
                    "status": "观察中",
                    "owner": "test",
                })
                self.assertEqual(len(records), 1)
                self.assertEqual(created["账号"], "900001")
                self.assertEqual(created["建议动作"], "M观察")
                first_joined_at = created["加入时间"]

                updated, records = app.mark_account_record({
                    "account": "900001",
                    "action": "P",
                    "note": "复核后更新",
                    "status": "已确认",
                })
                self.assertEqual(len(records), 1)
                self.assertEqual(updated["建议动作"], "P")
                self.assertEqual(updated["加入时间"], first_joined_at)
                history = app.read_history_rows()
                self.assertEqual([row["操作"] for row in history], ["加入", "修改"])
                self.assertIn("建议动作", history[-1]["修改字段"])

    def test_detail_payload_has_no_personal_profile_fields(self):
        trade = {
            "platform": "MT5", "server": "Live", "symbol": "XAUUSD", "type": "buy",
            "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:01:00",
            "volume": 0.1, "profit": 1, "commission": 0, "swap": 0, "taxes": 0,
            "holding_seconds": 60,
        }
        record = {field: "" for field in app.HEADERS}
        record.update({"记录ID": "ACC-900002", "账号": "900002", "建议动作": "M", "原始记录": "手机号 13800000000"})
        history = [{field: "" for field in app.HISTORY_HEADERS}]
        history[0].update({"记录ID": "ACC-900002", "账号": "900002", "修改前JSON": '{"email":"hidden@example.com"}'})
        with patch.object(app, "load_records", return_value=[record]), \
             patch.object(app, "query_db_trades", return_value=[trade]), \
             patch.object(app, "scan_chart_files", return_value=[]), \
             patch.object(app, "read_history_rows", return_value=history):
            payload = app.account_detail_payload("900002")
        encoded = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in ("phone", "mobile", "email", "idcard", "address", "姓名", "手机号", "证件号"):
            self.assertNotIn(forbidden, encoded)


class ToxicDetectionTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "ticket": "B1", "platform": "MT5", "server": "Live", "symbol": "NZDCHF", "type": "buy",
                "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:00:01",
                "open_time_msc": "2026-07-01 10:00:00.100", "close_time_msc": "2026-07-01 10:00:01.100",
                "volume": 10, "profit": -500, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
            },
            {
                "ticket": "S1", "platform": "MT5", "server": "Live", "symbol": "NZDCHF", "type": "sell",
                "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:00:01",
                "open_time_msc": "2026-07-01 10:00:00.200", "close_time_msc": "2026-07-01 10:00:01.200",
                "volume": 10, "profit": -500, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
            },
        ]
        self.finance = {
            "available": True, "equity": 100, "credit": 0, "margin": 80, "marginLevel": 125,
            "rebate": 100, "netDeposit": 50,
        }

    def test_market_pushing_consistency_bonus_requires_two_clean_core_groups(self):
        self.assertAlmostEqual(app.market_pushing_consistency_bonus(36.4, 21.5, 0), 10.35)
        self.assertEqual(app.market_pushing_consistency_bonus(32.1, 17.5, 0), 0)
        self.assertEqual(app.market_pushing_consistency_bonus(35.4, 24, 11.1), 0)
        self.assertEqual(app.market_pushing_consistency_bonus(40, 35, 0), 12)

    def test_initial_screen_returns_every_supported_type(self):
        results = app.calculate_toxic_results(
            "900100", self.rows, list(app.TOXIC_CHECK_TYPE_MAP), "initial", self.finance,
        )
        self.assertEqual(len(results), len(app.TOXIC_CHECK_TYPES))
        self.assertEqual({row["type"] for row in results}, set(app.TOXIC_CHECK_TYPE_MAP))
        self.assertTrue(all(row["stage"] == "initial" for row in results))

    def test_manual_detection_only_returns_selected_type(self):
        results = app.calculate_toxic_results(
            "900100", self.rows, ["short_close_trading"], "deep", self.finance,
        )
        self.assertEqual([row["type"] for row in results], ["short_close_trading"])
        self.assertEqual(results[0]["stage"], "deep")

    def test_large_instant_opposite_pair_flags_rebate_churning(self):
        result = app.calculate_toxic_results(
            "900100", self.rows, ["rebate_churning"], "deep", self.finance,
        )[0]
        self.assertGreaterEqual(result["score"], 90)
        self.assertEqual(result["level"], "严重形态")
        self.assertEqual(set(result["evidenceOrders"]), {"B1", "S1"})

    def test_tick_deep_result_exposes_coverage_terminal_and_time_alignment(self):
        tick = {
            "available": True, "candidateOrders": 2, "analyzedOrders": 1, "coverageRatio": 50,
            "priceWinTickMedian": 1, "netWinTickMedian": 2,
            "win1VolumeRatio": 50, "win3VolumeRatio": 100,
            "netWin1VolumeRatio": 0, "netWin3VolumeRatio": 100,
            "sources": [{"terminalServer": "AC-Live"}],
            "mappings": [{"timeMode": "report_is_GMT+3"}],
            "errors": ["一笔订单未取到Tick"],
        }
        result = app.calculate_toxic_results(
            "900100", self.rows, ["quote_latency_arbitrage"], "deep", self.finance, tick,
        )[0]
        metrics = {item["label"]: item["value"] for item in result["metrics"]}
        self.assertEqual(metrics["盈利单Tick有效样本"], "1/2 单 (50%)")
        self.assertEqual(metrics["盈利单Tick抽样覆盖"], "1/2 单 (50%)")
        self.assertEqual(metrics["Terminal行情源"], "AC-Live")
        self.assertEqual(metrics["时间校准"], "report_is_GMT+3")
        self.assertIn("部分候选未取到Tick", result["limitations"][0])

    def test_cached_tick_mapping_reuses_chart_alignment(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(app, "KLINE_OUT_DIR", Path(temp_dir)):
            mapping_path = Path(temp_dir) / "900100_20260701_100000_20260701_101000_mapping.json"
            mapping_path.write_text(json.dumps({
                "XAUUSD": {"mt5_symbol": "XAUUSD", "time_mode": "report_is_GMT+3", "hour_delta": -3},
            }), encoding="utf-8")
            mapping = app.toxic_cached_tick_mapping("900100", "XAUUSD")
        self.assertEqual(mapping["mt5Symbol"], "XAUUSD")
        self.assertEqual(mapping["hourDelta"], -3)
        self.assertEqual(mapping["source"], "图表校准缓存")

    def test_winning_tick_uses_closeable_bid_ask_prices(self):
        self.assertLess(app.toxic_closeable_move("buy", 100.0, 100.2, 100.19, 100.21), 0)
        self.assertGreater(app.toxic_closeable_move("buy", 100.0, 100.2, 100.21, 100.23), 0)
        self.assertLess(app.toxic_closeable_move("sell", 100.0, 100.2, 99.99, 100.01), 0)
        self.assertGreater(app.toxic_closeable_move("sell", 100.0, 100.2, 99.97, 99.99), 0)

    def test_tick_candidate_identity_keeps_same_ticket_from_different_sources(self):
        mt4 = {"platform": "MT4", "server": "AC MT4", "ticket": "123"}
        mt5 = {"platform": "MT5", "server": "AC GB MT5", "ticket": "123"}
        self.assertNotEqual(app.toxic_tick_candidate_key(mt4), app.toxic_tick_candidate_key(mt5))

    def test_winning_tick_coverage_excludes_extra_winners_from_all_order_sample(self):
        results = [
            {"_candidateKey": "winning-sample", "realizedNet": 10},
            {"_candidateKey": "all-order-extra", "realizedNet": 20},
            {"_candidateKey": "loser", "realizedNet": -5},
        ]
        selected = app.toxic_tick_winning_sample_results(results, {"winning-sample"})
        self.assertEqual([item["_candidateKey"] for item in selected], ["winning-sample"])

    def test_overlapping_tick_windows_are_fetched_once_and_sliced_exactly(self):
        first = {
            "ticket": "1", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
            "open_time": "2026-07-01 10:00:00",
        }
        second = {
            "ticket": "2", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
            "open_time": "2026-07-01 10:01:00",
        }
        first_ms = int(app.datetime(2026, 7, 1, 10, 0, tzinfo=app.timezone.utc).timestamp() * 1000)
        second_ms = int(app.datetime(2026, 7, 1, 10, 1, tzinfo=app.timezone.utc).timestamp() * 1000)
        ticks = [
            {"time_msc": first_ms, "bid": 1.0, "ask": 1.1},
            {"time_msc": second_ms, "bid": 1.2, "ask": 1.3},
        ]
        fake_mt5 = SimpleNamespace(COPY_TICKS_ALL=0, copy_ticks_range=MagicMock(return_value=ticks))
        result = app.toxic_prefetch_tick_windows(fake_mt5, "XAUUSD", [first, second], 0)
        self.assertEqual(fake_mt5.copy_ticks_range.call_count, 1)
        self.assertEqual(
            [item["time_msc"] for item in result[app.toxic_tick_candidate_key(first)]],
            [first_ms, second_ms],
        )
        self.assertEqual(
            [item["time_msc"] for item in result[app.toxic_tick_candidate_key(second)]],
            [second_ms],
        )

    def test_mt4_orders_use_explicitly_configured_mt5_terminal_ticks(self):
        opened = "2026-07-01 10:00:00"
        open_ms = int(app.datetime(2026, 7, 1, 10, 0, tzinfo=app.timezone.utc).timestamp() * 1000)
        row = {
            "ticket": "M4-1", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD", "type": "buy",
            "open_time": opened, "close_time": "2026-07-01 10:00:01", "open_price": 3300.2,
            "close_price": 3300.5, "volume": 1, "profit": 10, "commission": 0, "fee": 0,
            "swap": 0, "taxes": 0, "tick_value": 1, "tick_size": 0.1,
        }
        fake_mt5 = SimpleNamespace(
            COPY_TICKS_ALL=0,
            initialize=MagicMock(return_value=True),
            account_info=MagicMock(return_value=SimpleNamespace(login=11007, server="ACCMGlobal-Live")),
            terminal_info=MagicMock(return_value=SimpleNamespace(connected=True)),
            copy_ticks_range=MagicMock(return_value=[
                {"time_msc": open_ms - 100, "bid": 3300.0, "ask": 3300.2},
                {"time_msc": open_ms + 100, "bid": 3300.3, "ask": 3300.5},
            ]),
            login=MagicMock(return_value=True),
            shutdown=MagicMock(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            terminal = Path(temp_dir) / "terminal64.exe"
            terminal.touch()
            with patch.dict("sys.modules", {"MetaTrader5": fake_mt5}), \
                 patch.object(app, "TOXIC_MT5_TERMINALS", {"AC MT4": str(terminal)}), \
                 patch.object(app, "TOXIC_MT5_QUOTE_ACCOUNTS", {"AC MT4": {"login": 11007, "server": "ACCMGlobal-Live"}}), \
                 patch.object(app, "toxic_mt5_symbol_for", return_value="XAUUSD"), \
                 patch.object(app, "toxic_cached_tick_mapping") as cached_mapping, \
                 patch.object(app, "toxic_live_tick_mapping", return_value={
                     "reportSymbol": "XAUUSD", "mt5Symbol": "XAUUSD", "timeMode": "report_is_GMT",
                     "hourDelta": 0, "source": "test",
                 }):
                result = app.toxic_winning_ticks("5013128", [row])

        self.assertTrue(result["available"])
        self.assertEqual(result["analyzedOrders"], 1)
        self.assertEqual(result["priceWinTickMedian"], 1)
        self.assertIn("preTickRatePerMinuteMedian", result)
        self.assertIn("eventAcceleration10VolumeRatio", result)
        self.assertIn("spreadExpansionRatioMedian", result)
        self.assertEqual(result["sources"][0]["databasePlatform"], "MT4")
        self.assertTrue(result["sources"][0]["configuredForServer"])
        cached_mapping.assert_not_called()
        fake_mt5.initialize.assert_called_once_with(path=str(terminal), timeout=10000)

    def test_unconfigured_mt4_server_does_not_fall_back_to_unrelated_mt5_terminal(self):
        row = {
            "ticket": "M4-2", "platform": "MT4", "server": "Unknown MT4", "symbol": "XAUUSD", "type": "buy",
            "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:00:01",
            "open_price": 3300.2, "close_price": 3300.5, "volume": 1, "profit": 10,
        }
        fake_mt5 = SimpleNamespace(initialize=MagicMock())
        with patch.dict("sys.modules", {"MetaTrader5": fake_mt5}), \
             patch.object(app, "TOXIC_MT5_TERMINALS", {}):
            result = app.toxic_winning_ticks("900001", [row])

        self.assertFalse(result["available"])
        self.assertIn("未配置供 MT4 订单使用的 MT5 Terminal 行情源", result["reason"])
        fake_mt5.initialize.assert_not_called()

    def test_mt4_server_requires_explicit_mt5_quote_account(self):
        row = {
            "ticket": "M4-3", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD", "type": "buy",
            "open_time": "2026-07-01 10:00:00", "close_time": "2026-07-01 10:00:01",
            "open_price": 3300.2, "close_price": 3300.5, "volume": 1, "profit": 10,
        }
        fake_mt5 = SimpleNamespace(initialize=MagicMock())
        with tempfile.TemporaryDirectory() as temp_dir:
            terminal = Path(temp_dir) / "terminal64.exe"
            terminal.touch()
            with patch.dict("sys.modules", {"MetaTrader5": fake_mt5}), \
                 patch.object(app, "TOXIC_MT5_TERMINALS", {"AC MT4": str(terminal)}), \
                 patch.object(app, "TOXIC_MT5_QUOTE_ACCOUNTS", {}):
                result = app.toxic_winning_ticks("900001", [row])

        self.assertFalse(result["available"])
        self.assertIn("未配置供 MT4 订单使用的 MT5 行情账号", result["reason"])
        fake_mt5.initialize.assert_not_called()

    def test_market_pushing_sync_remains_high_risk_with_losing_orders(self):
        rows = []
        for index in range(8):
            day = index // 4 + 1
            minute = index % 4 * 10
            rows.append({
                "ticket": f"S{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                "type": "buy" if index % 3 else "sell",
                "open_time": f"2026-07-{day:02d} 10:{minute:02d}:00",
                "close_time": f"2026-07-{day:02d} 10:{minute + 1:02d}:00",
                "volume": 0.5, "profit": -50, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
            })
        sync = {
            "available": True, "sampledOrders": 8, "matchedOrders": 8,
            "matchedRatio": 100, "matchedVolumeRatio": 100, "closeMatchedRatio": 100,
            "peerAccounts": 6, "maxPeerRatio": 100, "evidenceOrders": ["S0", "S1"], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900100", rows, ["market_pushing"], "deep", self.finance,
            {"available": False, "reason": "test without ticks"}, sync,
        )[0]
        self.assertGreaterEqual(result["score"], 90)
        self.assertIn("高比例多账户协调开平仓", result["triggeredRules"])
        metric_labels = {item["label"] for item in result["metrics"]}
        self.assertIn("亏损单 / 亏损手数", metric_labels)
        analysis = {item["title"]: item["text"] for item in result["analysis"]}
        self.assertIn("高度疑似", analysis["结论"])
        self.assertIn("同一批账户", analysis["主要依据"])
        self.assertIn("亏损并没有抹掉", analysis["亏损怎么理解"])
        self.assertIn("外部基准报价", analysis["还不能确定什么"])

    def test_push_behavior_treats_losses_as_pattern_context(self):
        behavior = app.toxic_push_behavior(self.rows)
        self.assertEqual(behavior["lossRate"], 100)
        self.assertEqual(behavior["lossVolumeRatio"], 100)
        self.assertEqual(behavior["symbolConcentration"], 100)
        self.assertEqual(behavior["dailyLotConsistency"], 100)

    def test_push_filter_keeps_economic_core_covering_95_percent_volume(self):
        rows = [
            {
                "ticket": f"C{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 10:{index:02d}:00", "volume": 1.0,
            }
            for index in range(12)
        ] + [
            {
                "ticket": f"N{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 11:{index:02d}:00", "volume": 0.02,
            }
            for index in range(16)
        ]
        filtered = app.toxic_filter_push_orders(rows)
        self.assertEqual(filtered["filteredOrderCount"], 12)
        self.assertEqual(filtered["excludedOrderCount"], 16)
        self.assertLess(filtered["excludedVolumeRatio"], 5)
        self.assertEqual({row["ticket"] for row in filtered["rows"]}, {f"C{index}" for index in range(12)})

    def test_push_filter_keeps_all_orders_in_same_volume_tier(self):
        rows = [
            {
                "ticket": str(index), "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 10:{index:02d}:00", "volume": 0.1,
            }
            for index in range(10)
        ]
        filtered = app.toxic_filter_push_orders(rows)
        self.assertEqual(filtered["filteredOrderCount"], 10)
        self.assertEqual(filtered["excludedOrderCount"], 0)

    def test_dynamic_quiet_detects_relative_gap_below_four_hours(self):
        rows = []
        for prefix, opened, closed in (("A", "10:00:00", "10:05:00"), ("B", "13:54:00", "13:59:00")):
            for index in range(4):
                rows.append({
                    "ticket": f"{prefix}{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                    "type": "buy", "open_time": f"2026-07-01 {opened}", "close_time": f"2026-07-01 {closed}",
                    "volume": 1.0,
                })
        profile = app.toxic_dynamic_push_sessions(rows)
        self.assertEqual(len(profile["sessions"]), 2)
        self.assertGreaterEqual(profile["quietGapScore"], 60)
        self.assertLess(profile["sessionBreakMinutes"], 234)

    def test_dynamic_quiet_does_not_split_regular_ten_minute_trading(self):
        rows = [
            {
                "ticket": str(index), "platform": "MT4", "server": "Live", "symbol": "XAUUSD", "type": "buy",
                "open_time": f"2026-07-01 {10 + index // 6:02d}:{index % 6 * 10:02d}:00",
                "close_time": f"2026-07-01 {10 + index // 6:02d}:{index % 6 * 10 + 5:02d}:00",
                "volume": 1.0,
            }
            for index in range(12)
        ]
        profile = app.toxic_dynamic_push_sessions(rows)
        self.assertEqual(len(profile["sessions"]), 1)
        self.assertEqual(profile["quietGapScore"], 0)
        self.assertFalse(profile["quietEvidenceAvailable"])

    def test_dynamic_quiet_uses_previous_session_close_not_last_open(self):
        rows = []
        for prefix, opened, closed in (
            ("A", "10:00:00", "14:00:00"),
            ("B", "10:10:00", "10:15:00"),
            ("C", "13:54:00", "14:00:00"),
        ):
            for index in range(4):
                rows.append({
                    "ticket": f"{prefix}{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                    "type": "buy", "open_time": f"2026-07-01 {opened}", "close_time": f"2026-07-01 {closed}",
                    "volume": 1.0,
                })
        profile = app.toxic_dynamic_push_sessions(rows)
        self.assertEqual(len(profile["sessions"]), 2)
        self.assertEqual(profile["quietGapScore"], 0)

    def test_market_push_job_uses_same_filtered_orders_for_sync_tick_and_score(self):
        rows = [
            {
                "ticket": f"C{index}", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 10:{index:02d}:00", "close_time": f"2026-07-01 10:{index:02d}:30",
                "volume": 1.0, "profit": 1,
            }
            for index in range(5)
        ] + [
            {
                "ticket": f"N{index}", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 11:{index:02d}:00", "close_time": f"2026-07-01 11:{index:02d}:30",
                "volume": 0.01, "profit": 0,
            }
            for index in range(5)
        ]
        finance = {"available": False, "reason": "test"}
        with patch.object(app, "query_db_trades", return_value=rows), \
             patch.object(app, "toxic_finance_summary", return_value=finance), \
             patch.object(app, "toxic_cross_account_sync", return_value={"available": False}) as sync_call, \
             patch.object(app, "toxic_winning_ticks", return_value={"available": False}) as tick_call, \
             patch.object(app, "calculate_toxic_results", return_value=[]) as score_call:
            app.run_toxic_job("FILTER-CHAIN", "900001", "selected", ["market_pushing"], {})
        expected = {f"C{index}" for index in range(5)}
        self.assertEqual({row["ticket"] for row in sync_call.call_args.args[1]}, expected)
        self.assertEqual({row["ticket"] for row in tick_call.call_args.args[1]}, expected)
        self.assertEqual({row["ticket"] for row in score_call.call_args.args[1]}, expected)
        self.assertEqual(app.get_toxic_job("FILTER-CHAIN")["result"]["analysisOrderCount"], 5)

    def test_market_push_filter_does_not_change_other_selected_detectors(self):
        rows = [
            {
                "ticket": f"C{index}", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 10:{index:02d}:00", "close_time": f"2026-07-01 10:{index:02d}:30",
                "volume": 1.0, "profit": 1,
            }
            for index in range(5)
        ] + [
            {
                "ticket": f"N{index}", "platform": "MT4", "server": "AC MT4", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 11:{index:02d}:00", "close_time": f"2026-07-01 11:{index:02d}:30",
                "volume": 0.01, "profit": 0,
            }
            for index in range(5)
        ]
        finance = {"available": False, "reason": "test"}
        with patch.object(app, "query_db_trades", return_value=rows), \
             patch.object(app, "toxic_finance_summary", return_value=finance), \
             patch.object(app, "toxic_cross_account_sync", return_value={"available": False}), \
             patch.object(app, "toxic_winning_ticks", return_value={"available": False}), \
             patch.object(app, "calculate_toxic_results", return_value=[]) as score_call:
            app.run_toxic_job("FILTER-MULTI", "900001", "selected", ["market_pushing", "quote_latency_arbitrage"], {})
        self.assertEqual(score_call.call_args_list[0].args[2], ["market_pushing"])
        self.assertEqual(len(score_call.call_args_list[0].args[1]), 5)
        self.assertEqual(score_call.call_args_list[1].args[2], ["quote_latency_arbitrage"])
        self.assertEqual(len(score_call.call_args_list[1].args[1]), 10)

    def test_concentrated_trading_without_platform_peers_keeps_own_risk_score(self):
        rows = []
        for index in range(15):
            day = index // 3 + 1
            profit = -50 if index in {2, 5, 8, 11, 14} else 100
            rows.append({
                "ticket": f"P{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-{day:02d} 10:{index % 3 * 10:02d}:00",
                "close_time": f"2026-07-{day:02d} 10:{index % 3 * 10 + 5:02d}:00",
                "volume": 0.5, "profit": profit, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
            })
        result = app.calculate_toxic_results(
            "900200", rows, ["market_pushing"], "deep", self.finance,
            {"available": False, "reason": "test without ticks"},
            {"available": False, "reason": "test without sync"},
        )[0]
        self.assertGreaterEqual(result["score"], 75)
        self.assertIn("主要仓位集中在短时段，结束后长时间停手", result["triggeredRules"])
        self.assertIn("协同仅作为同伙线索和加分项，不影响主体推盘嫌疑", "；".join(result["limitations"]))
        analysis = {item["title"]: item["text"] for item in result["analysis"]}
        self.assertIn("集中进场、短时持仓、随后长时间安静", analysis["主要依据"])
        self.assertIn("本次没有取得可用 Tick", analysis["报价证据"])

    def test_early_winning_ticks_without_platform_peers_keep_own_risk_score(self):
        rows = []
        for index in range(12):
            day = index // 3 + 1
            rows.append({
                "ticket": f"W{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                "type": "buy" if index % 2 else "sell",
                "open_time": f"2026-07-{day:02d} 10:{index % 3 * 10:02d}:00",
                "close_time": f"2026-07-{day:02d} 10:{index % 3 * 10 + 5:02d}:00",
                "volume": 0.5, "profit": 100, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
            })
        tick = {
            "available": True, "accountOrders": 12, "candidateOrders": 12, "sampledOrders": 12,
            "analyzedOrders": 12, "coverageRatio": 100, "accountCoverageRatio": 100,
            "priceWinTickMedian": 1, "netWinTickMedian": 2,
            "win1VolumeRatio": 70, "win3VolumeRatio": 90, "win10VolumeRatio": 100,
            "win1OrderRatio": 60, "win3OrderRatio": 80, "win10OrderRatio": 100,
            "positiveImpact20VolumeRatio": 60, "favorableTickRatio50Median": 70,
            "impactSpreadMultipleMedian": 1, "win50VolumeRatio": 100,
            "sources": [{"terminalServer": "AC-Live"}], "mappings": [{"timeMode": "report_is_GMT"}], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900300", rows, ["market_pushing"], "deep", self.finance, tick,
            {"available": False, "reason": "test without sync"},
        )[0]
        self.assertLess(result["score"], 75)
        self.assertIn("多数盈利单在开仓后极少数原始Tick内开始盈利", result["triggeredRules"])
        analysis = {item["title"]: item["text"] for item in result["analysis"]}
        self.assertIn("赢点只统计最终盈利单", analysis["报价证据"])
        self.assertIn("第 1 个原始 Tick", analysis["报价证据"])
        self.assertIn("约 60.0% 的盈利单", analysis["报价证据"])
        metrics = {item["label"]: item["value"] for item in result["metrics"]}
        self.assertEqual(metrics["盈利单第1 Tick盈利概率"], "60% 订单")

    def test_low_push_score_does_not_call_losses_failed_attempts(self):
        result = app.calculate_toxic_results(
            "900100", self.rows, ["market_pushing"], "deep", self.finance,
            {"available": False, "reason": "test without ticks"},
            {"available": False, "reason": "test without sync"},
        )[0]
        analysis = {item["title"]: item["text"] for item in result["analysis"]}
        self.assertIn("既不能证明、也不能排除", analysis["亏损怎么理解"])
        self.assertNotIn("失败尝试", analysis["亏损怎么理解"])

    def test_partial_push_features_cannot_bypass_cross_conditions(self):
        rows = []
        for index in range(12):
            rows.append({
                "ticket": f"L{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 {index:02d}:00:00",
                "close_time": f"2026-07-01 {index + 2:02d}:00:00",
                "volume": 0.5, "profit": 100, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
            })
        result = app.calculate_toxic_results(
            "900400", rows, ["market_pushing"], "deep", self.finance,
            {"available": False, "reason": "test without ticks"},
            {
                "available": True, "sampledOrders": 12, "coordinatedMatchedRatio": 80,
                "coordinatedVolumeRatio": 80, "coordinatedCloseRatio": 0,
                "recurringPeerAccounts": 10, "maxPeerRatio": 40, "errors": [],
            },
        )[0]
        self.assertLess(result["score"], 60)
        self.assertEqual(result["triggeredRules"], [])
        analysis = {item["title"]: item["text"] for item in result["analysis"]}
        self.assertIn("活跃行情中的碰撞", analysis["主要依据"])

    def test_dynamic_position_campaign_keeps_staged_entries_with_cohesive_exit(self):
        rows = []
        ticket = 0
        for day in (1, 2):
            for hour in (10, 14):
                for offset, second in enumerate((0, 8, 29, 35)):
                    ticket += 1
                    rows.append({
                        "ticket": f"D{ticket}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                        "type": "sell", "open_time": f"2026-07-{day:02d} {hour:02d}:00:{second:02d}",
                        "close_time": f"2026-07-{day:02d} {hour:02d}:05:0{offset}",
                        "volume": 1.0, "profit": 100, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
                    })
        behavior = app.toxic_push_behavior(rows)
        self.assertEqual(behavior["sessionCount"], 4)
        self.assertEqual(behavior["staggeredAddOnOrderRatio"], 0)
        self.assertEqual(behavior["staggeredAddOnVolumeRatio"], 0)
        self.assertEqual(behavior["cohesiveBatchOrderRatio"], 100)
        sync = {
            "available": True, "sampledOrders": len(rows), "coordinatedMatchedRatio": 100,
            "coordinatedVolumeRatio": 100, "coordinatedCloseRatio": 100,
            "recurringPeerAccounts": 3, "maxPeerRatio": 100, "errors": [],
        }
        result = app.calculate_toxic_results(
            "900450", rows, ["market_pushing"], "deep", self.finance,
            {"available": False, "reason": "test without ticks"}, sync,
        )[0]
        self.assertGreaterEqual(result["score"], 75)
        self.assertNotIn("推盘分数已封顶", "；".join(result["limitations"]))
        self.assertIn("多数订单与多个账户在2秒内同向同步", result["triggeredRules"])
        analysis = {item["title"]: item["text"] for item in result["analysis"]}
        self.assertIn("完整动态轮次", analysis["仓位结构"])

    def test_dynamic_position_campaign_keeps_non_overlapping_cohesive_waves(self):
        rows = []
        for wave in range(4):
            minute = wave * 10
            for offset in range(3):
                rows.append({
                    "ticket": f"B{wave}-{offset}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                    "type": "buy", "open_time": f"2026-07-01 10:{minute:02d}:0{offset}",
                    "close_time": f"2026-07-01 10:{minute + 1:02d}:0{offset}",
                    "volume": 0.5, "profit": 100,
                })
        behavior = app.toxic_push_behavior(rows)
        self.assertEqual(behavior["sessionCount"], 1)
        self.assertEqual(behavior["staggeredAddOnOrderRatio"], 0)
        self.assertEqual(behavior["cohesiveCampaignOrderRatio"], 0)
        self.assertEqual(behavior["cohesiveBatchOrderRatio"], 100)

    def test_single_local_sync_episode_does_not_upgrade_mixed_account(self):
        rows = [
            {
                "ticket": f"E{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 10:00:0{index}",
                "close_time": f"2026-07-01 10:05:0{index}", "volume": 1.0, "profit": 100,
            }
            for index in range(5)
        ]
        sync = {
            "available": True, "sampledOrders": 5, "coordinatedMatchedRatio": 100,
            "coordinatedVolumeRatio": 100, "coordinatedCloseRatio": 100,
            "recurringPeerAccounts": 2, "maxPeerRatio": 100,
            "sampledOrderMatches": [
                {"ticket": row["ticket"], "volume": 1, "peers": ["Live/900901"], "closePeers": ["Live/900901"]}
                for row in rows
            ],
        }
        tick = {"available": True, "positiveImpact20VolumeRatio": 60, "favorableTickRatio50Median": 70, "win10VolumeRatio": 60}
        mixed = app.toxic_push_mixed_episode_summary(rows, sync, tick)
        self.assertEqual(mixed["candidateEpisodes"], 1)
        self.assertEqual(mixed["confirmedEpisodes"], 0)
        self.assertFalse(mixed["confirmed"])

    def test_repeated_local_sync_episodes_upgrade_mixed_grid_account(self):
        grid_rows = []
        for wave in range(4):
            for offset in range(3):
                minute = wave * 10
                grid_rows.append({
                    "ticket": f"G{wave}-{offset}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                    "type": "buy", "open_time": f"2026-07-01 10:{minute:02d}:0{offset}",
                    "close_time": f"2026-07-01 11:{minute:02d}:00", "volume": 0.2, "profit": 20,
                    "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
                })
        episode_rows = []
        for day in (2, 3):
            for index in range(5):
                episode_rows.append({
                    "ticket": f"P{day}-{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                    "type": "sell", "open_time": f"2026-07-{day:02d} 10:00:0{index}",
                    "close_time": f"2026-07-{day:02d} 10:05:0{index}", "volume": 1.0, "profit": 100,
                    "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
                })
        rows = grid_rows + episode_rows
        sync = {
            "available": True, "sampledOrders": len(rows), "coordinatedMatchedRatio": 100,
            "coordinatedVolumeRatio": 100, "coordinatedCloseRatio": 100,
            "recurringPeerAccounts": 3, "maxPeerRatio": 100, "errors": [],
            "sampledOrderMatches": [
                {"ticket": row["ticket"], "volume": row["volume"], "peers": ["Live/900902"], "closePeers": ["Live/900902"]}
                for row in rows
            ],
        }
        tick = {
            "available": True, "accountOrders": len(rows), "candidateOrders": len(rows), "sampledOrders": len(rows),
            "analyzedOrders": len(rows), "coverageRatio": 100, "accountCoverageRatio": 100,
            "priceWinTickMedian": 10, "netWinTickMedian": 12,
            "win1VolumeRatio": 0, "win3VolumeRatio": 20, "win10VolumeRatio": 60,
            "win1OrderRatio": 0, "win3OrderRatio": 20, "win10OrderRatio": 60,
            "positiveImpact20VolumeRatio": 65, "favorableTickRatio50Median": 75,
            "impactSpreadMultipleMedian": 1, "win50VolumeRatio": 80,
            "sources": [], "mappings": [], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900600", rows, ["market_pushing"], "deep", self.finance, tick, sync,
        )[0]
        self.assertGreaterEqual(result["score"], 90)
        self.assertTrue(result["mixedEpisodes"]["confirmed"])
        self.assertEqual(result["mixedEpisodes"]["confirmedEpisodes"], 2)
        self.assertIn("正常或网格交易中反复出现独立协同打盘轮次", result["triggeredRules"])
        self.assertNotIn("推盘分数已封顶", "；".join(result["limitations"]))

    def test_ea_attention_allows_strong_repeated_episodes_below_normal_volume_cutoff(self):
        rows = []
        for day in (2, 3):
            for index in range(5):
                rows.append({
                    "ticket": f"EA-{day}-{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                    "type": "sell", "open_time": f"2026-07-{day:02d} 10:00:0{index}",
                    "close_time": f"2026-07-{day:02d} 10:05:0{index}", "volume": 0.85, "profit": 100,
                    "expert_id": "149",
                })
        for index in range(10):
            rows.append({
                "ticket": f"EA-N-{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                "type": "buy" if index % 2 else "sell", "open_time": f"2026-07-01 12:{index:02d}:00",
                "close_time": f"2026-07-01 12:{index:02d}:30", "volume": 9.15, "profit": 10,
                "expert_id": "149",
            })
        sync = {
            "available": True, "sampledOrders": 20, "coordinatedMatchedRatio": 50,
            "coordinatedVolumeRatio": 50, "coordinatedCloseRatio": 50,
            "recurringPeerAccounts": 2, "maxPeerRatio": 50, "errors": [],
            "sampledOrderMatches": [
                {"ticket": row["ticket"], "volume": row["volume"], "peers": ["Live/901001"], "closePeers": ["Live/901001"]}
                if row["ticket"].startswith("EA-") and "EA-N" not in row["ticket"]
                else {"ticket": row["ticket"], "volume": row["volume"], "peers": [], "closePeers": []}
                for row in rows
            ],
        }
        tick = {"available": True, "positiveImpact20VolumeRatio": 60, "favorableTickRatio50Median": 70, "win10VolumeRatio": 60}
        mixed = app.toxic_push_mixed_episode_summary(rows, sync, tick)
        self.assertTrue(mixed["eaAttention"])
        self.assertEqual(mixed["volumeThreshold"], 8)
        self.assertTrue(mixed["confirmed"])
        self.assertGreaterEqual(mixed["confirmedVolumeRatio"], 8)

    def test_staggered_addons_cap_push_score_even_with_strong_sync(self):
        rows = []
        for batch in range(4):
            for offset in range(3):
                minute = batch * 10
                rows.append({
                    "ticket": f"G{batch}-{offset}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                    "type": "buy", "open_time": f"2026-07-01 10:{minute:02d}:0{offset}",
                    "close_time": f"2026-07-01 11:{minute:02d}:00",
                    "volume": 0.5, "profit": 100, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
                })
        sync = {
            "available": True, "sampledOrders": 12, "coordinatedMatchedRatio": 100,
            "coordinatedVolumeRatio": 100, "coordinatedCloseRatio": 100,
            "recurringPeerAccounts": 10, "maxPeerRatio": 100, "errors": [],
            "sampledOrderMatches": [
                {"ticket": row["ticket"], "volume": row["volume"], "peers": ["Live/900999"], "closePeers": ["Live/900999"]}
                for row in rows
            ],
        }
        result = app.calculate_toxic_results(
            "900500", rows, ["market_pushing"], "deep", self.finance,
            {"available": False, "reason": "test without ticks"}, sync,
        )[0]
        behavior = app.toxic_push_behavior(rows)
        self.assertGreaterEqual(behavior["staggeredAddOnOrderRatio"], 70)
        self.assertLess(result["score"], 60)
        self.assertIn("反证扣分", "；".join(result["limitations"]))
        self.assertIn("不再将账户总分硬封顶", "；".join(result["limitations"]))
        analysis = {item["title"]: item["text"] for item in result["analysis"]}
        self.assertIn("网格加仓", analysis["仓位结构"])

    def test_dynamic_liquidity_chain_only_marks_review_without_external_benchmark(self):
        rows = []
        for index in range(8):
            rows.append({
                "ticket": f"DL-{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 {8 + index:02d}:00:00",
                "close_time": f"2026-07-01 {10 + index:02d}:00:00", "volume": 0.5, "profit": 100,
            })
        sync = {
            "available": True, "sampledOrders": 8, "coordinatedMatchedRatio": 50,
            "coordinatedVolumeRatio": 50, "coordinatedCloseRatio": 0,
            "recurringPeerAccounts": 1, "maxPeerRatio": 50, "errors": [],
        }
        tick = {
            "available": True, "accountOrders": 8, "candidateOrders": 8, "sampledOrders": 8,
            "analyzedOrders": 8, "coverageRatio": 100, "accountCoverageRatio": 100,
            "eventImpact10VolumeRatio": 70, "eventAcceleration10VolumeRatio": 65,
            "eventPersistence60VolumeRatio": 70, "preexistingTrendVolumeRatio": 30,
            "reversal180VolumeRatio": 60, "spreadExpansionRatioMedian": 1.1,
            "sources": [], "mappings": [], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900700", rows, ["market_pushing"], "deep", self.finance, tick, sync,
        )[0]
        self.assertLess(result["score"], 60)
        self.assertIn("订单后出现超过入场前节奏的持续报价冲击，建议核对外部基准", result["triggeredRules"])
        self.assertIn("外部基准报价复核", "；".join(result["limitations"]))

    def test_dense_single_campaign_requires_tick_chain_before_high_risk(self):
        rows = []
        for index in range(12):
            rows.append({
                "ticket": f"SB-{index}", "platform": "MT4", "server": "Live", "symbol": "GBPNZD",
                "type": "buy", "open_time": f"2026-07-01 10:00:{index * 5:02d}",
                "close_time": f"2026-07-01 10:{14 + index // 2:02d}:{(index % 2) * 30:02d}",
                "volume": 0.9, "profit": 30, "commission": 0, "fee": 0, "swap": 0, "taxes": 0,
            })
        tick = {
            "available": True, "accountOrders": 12, "candidateOrders": 12, "sampledOrders": 12,
            "analyzedOrders": 12, "coverageRatio": 100, "accountCoverageRatio": 100,
            "eventImpact10VolumeRatio": 56.7, "eventAcceleration10VolumeRatio": 20,
            "eventPersistence60VolumeRatio": 36.7, "positiveImpact20VolumeRatio": 33.3,
            "favorableTickRatio50Median": 50, "impactSpreadMultipleMedian": 0.155,
            "sources": [], "mappings": [], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900704", rows, ["market_pushing"], "deep", self.finance, tick,
            {"available": False, "reason": "no cross-account evidence"},
        )[0]
        self.assertGreaterEqual(result["score"], 75)
        self.assertIn("单轮次内密集同向建仓，短持仓高胜率并伴随订单后报价冲击", result["triggeredRules"])
        metrics = {item["label"]: item["value"] for item in result["metrics"]}
        self.assertEqual(metrics["单轮次集中爆发链"], "成立")
        chain = result["evidenceChain"]
        self.assertEqual(chain["status"], "high")
        self.assertEqual([item["title"] for item in chain["facts"][:3]], ["1. 订单行为", "2. Tick反应", "3. 跨账户协同"])
        self.assertIn("不是单项指标", chain["reasoning"])
        self.assertTrue(any("外部基准报价" in item for item in chain["nextChecks"]))

        weak_tick = {**tick, "eventImpact10VolumeRatio": 49}
        weak_result = app.calculate_toxic_results(
            "900705", rows, ["market_pushing"], "deep", self.finance, weak_tick,
            {"available": False, "reason": "no cross-account evidence"},
        )[0]
        self.assertLess(weak_result["score"], 75)
        self.assertNotIn("单轮次内密集同向建仓，短持仓高胜率并伴随订单后报价冲击", weak_result["triggeredRules"])

    def test_coordinated_tick_chain_requires_synchronized_exits(self):
        behavior = {
            "coreOrders": 14, "concentratedCoreVolumeRatio": 100,
            "coreShortHoldVolumeRatio": 100, "staggeredAddOnVolumeRatio": 0,
        }
        sync = {
            "available": True, "sampledOrders": 14, "coordinatedMatchedRatio": 85.7,
            "coordinatedVolumeRatio": 85.7, "coordinatedCloseRatio": 71.4,
            "maxPeerMatches": 12, "maxPeerRatio": 85.7,
        }
        tick = {
            "available": True, "analyzedOrders": 11, "eventImpact10VolumeRatio": 54.5,
            "positiveImpact20VolumeRatio": 63.6, "favorableTickRatio50Median": 72,
        }
        self.assertTrue(app.toxic_coordinated_tick_chain(behavior, sync, tick))
        self.assertFalse(app.toxic_coordinated_tick_chain(behavior, {**sync, "coordinatedCloseRatio": 59}, tick))
        self.assertFalse(app.toxic_coordinated_tick_chain(behavior, sync, {**tick, "eventImpact10VolumeRatio": 49}))

    def test_sudden_exposure_chain_requires_funding_round_trip(self):
        behavior = {
            "coreOrders": 3, "coreOpenSpanSeconds": 1, "symbolConcentration": 100,
            "maxSameDirectionRunRatio": 100, "cohesiveCampaignOrderRatio": 100,
            "coreShortHoldVolumeRatio": 100, "winRate": 100, "lossVolumeRatio": 0,
        }
        tick = {
            "available": True, "analyzedOrders": 3, "eventImpact10VolumeRatio": 100,
            "eventPersistence60VolumeRatio": 100, "favorableTickRatio50Median": 92,
        }
        finance = {
            "available": True, "depositTotal": 37106.71, "withdrawalTotal": 38213.42,
            "firstDepositToTradeHours": 16.5, "lastTradeToWithdrawalHours": 9.7,
            "highestHoldingVolume": 3.64,
        }
        self.assertTrue(app.toxic_sudden_exposure_chain(behavior, tick, finance, True))
        self.assertFalse(app.toxic_sudden_exposure_chain(behavior, tick, {**finance, "lastTradeToWithdrawalHours": 25}, True))
        self.assertFalse(app.toxic_sudden_exposure_chain(behavior, tick, finance, False))

    def test_partial_dynamic_liquidity_does_not_bypass_grid_cap(self):
        rows = []
        for index in range(8):
            rows.append({
                "ticket": f"DL-N-{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 {8 + index:02d}:00:00",
                "close_time": f"2026-07-01 {10 + index:02d}:00:00", "volume": 0.5, "profit": 100,
            })
        tick = {
            "available": True, "accountOrders": 8, "candidateOrders": 8, "sampledOrders": 8,
            "analyzedOrders": 8, "coverageRatio": 100, "accountCoverageRatio": 100,
            "eventImpact10VolumeRatio": 80, "eventAcceleration10VolumeRatio": 20,
            "eventPersistence60VolumeRatio": 80, "preexistingTrendVolumeRatio": 30,
            "reversal180VolumeRatio": 50, "spreadExpansionRatioMedian": 1.0,
            "sources": [], "mappings": [], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900701", rows, ["market_pushing"], "deep", self.finance, tick,
            {"available": False, "reason": "test without sync"},
        )[0]
        self.assertLess(result["score"], 60)
        self.assertNotIn("订单后出现超过入场前节奏的持续报价冲击，建议核对外部基准", result["triggeredRules"])

    def test_small_sample_with_repeated_mirror_and_tick_evidence_warns(self):
        rows = []
        for index, (opened, closed, direction, volume, profit) in enumerate([
            ("2026-07-01 10:00:00", "2026-07-01 10:01:00", "buy", 2.0, 100),
            ("2026-07-01 10:03:00", "2026-07-01 10:14:00", "buy", 2.0, -20),
            ("2026-07-01 20:00:00", "2026-07-01 20:04:00", "sell", 1.0, 100),
            ("2026-07-01 21:00:00", "2026-07-01 21:06:00", "buy", 1.0, 100),
        ]):
            rows.append({
                "ticket": f"SM-{index}", "platform": "MT4", "server": "Live", "symbol": "XAUUSD",
                "type": direction, "open_time": opened, "close_time": closed,
                "volume": volume, "profit": profit, "expert_id": "5616",
            })
        sync = {
            "available": True, "sampledOrders": 4, "matchedOrders": 3,
            "coordinatedMatchedRatio": 50, "coordinatedVolumeRatio": 33.3,
            "coordinatedCloseRatio": 50, "recurringPeerAccounts": 1,
            "maxPeerMatches": 2, "maxPeerRatio": 50, "errors": [],
            "sampledOrderMatches": [
                {"ticket": "SM-0", "volume": 2, "peers": [], "closePeers": []},
                {"ticket": "SM-1", "volume": 2, "peers": [], "closePeers": []},
                {"ticket": "SM-2", "volume": 1, "peers": ["Live/900800"], "closePeers": ["Live/900800"]},
                {"ticket": "SM-3", "volume": 1, "peers": ["Live/900800"], "closePeers": ["Live/900800"]},
            ],
        }
        tick = {
            "available": True, "accountOrders": 4, "candidateOrders": 2, "sampledOrders": 2,
            "analyzedOrders": 2, "coverageRatio": 100, "accountCoverageRatio": 100,
            "eventImpact10VolumeRatio": 100, "eventAcceleration10VolumeRatio": 30,
            "eventPersistence60VolumeRatio": 100, "preexistingTrendVolumeRatio": 100,
            "positiveImpact20VolumeRatio": 100, "favorableTickRatio50Median": 54,
            "spreadExpansionRatioMedian": 1, "sources": [], "mappings": [], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900702", rows, ["market_pushing"], "deep", self.finance, tick, sync,
        )[0]
        self.assertGreaterEqual(result["score"], 75)
        self.assertIn("订单虽少，但固定账户同步开平仓、短持仓和Tick持续性同时明显", result["triggeredRules"])
        self.assertIn("样本较少", "；".join(result["limitations"]))

    def test_small_sample_without_cross_evidence_stays_unidentified(self):
        rows = []
        for index in range(4):
            rows.append({
                "ticket": f"SM-N-{index}", "platform": "MT5", "server": "Live", "symbol": "XAUUSD",
                "type": "buy", "open_time": f"2026-07-01 10:{index * 5:02d}:00",
                "close_time": f"2026-07-01 10:{index * 5 + 2:02d}:00",
                "volume": 0.1, "profit": 10,
            })
        tick = {
            "available": True, "accountOrders": 4, "candidateOrders": 4, "sampledOrders": 4,
            "analyzedOrders": 4, "coverageRatio": 100, "accountCoverageRatio": 100,
            "eventImpact10VolumeRatio": 40, "eventAcceleration10VolumeRatio": 20,
            "eventPersistence60VolumeRatio": 40, "positiveImpact20VolumeRatio": 40,
            "favorableTickRatio50Median": 45, "spreadExpansionRatioMedian": 1,
            "sources": [], "mappings": [], "errors": [],
        }
        result = app.calculate_toxic_results(
            "900703", rows, ["market_pushing"], "deep", self.finance, tick,
            {"available": False, "reason": "no cross-account evidence"},
        )[0]
        self.assertLess(result["score"], 60)
        self.assertNotIn("订单虽少，但固定账户同步开平仓、短持仓和Tick持续性同时明显", result["triggeredRules"])
        chain = result["evidenceChain"]
        self.assertEqual(chain["status"], "unconfirmed")
        self.assertIn("不是风险为零", chain["headline"])
        self.assertTrue(any("核心订单只有" in item for item in chain["uncertainties"]))
        self.assertIn("尚未达到高危", chain["reasoning"])

    def test_cross_account_sync_math_dependency_is_available(self):
        self.assertEqual(app.math.ceil(2.1), 3)

    def test_cross_account_sources_query_concurrently_and_retain_source_order(self):
        barrier = app.threading.Barrier(2)
        sources = [
            {"name": "First", "server": "First"},
            {"name": "Second", "server": "Second"},
        ]

        def load(source, *_args):
            barrier.wait(timeout=2)
            return [{"source": source["name"]}]

        with patch.object(app, "toxic_sync_candidates_for_source", side_effect=load):
            results = app.toxic_sync_candidates_across_sources(
                sources,
                "638650",
                {"2026-07-01 10:00:00"},
                {"XAUUSD"},
                {"buy"},
            )
        self.assertEqual([item["server"] for item in results], ["First", "Second"])
        self.assertEqual([item["candidates"][0]["source"] for item in results], ["First", "Second"])
        self.assertTrue(all(not item["error"] for item in results))

    def test_sync_candidate_query_filters_symbol_and_direction_in_sql(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {"kind": "mt5_deals", "schema": "risk", "table": "mt5_deals", "server": "Live"}
        with patch.object(app, "mysql_trade_connect", return_value=connection):
            result = app.toxic_sync_candidates_for_source(
                source,
                "638650",
                {"2026-07-01 10:00:00"},
                {"XAUUSD.r"},
                {"buy"},
            )
        self.assertEqual(result, [])
        sql, params = cursor.execute.call_args.args
        self.assertIn("Action in (%s)", sql)
        self.assertIn("SUBSTRING_INDEX(Symbol", sql)
        self.assertEqual(params, [0, 638650, "2026-07-01 10:00:00", "XAUUSD"])

    def test_cross_account_sync_uses_filtered_candidates_without_changing_matches(self):
        rows = [{
            "ticket": "T-1", "data_source": "mysql", "platform": "MT5", "server": "Live",
            "symbol": "XAUUSD.r", "type": "buy", "open_time": "2026-07-01 10:00:00",
            "close_time": "2026-07-01 10:01:00", "volume": 1,
        }]
        candidates = [
            {
                "login": "Live/900800", "account": "900800", "server": "Live", "position": 10,
                "direction": "buy", "symbol": "XAUUSD", "opened": app.parse_trade_time("2026-07-01 10:00:02"),
                "closed": app.parse_trade_time("2026-07-01 10:01:02"),
            },
            {
                "login": "Live/900801", "account": "900801", "server": "Live", "position": 11,
                "direction": "sell", "symbol": "XAUUSD", "opened": app.parse_trade_time("2026-07-01 10:00:00"),
                "closed": app.parse_trade_time("2026-07-01 10:01:00"),
            },
        ]
        source = {"name": "Live", "platform": "MT5", "server": "Live"}
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "toxic_sync_candidates_for_source", return_value=candidates) as candidate_query:
            result = app.toxic_cross_account_sync("638650", rows)
        self.assertEqual(result["matchedOrders"], 1)
        self.assertEqual(result["closeMatchedRatio"], 100.0)
        self.assertEqual(result["peerAccounts"], 1)
        self.assertEqual(result["performance"]["candidateOrders"], 2)
        _, _, target_seconds, target_symbols, target_directions = candidate_query.call_args.args
        self.assertEqual(len(target_seconds), 5)
        self.assertEqual(target_symbols, {"XAUUSD"})
        self.assertEqual(target_directions, {"buy"})

    def test_cross_account_sync_exposes_order_pair_comparisons_for_recurring_peers(self):
        rows = [
            {
                "ticket": "T-1", "data_source": "mysql", "platform": "MT4", "server": "AC MT4",
                "symbol": "XAUUSD.P", "type": "buy", "open_time": "2026-07-01 10:00:00",
                "close_time": "2026-07-01 10:00:05", "volume": 0.1,
            },
            {
                "ticket": "T-2", "data_source": "mysql", "platform": "MT4", "server": "AC MT4",
                "symbol": "XAUUSD.P", "type": "buy", "open_time": "2026-07-01 11:00:00",
                "close_time": "2026-07-01 11:00:05", "volume": 0.2,
            },
        ]
        candidates = [
            {
                "login": "AC MT4/7002718", "account": "7002718", "platform": "MT4", "server": "AC MT4",
                "position": 101, "direction": "buy", "symbol": "XAUUSD", "volume": 0.1,
                "opened": app.parse_trade_time("2026-07-01 10:00:01"),
                "closed": app.parse_trade_time("2026-07-01 10:00:06"),
            },
            {
                "login": "AC MT4/7002718", "account": "7002718", "platform": "MT4", "server": "AC MT4",
                "position": 102, "direction": "buy", "symbol": "XAUUSD", "volume": 0.3,
                "opened": app.parse_trade_time("2026-07-01 11:00:02"),
                "closed": app.parse_trade_time("2026-07-01 11:00:09"),
            },
        ]
        source = {"name": "AC MT4", "platform": "MT4", "server": "AC MT4"}
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "toxic_sync_candidates_for_source", return_value=candidates):
            result = app.toxic_cross_account_sync("7002769", rows)
        self.assertEqual(result["comparisonTotal"], 2)
        self.assertEqual(result["comparisonRows"][0]["peerAccount"], "7002718")
        self.assertEqual(result["comparisonRows"][0]["peerTicket"], "101")
        self.assertTrue(result["comparisonRows"][0]["closeSynchronized"])
        self.assertFalse(result["comparisonRows"][1]["closeSynchronized"])
        self.assertEqual(result["comparisonRows"][1]["closeDeltaSeconds"], 4)

    def test_recurring_sync_peers_are_returned_as_suspected_accounts(self):
        with patch.object(app, "MYSQL_SOURCES", [{"platform": "MT4", "server": "AC MT4"}]):
            suspected = app.toxic_suspected_accounts(
                [("AC MT4/5001001", 8), ("AC MT4/5001002", 1)],
                {"AC MT4/5001001"},
                {"AC MT4/5001001": 5},
                10,
            )
        self.assertEqual(suspected, [{
            "platform": "MT4", "server": "AC MT4", "account": "5001001",
            "matches": 8, "matchRatio": 80.0, "closeMatches": 5, "closeMatchRatio": 50.0,
        }])

    def test_market_push_result_exposes_suspected_accomplices(self):
        suspected = [{"platform": "MT4", "server": "AC MT4", "account": "5001001", "matches": 8}]
        result = app.calculate_toxic_results(
            "900100", self.rows, ["market_pushing"], "deep", self.finance,
            {"available": False, "reason": "test without ticks"},
            {
                "available": True, "sampledOrders": 2, "coordinatedMatchedRatio": 100,
                "coordinatedVolumeRatio": 100, "coordinatedCloseRatio": 50,
                "recurringPeerAccounts": 1, "maxPeerRatio": 100, "suspectedAccounts": suspected, "errors": [],
            },
        )[0]
        self.assertEqual(result["suspectedAccomplices"], suspected)

    def test_account_detail_ui_renders_suspected_accomplices(self):
        self.assertIn("疑似同伙账户", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("suspectedAccomplices", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("同步订单逐笔对比", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("comparisonRows", app.ACCOUNT_DETAIL_HTML)

    def test_workbench_exposes_configurable_push_discovery_order_limit(self):
        self.assertIn('id="pushDiscoveryMaxOrders"', app.WORKBENCH_HTML)
        self.assertIn("/api/push-discovery/start", app.WORKBENCH_HTML)


if __name__ == "__main__":
    unittest.main()
