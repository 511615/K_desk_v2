import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app


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
        with patch.object(app, "query_db_trades", return_value=[trade]) as query_trades, \
             patch.object(app, "query_mysql_trade_costs", return_value=empty_costs) as query_costs, \
             patch.object(app, "build_riskdash_panels", return_value={"available": False}), \
             patch.object(app, "TRADE_DB_SOURCE", "mysql"):
            detail = app._account_database_detail_uncached("532573", {"platform": "MT5", "server": "AC GB MT5"})
        self.assertTrue(detail["exists"])
        query_trades.assert_called_once_with("532573", limit=50000, platform="MT5", server="AC GB MT5")
        query_costs.assert_called_once_with("532573", platform="MT5", server="AC GB MT5")

    def test_lookup_finance_returns_database_local_status_and_comprehensive_profit(self):
        source = {"name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals"}
        trade = {"data_source": "mysql", "platform": "MT5", "server": "Live", "profit": 10}
        ledger = {"建议动作": "P", "状态": "观察中"}
        finance = {"comprehensiveProfit": 37918.02, "displayCurrency": "USD"}
        with patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_db_trades", return_value=[trade]), \
             patch.object(app, "query_mysql_trade_costs", return_value=None), \
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
        finance = {"comprehensiveProfit": 243.38, "displayCurrency": "USD"}
        with patch.object(app, "MYSQL_SOURCES", [cn_source, gb_source]), \
             patch.object(app, "query_db_trades", return_value=[trade]), \
             patch.object(app, "query_mysql_trade_costs", return_value=None), \
             patch.object(app, "query_mt4_finance_panel", return_value=finance) as finance_query, \
             patch.object(app, "query_mt4_database_statuses", return_value={"5010772": "Enabled"}), \
             patch.object(app, "ledger_record_for_login", return_value=None):
            app.account_lookup_finance_payload("5010772", "MT4", "AC MT4")

        finance_query.assert_called_once_with(gb_source, "5010772", [trade], unittest.mock.ANY)

    def test_lookup_finance_old_dbg_mt5_alias_uses_server_resolved_from_rows(self):
        cn_source = {"name": "DBG MT5", "platform": "MT5", "server": "DBG CN MT5", "aliases": ["DBG MT5"], "kind": "mt5_deals"}
        gb_source = {"name": "DBG GB MT5", "platform": "MT5", "server": "DBG GB MT5", "kind": "mt5_deals"}
        trade = {"data_source": "mysql", "platform": "MT5", "server": "DBG GB MT5", "profit": 10}
        finance = {"comprehensiveProfit": 15.25, "displayCurrency": "USD"}
        with patch.object(app, "MYSQL_SOURCES", [cn_source, gb_source]), \
             patch.object(app, "query_db_trades", return_value=[trade]), \
             patch.object(app, "query_mysql_trade_costs", return_value=None), \
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
             patch.object(app, "query_same_name_logins", return_value=["900001"]), \
             patch.object(app, "query_mt5_database_statuses", return_value={"900001": "M"}):
            panel = app.build_riskdash_panels("900001", [{"platform": "MT5", "server": "Live"}], {}, [])
        self.assertEqual(panel["sameName"][0]["databaseStatus"], "M")
        self.assertEqual(panel["sameName"][0]["localStatus"], "M")
        self.assertNotEqual(panel["sameName"][0]["localStatus"], "观察中")

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
             patch.object(app, "query_same_name_logins", return_value=["900004"]), \
             patch.object(app, "query_mt4_database_statuses", return_value={"900004": "Enabled"}):
            panel = app.build_riskdash_panels("900004", rows, {}, rows)

        self.assertTrue(panel["available"])
        self.assertEqual(panel["sameName"][0]["platform"], "MT4")
        self.assertEqual(panel["sameName"][0]["account"], "900004")
        self.assertEqual(panel["sameName"][0]["databaseStatus"], "Enabled")
        self.assertEqual(panel["finance"]["balance"], 100)
        finance_query.assert_called_once_with(source, "900004", rows, {})


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

    def test_cpt_comment_marks_copy_trade(self):
        row = {"comment": "CPT-SS#348815929 / CPT-SS#348821201"}
        self.assertTrue(app.is_copy_trade(row))
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

    def test_copy_origin_lookup_groups_initiating_accounts_by_cpt_order_id(self):
        copied_rows = [{"comment": "CPT-SS#348815929 / CPT-SS#348821201"}]
        source = {"name": "Live", "platform": "MT5", "server": "Live", "kind": "mt5_deals"}
        candidates = [
            {"account": "700001", "platform": "MT5", "server": "Live", "ticket": "348815929", "matchedOrderIds": ["348815929"], "time": "2026-07-01 10:00:00", "symbol": "XAUUSD", "comment": "source"},
            {"account": "700001", "platform": "MT5", "server": "Live", "ticket": "348821201", "matchedOrderIds": ["348821201"], "time": "2026-07-01 10:05:00", "symbol": "XAUUSD", "comment": "source"},
        ]
        follower_rows = [
            {"account": "700002", "platform": "MT5", "server": "Live", "ticket": "5001", "matchedSourceOrderIds": ["348815929"], "openTime": "2026-07-01 10:00:01", "closeTime": "2026-07-01 10:01:01", "symbol": "XAUUSD", "volume": 0.2, "grossProfit": 12, "commission": -1, "swap": 0, "taxes": 0, "netProfit": 11, "currency": "USD", "displayCurrency": "USD"},
            {"account": "700003", "platform": "MT5", "server": "Live", "ticket": "5002", "matchedSourceOrderIds": ["348815929", "348821201"], "openTime": "2026-07-01 10:00:02", "closeTime": "2026-07-01 10:01:02", "symbol": "XAUUSD", "volume": 0.3, "grossProfit": -4, "commission": -1, "swap": -0.5, "taxes": 0, "netProfit": -5.5, "currency": "USD", "displayCurrency": "USD"},
        ]
        with patch.object(app, "query_db_trades", return_value=copied_rows), \
             patch.object(app, "MYSQL_SOURCES", [source]), \
             patch.object(app, "query_copy_origin_source", return_value=candidates) as origin_query, \
             patch.object(app, "query_copy_followers_source", return_value={"rows": follower_rows, "sourceOrdersScanned": 2, "sourceOrdersTruncated": False, "candidateRowsTruncated": False}):
            payload = app.account_copy_origins_payload("700002", {"platform": "MT5", "server": "Live"})

        self.assertTrue(payload["detected"])
        self.assertEqual(payload["primaryOrigin"]["account"], "700001")
        self.assertEqual(payload["primaryOrigin"]["matchedOrders"], 2)
        self.assertEqual(payload["primaryOrigin"]["sampleOrderIds"], ["348815929", "348821201"])
        self.assertEqual(len(payload["primaryOrigin"]["sourceOrders"]), 2)
        self.assertEqual(payload["primaryOrigin"]["orders"], 1)
        self.assertEqual(payload["primaryOrigin"]["copyOrderRatio"], 100)
        self.assertEqual(payload["primaryOrigin"]["followerSummary"]["accounts"], 2)
        self.assertEqual(payload["primaryOrigin"]["followerSummary"]["orders"], 2)
        self.assertEqual(payload["primaryOrigin"]["followerSummary"]["netProfit"], 5.5)
        self.assertTrue(payload["primaryOrigin"]["followers"][0]["isCurrentAccount"])
        self.assertEqual(payload["primaryOrigin"]["followers"][1]["matchedSourceOrders"], 2)
        origin_query.assert_called_once_with(source, ["348815929", "348821201"])

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

    def test_ea_comment_parser_keeps_exact_ea_name_and_rejects_generic_or_copy_comments(self):
        self.assertEqual(app.ea_comment_parts("ChanGold V33 / tp"), ["ChanGold V33"])
        self.assertEqual(app.ea_comment_parts("KLine_Breakout[tp]"), ["KLine_Breakout"])
        self.assertEqual(app.ea_comment_parts("AlphaBot / AlphaBot"), ["AlphaBot"])
        self.assertEqual(app.ea_comment_parts("EA"), [])
        self.assertEqual(app.ea_comment_parts("CPT-SS#348815929"), [])
        self.assertEqual(app.ea_comment_parts("Signal #5009780 IN"), [])
        self.assertEqual(app.ea_comment_parts("from #27060824"), [])

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
        toxic_index = app.ACCOUNT_DETAIL_HTML.index('id="toxicBtn"')
        self.assertLess(copy_index, ea_index)
        self.assertLess(ea_index, toxic_index)
        self.assertIn("/ea-comment-profit", app.ACCOUNT_DETAIL_HTML)
        self.assertIn("相同 Comment 的 EA 账户收益", app.ACCOUNT_DETAIL_HTML)

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
