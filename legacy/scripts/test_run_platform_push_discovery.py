import sys
import unittest
from concurrent.futures import Future
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

    def test_parallel_screen_batches_restore_exact_serial_order(self):
        candidates = [
            {
                "login": str(700000 + index),
                "source": "Live",
                "server": "Live",
                "platform": "MT5",
            }
            for index in range(250)
        ]
        rows_by_source = {"Live": {}}

        class InlineExecutor:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def submit(self, function, *args):
                future = Future()
                future.set_result(function(*args))
                return future

        serial = runner.screen_candidates(candidates, rows_by_source, 100, 1)
        with patch.object(runner, "ProcessPoolExecutor", InlineExecutor):
            parallel = runner.screen_candidates(candidates, rows_by_source, 100, 2)
        self.assertEqual(parallel, serial)

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
                cursor_context = MagicMock()
                cursor_context.__enter__.return_value = MagicMock()
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
                profile = {
                    aggregate_row["Login"]: {
                        "MoneyScale": 1,
                        "Currency": "USD",
                        "LifetimeDataAvailable": False,
                    }
                }
                with patch.object(runner, "_window_candidate_rows", return_value=[aggregate_row]), \
                     patch.object(runner, "_load_candidate_profiles", return_value=profile), \
                     patch.object(runner.app, "mysql_trade_connect", return_value=connection):
                    result = runner.source_candidates(source, started, started + timedelta(days=1), filters)
                self.assertIn(expected_sql, runner._candidate_interval_sql(source))
                self.assertEqual(result[0]["maxLot"], aggregate_row["MaxLot"])

    def test_candidate_shards_are_bounded_by_platform(self):
        started = datetime(2026, 7, 16, 0, 0, 0)
        mt5 = runner._candidate_time_shards(
            {"kind": "mt5_deals"}, started, started + timedelta(days=3)
        )
        mt4 = runner._candidate_time_shards(
            {"kind": "mt4_trades"}, started, started + timedelta(days=3)
        )
        self.assertEqual(len(mt5), 6)
        self.assertEqual(len(mt4), 3)
        self.assertTrue(all(end - start <= timedelta(hours=12) for start, end in mt5))

    def test_mt5_shard_merge_preserves_profit_lot_and_order_upper_bound(self):
        rows = runner._merge_candidate_rows([
            {"Login": 700001, "ClosedOrders": 60, "MaxLot": 0.1, "PeriodNetRaw": 5},
            {"Login": 700001, "ClosedOrders": 60, "MaxLot": 0.2, "PeriodNetRaw": -1},
        ])
        self.assertEqual(rows, [{
            "Login": 700001,
            "ClosedOrders": 120,
            "MaxShardClosedOrders": 60,
            "MaxLot": 0.2,
            "PeriodNetRaw": 4.0,
        }])
        self.assertNotIn("having", runner._candidate_interval_sql({
            "kind": "mt5_deals", "schema": "risk", "table": "mt5_deals"
        }).lower())

    def test_timed_out_candidate_shard_is_bisected(self):
        started = datetime(2026, 7, 16, 0, 0, 0)
        source = {
            "kind": "mt5_deals",
            "name": "MT5",
            "schema": "risk",
            "table": "mt5_deals",
        }

        def connection(rows=None, error=None):
            cursor = MagicMock()
            cursor.execute.side_effect = error
            cursor.fetchall.return_value = rows or []
            cursor_context = MagicMock()
            cursor_context.__enter__.return_value = cursor
            value = MagicMock()
            value.__enter__.return_value = value
            value.cursor.return_value = cursor_context
            return value

        connections = [
            connection(error=RuntimeError(2013, "timed out")),
            connection([{"Login": 1, "ClosedOrders": 1}]),
            connection([{"Login": 2, "ClosedOrders": 1}]),
        ]
        status = MagicMock()
        with patch.object(runner.app, "mysql_trade_connect", side_effect=connections):
            rows = runner._query_candidate_interval(
                source,
                started,
                started + timedelta(hours=12),
                status,
            )
        self.assertEqual([row["Login"] for row in rows], [1, 2])
        status.assert_called_once()

    def test_timed_out_profile_batch_reopens_and_shrinks(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = MagicMock()
        connection.cursor.return_value = cursor_context
        expected = {700001: {"TotalNet": 1}}
        status = MagicMock()
        with patch.object(runner.app, "mysql_trade_connect", return_value=connection), \
             patch.object(
                 runner,
                 "_candidate_profiles",
                 side_effect=[RuntimeError(2013, "timed out"), expected],
             ) as loader:
            result = runner._load_candidate_profiles(
                {"name": "MT5", "host": "database"},
                [700001],
                runner.CandidateFilters(),
                datetime(2026, 7, 16),
                status,
            )
        self.assertEqual(result, expected)
        self.assertEqual(loader.call_args_list[0].kwargs["batch_size"], 10)
        self.assertEqual(loader.call_args_list[1].kwargs["batch_size"], 5)
        status.assert_called_once_with("MT5历史收益批次超时，缩小为每批5账号重试")

    def test_timed_out_mt5_candidate_row_batch_reopens_and_splits(self):
        def connection(error=None):
            cursor = MagicMock()
            cursor.execute.side_effect = error
            cursor.fetchall.return_value = []
            cursor_context = MagicMock()
            cursor_context.__enter__.return_value = cursor
            value = MagicMock()
            value.__enter__.return_value = value
            value.cursor.return_value = cursor_context
            return value

        connections = [
            connection(RuntimeError(2013, "timed out")),
            connection(),
            connection(),
        ]
        source = {
            "kind": "mt5_deals",
            "name": "MT5",
            "schema": "risk",
            "table": "mt5_deals",
        }
        with patch.object(runner.app, "mysql_trade_connect", side_effect=connections):
            rows = runner._load_mt5_candidate_batch(
                source,
                list(range(10)),
                datetime(2026, 7, 16),
                datetime(2026, 7, 17),
            )
        self.assertEqual(rows, {})

    def test_mt5_time_first_candidate_loader_uses_bounded_indexes(self):
        live2 = next(source for source in runner.app.MYSQL_SOURCES if source["name"] == "DBG MT5 Live2")
        self.assertEqual(live2["schema"], "crm_vn_mt5_live2")
        self.assertEqual(live2["account_route"], {"schema": "crm_vn", "mt_server_code": "5"})
        for schema in ("mt5_export_new", "crm_vn_mt5_live2"):
            with self.subTest(schema=schema):
                cursor = MagicMock()
                cursor.fetchall.return_value = []
                cursor_context = MagicMock()
                cursor_context.__enter__.return_value = cursor
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.cursor.return_value = cursor_context
                source = {
                    "kind": "mt5_deals",
                    "name": "DBG MT5",
                    "schema": schema,
                    "table": "mt5_deals",
                }
                with patch.object(runner.app, "mysql_trade_connect", return_value=connection):
                    rows = runner._load_mt5_candidate_time_shard(
                        source,
                        [700001, 700002],
                        datetime(2026, 7, 16),
                        datetime(2026, 7, 16, 12),
                    )
                self.assertEqual(rows, {})
                sql, params = cursor.execute.call_args.args
                self.assertIn("force index (INDEX_TIME)", sql)
                self.assertIn("force index (INDEX_POSITIONID)", sql)
                self.assertEqual(params, [
                    datetime(2026, 7, 16),
                    datetime(2026, 7, 16, 12),
                    700001,
                    700002,
                ])

    def test_mt5_time_shards_deduplicate_complete_deals_without_changing_order(self):
        source = {
            "kind": "mt5_deals",
            "name": "DBG GB MT5",
            "server": "DBG GB MT5",
            "schema": "mt5_export_new",
            "table": "mt5_deals",
        }
        first = {"Login": 700001, "Deal": 20, "PositionID": 2, "Time": "2026-07-16 10:00:00"}
        second = {"Login": 700001, "Deal": 10, "PositionID": 1, "Time": "2026-07-16 09:00:00"}
        captured = []

        def corrected(deals, *_args):
            captured.extend(deals)
            return [{"ticket": str(row["PositionID"])} for row in deals]

        with patch.object(
            runner,
            "_candidate_time_shards",
            return_value=[
                (datetime(2026, 7, 16), datetime(2026, 7, 16, 12)),
                (datetime(2026, 7, 16, 12), datetime(2026, 7, 17)),
            ],
        ), patch.object(
            runner,
            "_load_mt5_candidate_time_shard",
            side_effect=[{"700001": [first, second]}, {"700001": [first]}],
        ), patch.object(
            runner.mt5_runner,
            "corrected_mt5_positions",
            side_effect=corrected,
        ), patch.object(
            runner.app,
            "account_money_meta",
            return_value={"moneyScale": 1},
        ):
            rows = runner.load_mt5_candidate_rows(
                source,
                [{"login": "700001"}],
                datetime(2026, 7, 16),
                datetime(2026, 7, 17),
            )
        self.assertEqual([row["Deal"] for row in captured], [10, 20])
        self.assertEqual([row["ticket"] for row in rows["700001"]], ["1", "2"])

    def test_mt5_ambiguous_cross_shard_count_is_exactly_rechecked(self):
        started = datetime(2026, 7, 16, 0, 0, 0)
        filters = runner.CandidateFilters(
            require_period_profit=False,
            limit_orders=True,
            max_orders=100,
            require_max_lot=False,
            require_total_profit=False,
            limit_deposit=False,
            limit_active_ratio=False,
            exclude_handled=False,
        )
        source = {
            "kind": "mt5_deals",
            "name": "MT5",
            "platform": "MT5",
            "server": "MT5",
            "schema": "risk",
            "table": "mt5_deals",
        }
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"Login": 700001, "ClosedOrders": 90}]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor_context
        aggregate = [{
            "Login": 700001,
            "ClosedOrders": 120,
            "MaxShardClosedOrders": 60,
            "MaxLot": 0.1,
            "PeriodNetRaw": 4,
        }]
        profile = {700001: {"MoneyScale": 1, "Currency": "USD", "LifetimeDataAvailable": False}}
        with patch.object(runner, "_window_candidate_rows", return_value=aggregate), \
             patch.object(runner, "_load_candidate_profiles", return_value=profile), \
             patch.object(runner.app, "mysql_trade_connect", return_value=connection):
            result = runner.source_candidates(source, started, started + timedelta(days=3), filters)
        self.assertEqual(result[0]["closedOrders"], 90)

    def test_mt5_candidate_profiles_do_not_query_unindexed_daily_view(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{
                "Login": 700001,
                "Registration": datetime(2026, 1, 1),
                "Status": "",
                "AccountGroup": "Live\\USD",
                "Balance": 1083.72,
            }],
            [{"Login": 700001, "LedgerNetRaw": 18928.47, "DepositRaw": 50}],
        ]
        filters = runner.CandidateFilters(
            require_period_profit=False,
            limit_orders=False,
            require_max_lot=False,
            require_total_profit=True,
            limit_deposit=True,
            limit_active_ratio=False,
            exclude_handled=False,
        )
        profiles = runner._candidate_profiles(
            {"kind": "mt5_deals", "schema": "risk", "table": "mt5_deals", "name": "MT5"},
            cursor,
            [700001],
            filters,
            datetime(2026, 7, 16),
        )
        sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertNotIn("mt5_daily_view", sql)
        self.assertNotIn("count(distinct", sql.lower())
        self.assertIn("Action >= 2", sql)
        self.assertAlmostEqual(profiles[700001]["TotalNet"], -17844.75)
        self.assertEqual(profiles[700001]["DepositTotal"], 50)

    def test_mt4_candidate_profile_uses_balance_minus_ledger(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{
                "Login": 500001,
                "Registration": datetime(2026, 1, 1),
                "Status": "",
                "Currency": "USD",
                "AccountGroup": "real",
                "Balance": 500,
            }],
            [{"Login": 500001, "LedgerNetRaw": 300, "DepositRaw": 100}],
        ]
        filters = runner.CandidateFilters(
            require_period_profit=False,
            limit_orders=False,
            require_max_lot=False,
            require_total_profit=True,
            limit_deposit=True,
            limit_active_ratio=False,
            exclude_handled=False,
        )
        profiles = runner._candidate_profiles(
            {"kind": "mt4_trades", "schema": "risk", "table": "mt4_trades", "name": "MT4"},
            cursor,
            [500001],
            filters,
            datetime(2026, 7, 16),
        )
        self.assertEqual(profiles[500001]["TotalNet"], 200)
        self.assertEqual(profiles[500001]["DepositTotal"], 100)

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

    def test_lifetime_filters_can_be_deferred_until_after_structure_screen(self):
        filters = runner.CandidateFilters(
            require_total_profit=True,
            limit_deposit=True,
            limit_active_ratio=True,
            exclude_handled=False,
        )
        self.assertEqual(
            runner.candidate_filter_reasons({}, filters, include_lifetime=False),
            [],
        )
        self.assertEqual(len(runner.candidate_filter_reasons({}, filters)), 3)

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

    def test_push_economic_evidence_requires_positive_lifetime_and_meaningful_interval_return(self):
        candidate = {
            "lifetimeDataAvailable": True,
            "totalNet": 200,
            "depositTotal": 500,
        }
        interval = {"available": True, "netProfit": 50}

        exact_relative_boundary = runner.push_economic_evidence(candidate, interval)
        self.assertTrue(exact_relative_boundary["qualified"])
        self.assertEqual(exact_relative_boundary["intervalReturnPct"], 10)
        self.assertTrue(exact_relative_boundary["relativeQualified"])

        absolute_without_deposit = runner.push_economic_evidence(
            {**candidate, "depositTotal": 0},
            {"available": True, "netProfit": 100},
        )
        self.assertTrue(absolute_without_deposit["qualified"])
        self.assertTrue(absolute_without_deposit["absoluteQualified"])

        negative_lifetime = runner.push_economic_evidence(
            {**candidate, "totalNet": -1},
            {"available": True, "netProfit": 500},
        )
        self.assertFalse(negative_lifetime["qualified"])
        self.assertIn("全历史交易净收益不为正", negative_lifetime["reason"])

        negative_interval = runner.push_economic_evidence(
            candidate,
            {"available": True, "netProfit": -10},
        )
        self.assertFalse(negative_interval["qualified"])
        self.assertIn("没有形成正净收益", negative_interval["reason"])

        low_return = runner.push_economic_evidence(
            candidate,
            {"available": True, "netProfit": 49.99},
        )
        self.assertFalse(low_return["qualified"])
        self.assertIn("未达到", low_return["reason"])

    def test_lifetime_economic_prerequisite_is_independent_of_optional_candidate_filters(self):
        self.assertEqual(
            runner.push_lifetime_economic_reasons({"lifetimeDataAvailable": True, "totalNet": 0}),
            ["全历史交易净收益未形成正向经济结果"],
        )
        self.assertEqual(
            runner.push_lifetime_economic_reasons({"lifetimeDataAvailable": True, "totalNet": 0.01}),
            [],
        )


if __name__ == "__main__":
    unittest.main()
