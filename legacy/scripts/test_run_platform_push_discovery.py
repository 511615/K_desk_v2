import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from scripts import run_platform_push_discovery as runner


class PushDiscoveryTests(unittest.TestCase):
    def test_excluded_logins_only_uses_confirmed_actions(self):
        records = [
            {"账号": "100", "建议动作": "T"},
            {"账号": "101", "建议动作": "TA"},
            {"账号": "102", "建议动作": "A"},
            {"账号": "103", "建议动作": "A/TA"},
            {"账号": "104", "建议动作": "P->A/T"},
            {"账号": "105", "建议动作": "P"},
        ]
        self.assertEqual(runner.excluded_logins(records), {"100", "101", "102", "103"})

    def test_initial_score_below_40_routes_strong_structure_to_deep_check(self):
        rows = [{"ticket": str(index)} for index in range(20)]
        context = {
            "rows": rows,
            "filter": {},
            "behavior": {
                "concentratedCoreVolumeRatio": 92,
                "coreShortHoldVolumeRatio": 88,
                "quietGapRatio": 45,
                "eaVolumeRatio": 0,
                "copyVolumeRatio": 0,
            },
        }
        with patch.object(runner.app, "toxic_build_push_context", return_value=context), \
             patch.object(runner.app, "calculate_toxic_results", return_value=[{
                 "score": 30, "level": "无明显风险", "confidence": 50,
                 "triggeredRules": [],
             }]):
            result = runner.screen_candidate(
                {"login": "900001", "source": "Live", "server": "Live", "platform": "MT5"},
                rows,
                200,
            )
        self.assertTrue(result["deepEligible"])
        self.assertIn("集中度、短持仓和动态停手同时明显", result["routeReasons"])

    def test_default_order_limit_is_200_and_remains_configurable(self):
        with patch.object(sys, "argv", ["runner"]):
            args = runner.parse_args()
            self.assertEqual(args.max_orders, 200)
            self.assertTrue(args.require_max_lot)
            self.assertEqual(args.min_max_lot, 0.01)
            self.assertTrue(args.require_total_profit)
            self.assertTrue(args.limit_deposit)
            self.assertEqual(args.max_deposit, 2000)
            self.assertTrue(args.limit_active_ratio)
            self.assertEqual(args.max_active_ratio, 30)
        with patch.object(sys, "argv", ["runner", "--max-orders", "350"]):
            self.assertEqual(runner.parse_args().max_orders, 350)

    def test_all_candidate_limits_can_be_disabled(self):
        with patch.object(sys, "argv", [
            "runner",
            "--no-require-period-profit",
            "--no-limit-orders",
            "--no-require-max-lot",
            "--no-require-total-profit",
            "--no-limit-deposit",
            "--no-limit-active-ratio",
            "--no-exclude-handled",
        ]):
            filters = runner.CandidateFilters.from_args(runner.parse_args())
        self.assertFalse(filters.require_period_profit)
        self.assertFalse(filters.limit_orders)
        self.assertFalse(filters.require_max_lot)
        self.assertFalse(filters.require_total_profit)
        self.assertFalse(filters.limit_deposit)
        self.assertFalse(filters.limit_active_ratio)
        self.assertFalse(filters.exclude_handled)

    def test_window_max_lot_filter_is_strict_and_uses_platform_lot_units(self):
        started = datetime(2026, 7, 16, 0, 0, 0)
        filters = runner.CandidateFilters(
            require_period_profit=False,
            limit_orders=False,
            require_max_lot=True,
            min_max_lot=0.05,
            require_total_profit=False,
            limit_deposit=False,
            limit_active_ratio=False,
            exclude_handled=False,
        )
        cases = [
            ("mt5_deals", "VolumeExt / 100000000.0", {"Login": 700001, "ClosedOrders": 2, "MaxLot": 0.1}),
            ("mt4_trades", "max(VOLUME / 100.0)", {"Login": 700002, "ClosedOrders": 2, "MaxLot": 0.2}),
        ]
        for kind, expected_sql, aggregate_row in cases:
            with self.subTest(kind=kind):
                cursor = MagicMock()
                cursor.fetchall.side_effect = [[aggregate_row], []]
                cursor_context = MagicMock()
                cursor_context.__enter__.return_value = cursor
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.cursor.return_value = cursor_context
                source = {
                    "kind": kind,
                    "name": kind,
                    "platform": "MT5" if kind == "mt5_deals" else "MT4",
                    "server": kind,
                    "schema": "risk",
                    "table": kind,
                }
                with patch.object(runner.app, "mysql_trade_connect", return_value=connection):
                    result = runner.source_candidates(source, started, started + timedelta(days=1), filters)
                sql, params = cursor.execute.call_args_list[0].args
                self.assertIn(expected_sql, sql)
                self.assertIn("MaxLot > %s", sql)
                self.assertEqual(params, [started, started + timedelta(days=1), 0.05])
                self.assertEqual(result[0]["maxLot"], aggregate_row["MaxLot"])

    def test_source_candidates_drop_accounts_owned_by_another_shared_table_route(self):
        started = datetime(2026, 7, 16, 0, 0, 0)
        filters = runner.CandidateFilters(
            require_period_profit=False,
            limit_orders=False,
            require_max_lot=False,
            require_total_profit=False,
            limit_deposit=False,
            limit_active_ratio=False,
            exclude_handled=False,
        )
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [
                {"Login": 6003464, "ClosedOrders": 18, "MaxLot": 0.01, "PeriodNetRaw": 4.68},
                {"Login": 6001345, "ClosedOrders": 12, "MaxLot": 0.02, "PeriodNetRaw": 8.20},
            ],
            [{"mt_login": 6003464}],
            [{"Login": 6003464, "Registration": started, "Status": "", "Currency": "USD", "AccountGroup": "real"}],
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        source = {
            "kind": "mt4_trades",
            "name": "AC MT4",
            "platform": "MT4",
            "server": "AC CN MT4",
            "schema": "mt4_export_syc",
            "table": "mt4_trades",
            "account_route": {"schema": "sass_crm_ac", "mt_server_code": "2"},
        }

        with patch.object(runner.app, "mysql_trade_connect", return_value=connection):
            result = runner.source_candidates(source, started, started + timedelta(days=1), filters)

        self.assertEqual([row["login"] for row in result], ["6003464"])
        route_sql, route_params = cursor.execute.call_args_list[1].args
        self.assertIn("`sass_crm_ac`.`mt_users_account`", route_sql)
        self.assertEqual(route_params, ["2", 6003464, 6001345])

    def test_transient_mysql_failures_are_retryable(self):
        self.assertTrue(runner.transient_mysql_failure(RuntimeError(2013, "lost connection")))
        self.assertTrue(runner.transient_mysql_failure(RuntimeError(2006, "server gone")))
        self.assertFalse(runner.transient_mysql_failure(RuntimeError("bad query")))

    def test_lifetime_candidate_filters_report_each_failed_condition(self):
        filters = runner.CandidateFilters(max_deposit=2000, max_active_ratio=30)
        reasons = runner.candidate_filter_reasons({
            "lifetimeDataAvailable": True,
            "totalNet": -1,
            "depositTotal": 2500,
            "activeRatio": 45,
            "databaseStatus": "TA",
        }, filters)
        self.assertEqual(reasons, [
            "历史交易净收益未大于0",
            "累计入金超过上限或不可用",
            "活跃天数占比超过上限或不可用",
            "数据库状态已处置",
        ])

    def test_disabled_lifetime_filters_do_not_exclude_candidate(self):
        filters = runner.CandidateFilters(
            require_total_profit=False,
            limit_deposit=False,
            limit_active_ratio=False,
            exclude_handled=False,
        )
        self.assertEqual(runner.candidate_filter_reasons({}, filters), [])

    def test_deep_loader_uses_all_mt5_history(self):
        source = {"kind": "mt5_deals", "name": "AC GB MT5"}
        with patch.object(
            runner.mt5_runner,
            "load_all_closed_trades",
            return_value={"rows": [{"ticket": "1"}, {"ticket": "2"}]},
        ) as loader:
            rows = runner.load_deep_rows(source, "638537")
        self.assertEqual(len(rows), 2)
        loader.assert_called_once_with(source, "638537")

    def test_deep_loader_removes_mt4_order_limit(self):
        source = {"kind": "mt4_orders", "name": "AC MT4"}
        source_rows = [
            {"ticket": "1", "close_time": "2026-07-16 08:00:00"},
            {"ticket": "2", "close_time": "1970-01-01 00:00:00"},
        ]
        with patch.object(runner.app, "query_mysql_mt4_source", return_value=source_rows) as loader:
            rows = runner.load_deep_rows(source, "5009191")
        self.assertEqual(rows, [source_rows[0]])
        loader.assert_called_once_with(source, "5009191", limit=None)

    def test_suspected_interval_profit_prefers_coordinated_episode_sessions(self):
        started = datetime(2026, 7, 16, 8, 0, 0)
        first = {"open_time": str(started), "close_time": str(started + timedelta(minutes=1)), "profit": 10, "commission": -1, "volume": 1}
        second = {"open_time": str(started + timedelta(seconds=2)), "close_time": str(started + timedelta(minutes=1)), "profit": -2, "fee": -.5, "volume": 1}
        third = {"open_time": str(started + timedelta(hours=2)), "close_time": str(started + timedelta(hours=2, minutes=1)), "profit": 30, "commission": -2, "volume": 2}
        sessions = [[(started, first), (started + timedelta(seconds=2), second)], [(started + timedelta(hours=2), third)]]
        with patch.object(runner.app, "toxic_dynamic_push_sessions", return_value={"sessions": sessions}):
            result = runner.suspected_push_interval_profit(
                [first, second, third],
                {"candidateSessionIds": [2], "confirmedSessionIds": [], "confirmed": False},
            )
        self.assertEqual(result["basis"], "coordinated_candidate")
        self.assertEqual(result["intervalCount"], 1)
        self.assertEqual(result["orders"], 1)
        self.assertEqual(result["grossProfit"], 30)
        self.assertEqual(result["netProfit"], 28)

    def test_suspected_interval_profit_falls_back_to_multi_order_dynamic_sessions(self):
        started = datetime(2026, 7, 16, 8, 0, 0)
        first = {"open_time": str(started), "close_time": str(started + timedelta(minutes=1)), "profit": 10, "commission": -1, "volume": 1}
        second = {"open_time": str(started + timedelta(seconds=2)), "close_time": str(started + timedelta(minutes=1)), "profit": -2, "fee": -.5, "volume": 1}
        isolated = {"open_time": str(started + timedelta(hours=2)), "close_time": str(started + timedelta(hours=2, minutes=1)), "profit": 30, "volume": 2}
        sessions = [[(started, first), (started + timedelta(seconds=2), second)], [(started + timedelta(hours=2), isolated)]]
        with patch.object(runner.app, "toxic_dynamic_push_sessions", return_value={"sessions": sessions}):
            result = runner.suspected_push_interval_profit([first, second, isolated])
        self.assertEqual(result["basis"], "dynamic_concentration")
        self.assertEqual(result["orders"], 2)
        self.assertEqual(result["grossProfit"], 8)
        self.assertEqual(result["netProfit"], 6.5)
        self.assertEqual(result["costs"], -1.5)


if __name__ == "__main__":
    unittest.main()
