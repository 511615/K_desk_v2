from __future__ import annotations

import importlib.util
from pathlib import Path


def load_rebate_module():
    path = Path(__file__).resolve().parents[1] / "legacy" / "apps" / "problem_account_registry" / "rebate_churning.py"
    spec = importlib.util.spec_from_file_location("kdesk_test_rebate_churning", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_route_code_accepts_v2_route_lists() -> None:
    module = load_rebate_module()
    source = {
        "crm_routes": [
            {"schema": "crm_cn", "mt_server_code": "10"},
            {"schema": "crm_vn", "mt_server_code": "11"},
        ]
    }

    assert module._source_route_code(source, "crm_cn") == "10"
    assert module._source_route_code(source, "crm_vn") == "11"
    assert module._source_route_code(source, "missing") == ""


def test_source_route_code_keeps_legacy_route_dict_support() -> None:
    module = load_rebate_module()
    source = {"crm_routes": {"crm_cn": "10"}}

    assert module._source_route_code(source, "crm_cn") == "10"


def test_cent_trade_volume_is_scaled_to_standard_lot_equivalent() -> None:
    module = load_rebate_module()
    source = {"server": "AC CN MT4"}
    rows = [{
        "TICKET": 1, "LOGIN": 5006788, "CMD": 0, "SYMBOL": "XAUUSD", "VOLUME": 10000,
        "OPEN_TIME": "2026-07-01 10:00:00", "CLOSE_TIME": "2026-07-01 10:00:01",
        "PROFIT": -100, "COMMISSION": 0, "SWAPS": 0, "TAXES": 0, "REASON": 0, "MAGIC": 0,
        "COMMENT": "",
    }]

    trades = module._mt4_rows_to_trades(rows, {5006788: 0.01}, source)

    assert trades[5006788][0]["volume"] == 1.0
    assert trades[5006788][0]["profit"] == -1.0


def test_usc_rebate_amount_is_not_currency_scaled() -> None:
    module = load_rebate_module()

    assert module._rebate_amount({"rebate_amount": 1209.2431, "usd_or_usc": "USC"}) == 1209.2431


def test_dbg_mt5_queries_do_not_force_an_ac_only_index() -> None:
    module = load_rebate_module()
    executed = []

    class RecordingCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            executed.append((sql, params))

        def fetchall(self):
            return []

    class RecordingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def cursor():
            return RecordingCursor()

    source = {
        "name": "DBG GB MT5",
        "schema": "mt5_export_new",
        "table": "mt5_deals",
        "kind": "mt5_deals",
        "server": "DBG GB MT5",
        "crm_routes": [{"schema": "crm_vn", "mt_server_code": "2"}],
    }
    service = module.RebateChurningService([source], lambda _source: RecordingConnection())
    accounts = {("2", 3066186): {"mt_type_name": "GLOBAL-STDN20"}}
    period = {"startText": "2021-11-19 00:00:00", "endText": "2026-07-21 00:00:00"}

    trades = service._detailed_trades("dbg_vn", accounts, {}, period)
    service._cashflow_metrics("dbg_vn", accounts, {}, trades, period)

    sql = "\n".join(statement for statement, _params in executed)
    assert len(executed) == 2
    assert "idx_mt5_deals_Login_Time_Comment" not in sql
    assert "force index" not in sql.lower()
    assert "`mt5_export_new`.`mt5_deals`" in sql


def test_mt5_rebate_trades_are_reconstructed_by_exact_deal_and_position() -> None:
    module = load_rebate_module()
    executed = []

    open_row = {
        "Deal": 8, "Login": 3066186, "Order": 10, "PositionID": 12,
        "Action": 0, "Entry": 0, "Time": "2026-07-20 00:00:00",
        "TimeMsc": "2026-07-20 00:00:00", "Symbol": "XAUUSD", "Volume": 10000,
        "VolumeClosed": 0, "Profit": 0, "Commission": 0, "Storage": 0, "Fee": 0,
        "Reason": 0, "Comment": "", "ExpertID": 0,
    }
    close_row = {
        **open_row,
        "Deal": 9,
        "Entry": 1,
        "Time": "2026-07-20 00:00:01",
        "TimeMsc": "2026-07-20 00:00:01",
        "Profit": -2,
    }

    class RecordingCursor:
        sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            self.sql = sql
            executed.append((sql, params))

        def fetchall(self):
            if "where Deal in" in self.sql:
                return [close_row]
            if "where PositionID in" in self.sql:
                return [open_row, close_row]
            return []

    class RecordingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def cursor():
            return RecordingCursor()

    source = {
        "name": "DBG GB MT5",
        "schema": "mt5_export_new",
        "table": "mt5_deals",
        "kind": "mt5_deals",
        "server": "DBG GB MT5",
        "crm_routes": [{"schema": "crm_vn", "mt_server_code": "2"}],
    }
    service = module.RebateChurningService([source], lambda _source: RecordingConnection())
    key = ("2", 3066186)

    trades = service._exact_rebate_trades(
        "dbg_vn",
        {key: {"mt_type_name": "GLOBAL-STDN20"}},
        {key: [{"trade_mt_deal": 9, "trade_mt_ticket": 0}]},
    )

    assert len(trades[key]) == 1
    assert trades[key][0]["id"] == "9"
    assert trades[key][0]["open_time"] == "2026-07-20 00:00:00"
    assert trades[key][0]["close_time"] == "2026-07-20 00:00:01"
    assert module.account_features(trades[key])["short10Coverage"] == 1
    assert any("where Deal in" in sql for sql, _params in executed)
    assert any("where PositionID in" in sql for sql, _params in executed)
    assert all("where `Order` in" not in sql for sql, _params in executed)
    assert all("Time >=" not in sql for sql, _params in executed)


def test_tree_can_show_upstream_relation_and_account_owned_by_ib() -> None:
    module = load_rebate_module()
    users = {
        7257: {"id": 7257, "supper_id": None, "user_type": 0, "full_name": "Ken"},
        121983: {"id": 121983, "supper_id": 7257, "user_type": 1, "full_name": "张川", "ib_level": 1},
    }
    account = {"account": 5006788, "userId": 121983, "serverCode": "2"}

    tree = module.RebateChurningService._account_audit_tree(
        users, [account], {}, {}, 7257, 121983, {121983}, {7257, 121983}, 5006788,
    )

    assert tree["type"] == "ib"
    assert tree["name"] == "Ken"
    assert tree["relationship"] == "上级IB"
    assert tree["children"][0]["relationship"] == "直属IB"
    assert tree["children"][0]["accounts"][0]["account"] == 5006788
    assert tree["children"][0]["accounts"][0]["isTarget"] is True


def test_detail_batches_use_one_hundred_accounts() -> None:
    module = load_rebate_module()

    assert [len(batch) for batch in module._batches(range(201))] == [100, 100, 1]
    assert [len(batch) for batch in module._batches(range(2001), module.EXACT_ID_BATCH_SIZE)] == [1000, 1000, 1]


def test_rebate_details_use_time_capable_optimizer_index_and_preserve_raw_counts() -> None:
    module = load_rebate_module()
    executed = []

    class RecordingCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            executed.append((sql, params))

        @staticmethod
        def fetchall():
            return [{
                "rebate_ib_id": 7,
                "trade_user_id": 8,
                "trade_mt_login": 3066186,
                "mt_server_code": "2",
                "trade_mt_ticket": 0,
                "trade_mt_deal": 9,
                "rebate_amount": 12.5,
                "rebate_row_count": 4,
            }]

    class RecordingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def cursor():
            return RecordingCursor()

    source = {
        "name": "DBG GB MT5",
        "crm_routes": [{"schema": "crm_vn", "mt_server_code": "2"}],
    }
    service = module.RebateChurningService([source], lambda _source: RecordingConnection())
    period = {"startText": "2026-07-20 00:00:00", "endText": "2026-07-20 01:00:00"}

    grouped = service._rebate_details("dbg_vn", {("2", 3066186)}, period)

    sql, params = executed[0]
    assert "force index (idx_mtLogin)" not in sql
    assert "group by" not in sql.lower()
    assert "mt_symbol, mt_volume" in sql
    assert "mt_open_time, mt_close_time" in sql
    assert "rebate_amount, usd_or_usc" in sql
    assert params[-2:] == [period["startText"], period["endText"]]
    assert grouped[("2", 3066186)][0]["rebate_row_count"] == 4


def test_rebate_candidate_screen_is_high_recall_and_always_keeps_target() -> None:
    module = load_rebate_module()
    target = ("2", 5000)
    short = ("2", 5001)
    fixed = ("2", 5002)
    shared_a = ("2", 5003)
    shared_b = ("2", 5004)
    ordinary = ("2", 5005)

    def row(deal, *, opened, closed, volume, symbol="XAUUSD", rebate=1):
        return {
            "trade_mt_deal": deal,
            "mt_symbol": symbol,
            "mt_volume": volume,
            "mt_open_time": opened,
            "mt_close_time": closed,
            "rebate_amount": rebate,
        }

    shared_signature = {
        "opened": "2026-07-20 09:00:00",
        "closed": "2026-07-20 09:01:00",
        "volume": 2,
    }
    rebates = {
        short: [row(1, opened="2026-07-20 10:00:00", closed="2026-07-20 10:00:05", volume=1)],
        fixed: [
            row(10 + index, opened=f"2026-07-20 11:0{index}:00", closed=f"2026-07-20 11:0{index}:30", volume=3)
            for index in range(3)
        ],
        shared_a: [row(20, **shared_signature)],
        shared_b: [row(21, **shared_signature)],
        ordinary: [row(30, opened="2026-07-20 12:00:00", closed="2026-07-20 13:00:00", volume=1)],
    }

    candidates = module._rebate_candidate_keys(rebates, target)

    assert {target, short, fixed, shared_a, shared_b} <= candidates
    assert ordinary not in candidates


def test_high_volume_rebate_metadata_features_deduplicate_ib_rows() -> None:
    module = load_rebate_module()
    rows = [
        {
            "rebate_ib_id": ib_id,
            "trade_mt_deal": 9,
            "mt_symbol": "XAUUSD",
            "mt_volume": 2,
            "mt_open_time": "2026-07-20 10:00:00",
            "mt_close_time": "2026-07-20 10:00:05",
            "rebate_amount": 1,
        }
        for ib_id in (7, 8)
    ]

    feature = module._rebate_metadata_features(rows, 0.01)

    assert feature["orders"] == 1
    assert feature["lots"] == 0.02
    assert feature["short10Coverage"] == 1
    assert feature["tradeKeys"] == []
    assert feature["tradeProfitIncomplete"] is True
    assert module._rebate_exact_id_count(rows, "mt5_deals") == 1

    feature["_rebateRows"] = rows
    attached = module.RebateChurningService([], lambda _source: None)._attach_ib_rebate(feature, 7)
    assert attached["matchedRebateOrders"] == 1

    feature.pop("_rebateRows")
    feature["_rebateByIb"] = module._rebate_summaries_by_ib(feature, rows)
    attached = module.RebateChurningService([], lambda _source: None)._attach_ib_rebate(feature, 8)
    assert attached["currentIbRebate"] == 1
    assert attached["currentIbRebateRows"] == 1
    assert attached["matchedRebateOrders"] == 1


def test_incomplete_profit_metadata_does_not_confirm_economic_turnover() -> None:
    module = load_rebate_module()
    account = {
        "account": 1,
        "userId": 10,
        "orders": 2000,
        "lots": 2000,
        "activeDays": 1,
        "ordersPerActiveDay": 2000,
        "short10Coverage": 1,
        "fixedLotCoverage": 1,
        "repeatCoverage": 1,
        "tradeProfit": 0,
        "tradeProfitIncomplete": True,
        "currentIbRebate": 1000,
        "currentIbRebateRows": 2000,
        "matchedRebateOrders": 2000,
        "externalNetDeposit": 0,
    }

    risk = module.score_ib(
        [account],
        ib_id=7,
        thresholds={
            "ordersPerDayP95": 100,
            "ordersPerDayP99": 500,
            "ordersP95": 1000,
            "ordersP99": 1500,
            "lotsDepositP95": 100,
            "lotsDepositP99": 1000,
        },
    )

    assert risk["score"] < 75
    assert "高周转且返佣经济贡献超过交易盈亏一半" not in risk["evidenceTags"]
    assert any("未回查完整盈亏" in tag for tag in risk["evidenceTags"])


def test_aggregated_rebate_rows_keep_amount_and_original_detail_count() -> None:
    module = load_rebate_module()
    service = module.RebateChurningService([], lambda _source: None)
    aggregated = module._aggregate_rebate_rows([
        {
            "rebate_ib_id": 7, "trade_user_id": 8, "trade_mt_login": 3066186,
            "mt_server_code": "2", "trade_mt_ticket": 0, "trade_mt_deal": 9,
            "rebate_amount": 10, "usd_or_usc": "USD",
        },
        {
            "rebate_ib_id": 7, "trade_user_id": 8, "trade_mt_login": 3066186,
            "mt_server_code": "2", "trade_mt_ticket": 0, "trade_mt_deal": 9,
            "rebate_amount": 2.5, "usd_or_usc": "USC",
        },
    ])
    assert len(aggregated) == 1
    assert aggregated[0]["rebate_amount"] == 12.5
    assert aggregated[0]["rebate_row_count"] == 2
    assert aggregated[0]["usd_or_usc"] == "USC"

    account = {
        "_rebateRows": [
            {"rebate_ib_id": 7, "rebate_amount": 10, "rebate_row_count": 3},
            {"rebate_ib_id": 7, "rebate_amount": 2.5, "rebate_row_count": 2},
            {"rebate_ib_id": 8, "rebate_amount": 99, "rebate_row_count": 1},
        ],
    }

    attached = service._attach_ib_rebate(account, 7)

    assert attached["currentIbRebate"] == 12.5
    assert attached["currentIbRebateRows"] == 5


def test_account_audit_separates_recipient_evidence_from_hierarchy_totals() -> None:
    module = load_rebate_module()
    executed = []

    class RecordingCursor:
        sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            self.sql = sql
            executed.append((sql, params))

        def fetchall(self):
            if "force index (idx_covering)" in self.sql:
                return [{
                    "rebate_ib_id": 7,
                    "trade_user_id": 8,
                    "trade_mt_login": 3066186,
                    "mt_server_code": "2",
                    "trade_mt_ticket": 0,
                    "trade_mt_deal": 9,
                    "rebate_amount": 12.5,
                    "usd_or_usc": "USD",
                }]
            return [{
                "trade_mt_login": 3066186,
                "mt_server_code": "2",
                "rebate_amount": 30.0,
                "rebate_row_count": 6,
            }]

    class RecordingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def cursor():
            return RecordingCursor()

    source = {
        "name": "DBG GB MT5",
        "crm_routes": [{"schema": "crm_vn", "mt_server_code": "2"}],
    }
    service = module.RebateChurningService([source], lambda _source: RecordingConnection())
    account_keys = {("2", 3066186)}
    period = {"startText": "2026-07-20 00:00:00", "endText": "2026-07-20 01:00:00"}

    details = service._rebate_details_for_ibs("dbg_vn", {7}, account_keys, period)
    totals = service._rebate_totals_for_accounts("dbg_vn", account_keys, period)

    assert details[("2", 3066186)][0]["rebate_amount"] == 12.5
    assert totals[("2", 3066186)] == {"amount": 30.0, "rows": 6}
    assert "rebate_ib_id in" in executed[0][0]
    assert "mt_symbol, mt_volume" in executed[0][0]
    assert "mt_open_time, mt_close_time" in executed[0][0]
    assert "group by trade_mt_login, mt_server_code" in executed[1][0]


def test_historical_accounts_use_selected_period_instead_of_fixed_five_year_scan() -> None:
    module = load_rebate_module()
    executed = []

    class RecordingCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            executed.append((sql, params))

        @staticmethod
        def fetchall():
            return []

    class RecordingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def cursor():
            return RecordingCursor()

    source = {
        "name": "DBG GB MT5",
        "crm_routes": [{"schema": "crm_vn", "mt_server_code": "2"}],
    }
    service = module.RebateChurningService([source], lambda _source: RecordingConnection())

    service._historical_ib_accounts(
        "dbg_vn", {7}, "2026-07-20 00:00:00", "2026-07-20 01:00:00",
    )

    assert executed[0][1][-2:] == ["2026-07-20 00:00:00", "2026-07-20 01:00:00"]


def test_cashflow_reads_only_accounts_with_trades_or_rebates() -> None:
    module = load_rebate_module()

    keys = module._cashflow_account_keys(
        {("2", 1001): [{}]},
        {
            ("2", 1001): [],
            ("2", 1002): [{"id": 1}],
            ("2", 1003): [],
        },
    )

    assert keys == {("2", 1001), ("2", 1002)}


def test_batched_trade_reads_reuse_one_connection_per_stage() -> None:
    module = load_rebate_module()
    connection_count = 0
    executed = []

    class RecordingCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            executed.append((sql, params))

        @staticmethod
        def fetchall():
            return []

    class RecordingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def cursor():
            return RecordingCursor()

    def connect(_source):
        nonlocal connection_count
        connection_count += 1
        return RecordingConnection()

    source = {
        "name": "DBG GB MT5",
        "schema": "mt5_export_new",
        "table": "mt5_deals",
        "kind": "mt5_deals",
        "server": "DBG GB MT5",
        "crm_routes": [{"schema": "crm_vn", "mt_server_code": "2"}],
    }
    service = module.RebateChurningService([source], connect)
    mappings = {
        ("2", login): {"mt_login": login, "mt_server_code": "2", "mt_type_name": "GLOBAL-STDN20"}
        for login in range(1000, 1201)
    }
    raw_accounts = list(mappings.values())
    period = {"startText": "2026-07-20 00:00:00", "endText": "2026-07-20 01:00:00"}

    trades = service._detailed_trades("dbg_vn", mappings, {}, period)
    service._cashflow_metrics("dbg_vn", mappings, {}, trades, period)
    service._trade_aggregates_for_accounts("dbg_vn", raw_accounts, period)

    assert connection_count == 3
    assert len(executed) == 27


def test_complete_trade_aggregate_replaces_non_candidate_display_totals() -> None:
    module = load_rebate_module()
    shallow_feature = module.account_features([])

    merged = module._merge_complete_trade_aggregate(shallow_feature, {
        "orders": 161,
        "lots": 18.44,
        "tradeProfit": 512.25,
        "activeDays": 21,
    })

    assert merged["orders"] == 161
    assert merged["lots"] == 18.44
    assert merged["tradeProfit"] == 512.25
    assert merged["activeDays"] == 21
    assert merged["ordersPerActiveDay"] == 7.67
    assert merged["tradeStatisticsComplete"] is True
    assert merged["tradeProfitIncomplete"] is False


def test_complete_trade_aggregate_keeps_candidate_structure_evidence() -> None:
    module = load_rebate_module()
    candidate_feature = {
        **module.account_features([{
            "id": 1,
            "symbol": "XAUUSD",
            "type": "buy",
            "volume": 1,
            "open_time": "2026-07-20 10:00:00",
            "close_time": "2026-07-20 10:00:05",
            "profit": -1,
        }]),
        "tradeProfitIncomplete": True,
    }

    merged = module._merge_complete_trade_aggregate(candidate_feature, {
        "orders": 10,
        "lots": 4,
        "tradeProfit": 25,
        "activeDays": 2,
    })

    assert merged["orders"] == 10
    assert merged["tradeProfit"] == 25
    assert merged["short10Coverage"] == 1
    assert merged["tradeKeys"] == ["1"]
    assert merged["tradeProfitIncomplete"] is False


def test_full_history_audit_uses_complete_totals_for_non_candidate_tree_account() -> None:
    module = load_rebate_module()
    source = {
        "name": "DBG CN MT5",
        "schema": "mt5_export_new",
        "table": "mt5_deals",
        "kind": "mt5_deals",
        "platform": "MT5",
        "server": "DBG CN MT5",
        "crm_routes": [{"schema": "crm_cn", "mt_server_code": "4"}],
    }
    service = module.RebateChurningService([source], lambda _source: None)
    subject = {
        "environment": "dbg_cn",
        "environmentLabel": "DBG CN",
        "crmSchema": "crm_cn",
        "source": source,
        "account": 2000001,
        "serverCode": "4",
        "platform": "MT5",
        "server": "DBG CN MT5",
        "typeName": "STDN20",
        "userId": 10,
        "ownerName": "目标客户",
    }
    users = {
        7: {"id": 7, "supper_id": None, "user_type": 1, "full_name": "上级IB", "ib_level": 1},
        10: {"id": 10, "supper_id": 7, "user_type": 0, "full_name": "目标客户"},
        11: {"id": 11, "supper_id": 7, "user_type": 0, "full_name": "普通客户"},
    }
    raw_accounts = [
        {"user_id": 10, "mt_login": 2000001, "mt_server_code": "4", "mt_type_name": "STDN20"},
        {"user_id": 11, "mt_login": 2013813, "mt_server_code": "4", "mt_type_name": "STDN20"},
    ]
    mappings = {
        ("4", row["mt_login"]): {**row, **users[row["user_id"]]}
        for row in raw_accounts
    }
    service.resolve_account = lambda *_args, **_kwargs: subject
    service._ancestor_chain = lambda _subject: [users[7], users[10]]
    service._fetch_tree = lambda _environment, _ib_id: (users.copy(), raw_accounts.copy())
    service._rebate_details_for_ibs = lambda *_args, **_kwargs: {}
    service._account_mappings = lambda _environment, _keys: mappings
    service._candidate_account_evidence = lambda *_args, **_kwargs: ({}, {}, set())
    service._account_audit_complete_statistics = lambda *_args, **_kwargs: ({}, [
        {"serverCode": "4", "login": 2013813, "orders": 161, "lots": 18.44, "tradeProfit": 512.25, "activeDays": 21},
    ])

    result = service.target_account_audit(2000001)

    ordinary_customer = next(node for node in result["tree"]["children"] if node["userId"] == 11)
    ordinary_account = ordinary_customer["accounts"][0]
    assert result["query"]["fullHistory"] is True
    assert ordinary_account["orders"] == 161
    assert ordinary_account["lots"] == 18.44
    assert ordinary_account["tradeProfit"] == 512.25
    assert ordinary_account["tradeStatisticsComplete"] is True


def test_account_audit_cache_is_bounded_and_returns_copies() -> None:
    module = load_rebate_module()
    service = module.RebateChurningService([], lambda _source: None)
    key = ("dbg_vn", "2", 3066186, "2026-07-20 00:00:00", "latest")
    payload = {"ok": True, "tree": {"accounts": [3066186]}}

    service._cache_account_audit(key, payload)
    first = service._cached_account_audit(key)
    assert first == payload
    first["tree"]["accounts"].append(1)

    assert service._cached_account_audit(key) == payload
