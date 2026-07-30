from __future__ import annotations

from types import SimpleNamespace

from kdesk.infrastructure.position_risk import (
    LegacyPositionRiskRepository,
    _bounded_target_query,
    _distinct_target_windows,
    _mt5_open_matches_target,
    _mt5_target_predicate,
    _target_open_index,
)


def source(host: str, schema: str, table: str, kind: str, platform: str, server: str) -> dict:
    return {
        "host": host, "schema": schema, "table": table, "kind": kind,
        "platform": platform, "server": server, "name": server,
    }


def repository(sources: list[dict]) -> LegacyPositionRiskRepository:
    value = object.__new__(LegacyPositionRiskRepository)
    value.module = SimpleNamespace(MYSQL_SOURCES=sources)
    return value


def test_bounded_target_query_splits_saturated_batches_without_losing_rows() -> None:
    calls = []

    def fetch_batch(targets: list[dict]) -> list[dict]:
        calls.append([target["id"] for target in targets])
        if len(targets) > 1:
            return [{"saturated": index} for index in range(3)]
        return [{"id": targets[0]["id"]}]

    rows = _bounded_target_query(
        [{"id": value} for value in range(4)],
        fetch_batch,
        row_limit=3,
        saturated_message="single target saturated",
    )

    assert [row["id"] for row in rows] == [0, 1, 2, 3]
    assert calls[0] == [0, 1, 2, 3]
    assert [0] in calls and [3] in calls


def test_distinct_target_windows_remove_only_equivalent_source_queries() -> None:
    targets = [
        {"id": "first", "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:30:00"},
        {"id": "same", "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:30:00"},
        {"id": "other-close", "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:31:00"},
    ]

    assert [row["id"] for row in _distinct_target_windows(targets, require_close=False)] == ["first"]
    assert [row["id"] for row in _distinct_target_windows(targets, require_close=True)] == ["first", "other-close"]


def test_mt5_open_candidate_prefilter_preserves_shared_rules_and_opposite_lot_gate() -> None:
    targets = [{
        "symbol": "XAUUSD.a", "direction": "buy", "volume": 1,
        "openTime": "2026-07-20 22:00:00",
    }]
    index = _target_open_index(targets)
    matching_opposite = {
        "Symbol": "XAUUSD", "Action": 1, "Volume": 9000, "VolumeExt": 90_000_000,
        "Time": "2026-07-20 22:00:05",
    }
    small_opposite = {**matching_opposite, "VolumeExt": 70_000_000}
    same_direction = {**matching_opposite, "Action": 0, "VolumeExt": 10_000_000}
    wrong_symbol = {**matching_opposite, "Symbol": "EURUSD"}

    assert _mt5_open_matches_target(matching_opposite, index, opposite_only=True)
    assert not _mt5_open_matches_target(small_opposite, index, opposite_only=True)
    assert not _mt5_open_matches_target(same_direction, index, opposite_only=True)
    assert _mt5_open_matches_target(same_direction, index, opposite_only=False)
    assert not _mt5_open_matches_target(wrong_symbol, index, opposite_only=False)


def test_mt5_target_predicate_pushes_hedge_rules_into_bounded_time_query() -> None:
    target = {
        "symbol": "XAUUSD.a", "direction": "buy", "volume": 1,
        "openTime": "2026-07-20 22:00:00",
    }

    hedge_clause, hedge_parameters = _mt5_target_predicate(target, opposite_only=True)
    shared_clause, shared_parameters = _mt5_target_predicate(target, opposite_only=False)

    assert "Time >= %s" in hedge_clause
    assert "Symbol like %s" in hedge_clause
    assert "Action=%s" in hedge_clause
    assert "VolumeExt/100000000.0" in hedge_clause
    assert hedge_parameters[2:] == ("XAUUSD%", 1, 0.8, 1.25)
    assert "Action=%s" not in shared_clause
    assert shared_parameters[2:] == ("XAUUSD%",)


def test_peer_sources_deduplicate_shared_physical_databases() -> None:
    sources = [
        source("ac", "ac_gb_mt5", "mt5_deals", "mt5_deals", "MT5", "AC GB MT5"),
        source("ac", "ac_cn_mt5", "mt5_deals", "mt5_deals", "MT5", "AC CN MT5"),
        source("ac", "ac_cn_mt5_3", "mt5_deals", "mt5_deals", "MT5", "AC CN MT5 live3"),
        source("ac", "ac_mt4", "mt4_trades", "mt4_trades", "MT4", "AC CN MT4"),
        source("ac", "ac_mt4", "mt4_trades", "mt4_trades", "MT4", "AC GB MT4"),
        source("dbg", "dbg_mt5", "mt5_deals", "mt5_deals", "MT5", "DBG CN MT5"),
        source("dbg", "dbg_mt5", "mt5_deals", "mt5_deals", "MT5", "DBG GB MT5"),
        source("dbg", "crm_vn_mt5_live2", "mt5_deals", "mt5_deals", "MT5", "DBG MT5 Live2"),
        source("dbg", "dbg_mt4_1", "mt4_trades", "mt4_trades", "MT4", "DBG MT4 CN1"),
        source("dbg", "dbg_mt4_2", "mt4_trades", "mt4_trades", "MT4", "DBG MT4 CN2"),
        source("dbg", "dbg_mt4_3", "mt4_trades", "mt4_trades", "MT4", "DBG MT4 VN3"),
    ]

    units = repository(sources)._peer_source_units()

    assert len(units) == 9
    assert any(unit["key"][1] == "crm_vn_mt5_live2" for unit in units)
    shared_ac = next(unit for unit in units if unit["key"][1] == "ac_mt4")
    assert [item["server"] for item in shared_ac["sources"]] == ["AC CN MT4", "AC GB MT4"]


def test_peer_search_keeps_partial_coverage_and_exact_order_evidence() -> None:
    first = source("ac", "ac_mt5", "mt5_deals", "mt5_deals", "MT5", "AC GB MT5")
    failed = source("dbg", "dbg_mt4", "mt4_trades", "mt4_trades", "MT4", "DBG MT4 CN1")
    value = repository([first, failed])

    def load(unit: dict, _targets: list[dict]) -> list[dict]:
        if unit["representative"]["host"] == "dbg":
            raise RuntimeError("read-only source timeout")
        metadata = value._peer_source_metadata(unit)
        return [{
            **metadata, "account": "2001", "orderId": "peer-order", "positionId": "peer-position",
            "dealId": "peer-deal", "symbol": "XAUUSD", "direction": "sell", "volume": 1,
            "openTime": "2026-07-20 22:00:04", "closeTime": "2026-07-20 22:30:05", "fullyClosed": True,
        }]

    value._load_peer_orders_from_source = load
    event = {
        "start": "2026-07-20 22:00:00", "end": "2026-07-20 22:30:00",
        "heavyOrders": [{
            "orderId": "target-order", "positionId": "target-position", "symbol": "XAUUSD", "direction": "sell",
            "volume": 2, "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:30:00",
        }],
    }

    result = value.load_peer_accounts("1001", {"source": first}, event)

    assert result["sameDirectionAccounts"] == ["2001"]
    assert result["sameDirectionMatches"][0]["orderId"] == "peer-order"
    assert result["sameDirectionMatches"][0]["targetOrderId"] == "target-order"
    assert result["peerSearchCoverage"]["status"] == "部分失败"
    assert result["peerSearchCoverage"]["scannedSourceCount"] == 1
    assert result["peerSearchCoverage"]["failedSourceCount"] == 1


def test_peer_search_reports_unclosed_target_as_data_insufficient() -> None:
    first = source("ac", "ac_mt5", "mt5_deals", "mt5_deals", "MT5", "AC GB MT5")
    value = repository([first])
    event = {
        "start": "2026-07-20 22:00:00", "end": "2026-07-20 22:30:00",
        "heavyOrders": [{
            "orderId": "open-target", "symbol": "XAUUSD", "direction": "sell", "volume": 2,
            "openTime": "2026-07-20 22:00:00", "closeTime": "",
        }],
    }

    result = value.load_peer_accounts("1001", {"source": first}, event)

    assert result["peerSearchCoverage"]["status"] == "数据不足"
    assert result["peerSearchCoverage"]["scannedSourceCount"] == 0
    assert result["peerSearchCoverage"]["skippedTargetOrders"][0]["orderId"] == "open-target"


def test_shared_physical_source_resolves_each_peer_logical_server() -> None:
    cn = source("ac", "ac_mt4", "mt4_trades", "mt4_trades", "MT4", "AC CN MT4")
    cn["account_route"] = {"schema": "crm_cn", "mt_server_code": "2"}
    gb = source("ac", "ac_mt4", "mt4_trades", "mt4_trades", "MT4", "AC GB MT4")
    gb["account_route"] = {"schema": "crm_gb", "mt_server_code": "2"}

    class Cursor:
        parameters = ()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, parameters):
            self.query = query
            self.parameters = parameters

        def fetchall(self):
            return [{"mt_login": 2001}] if "`crm_gb`" in self.query else []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    value = repository([cn, gb])
    value.module.mysql_trade_connect = lambda _source: Connection()
    unit = value._peer_source_units()[0]
    rows = [{"account": "2001", "server": "AC CN MT4 / AC GB MT4"}]

    resolved = value._resolve_peer_servers(unit, rows)

    assert resolved[0]["server"] == "AC GB MT4"
