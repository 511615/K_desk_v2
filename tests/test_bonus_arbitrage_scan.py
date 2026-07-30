from __future__ import annotations

from datetime import datetime
from threading import Lock
from time import sleep

import pytest

from kdesk.application.bonus_arbitrage_scan import (
    BonusArbitrageScanService,
    normalize_bonus_scan_options,
)
from kdesk.infrastructure.bonus_arbitrage_scan import (
    LegacyBonusArbitrageScanRepository,
    _candidate_deposit_amount,
)


def test_bonus_scan_options_default_to_all_environments_and_validate_limits() -> None:
    options = normalize_bonus_scan_options({}, now=datetime(2026, 7, 20, 12, 0, 0))
    assert options == {
        "start": "2026-06-20 12:00:00",
        "end": "2026-07-20 12:00:00",
        "environments": ["ac_gb", "ac_cn", "dbg_cn", "dbg_vn"],
        "deepLimit": 100,
        "minGrant": 0.0,
        "excludeHandled": True,
    }
    with pytest.raises(ValueError, match="180天"):
        normalize_bonus_scan_options({"start": "2025-01-01", "end": "2026-07-20"})
    with pytest.raises(ValueError, match="1到300"):
        normalize_bonus_scan_options({"deepLimit": 301})


def test_bonus_scan_units_include_independent_dbg_live2_source() -> None:
    sources = [
        {
            "host": "dbg", "schema": "mt5_export_new", "table": "mt5_deals",
            "kind": "mt5_deals", "server": "DBG CN MT5",
            "account_route": {"schema": "crm_cn", "mt_server_code": "4"},
        },
        {
            "host": "dbg", "schema": "mt5_export_new", "table": "mt5_deals",
            "kind": "mt5_deals", "server": "DBG GB MT5",
            "account_route": {"schema": "crm_vn", "mt_server_code": "2"},
        },
        {
            "host": "dbg", "schema": "crm_vn_mt5_live2", "table": "mt5_deals",
            "kind": "mt5_deals", "server": "DBG MT5 Live2",
            "account_route": {"schema": "crm_vn", "mt_server_code": "5"},
        },
    ]
    repository = object.__new__(LegacyBonusArbitrageScanRepository)
    repository.module = type("Runtime", (), {"MYSQL_SOURCES": sources})()

    units = repository.scan_units(["dbg_cn", "dbg_vn"])

    assert {unit["schema"] for unit in units} == {"mt5_export_new", "crm_vn_mt5_live2"}
    live2_unit = next(unit for unit in units if unit["schema"] == "crm_vn_mt5_live2")
    assert live2_unit["label"] == "DBG MT5 Live2"


class FakeBonusScanRepository:
    def scan_units(self, environments):
        assert environments == ["ac_gb"]
        return [{"id": "gb-mt5", "label": "AC GB MT5"}]

    def discover_candidates(self, unit_id, start, end):
        assert unit_id == "gb-mt5"
        return [
            {
                "account": "621928", "source": "AC GB MT5", "platform": "MT5",
                "server": "AC GB MT5", "environment": "ac_gb", "crmSchema": "int_sass_crm_ac",
                "serverCode": "1", "databaseStatus": "", "currency": "USD",
                "grantCount": 1, "explicitGrantCount": 1, "grantAmount": 500,
                "latestGrant": "2026-07-01 08:00:01",
            },
            {
                "account": "900001", "source": "AC GB MT5", "platform": "MT5",
                "server": "AC GB MT5", "environment": "ac_gb", "crmSchema": "int_sass_crm_ac",
                "serverCode": "1", "databaseStatus": "", "currency": "USD",
                "grantCount": 1, "explicitGrantCount": 1, "grantAmount": 800,
                "latestGrant": "2026-07-01 08:00:01",
            },
        ]

    def load_account_context(self, login, filters):
        assert login == "621928"
        assert filters["server"] == "AC GB MT5"
        return {
            "profile": {"account": login, "platform": "MT5", "server": "AC GB MT5", "currency": "USD", "moneyScale": 1, "leverage": 100},
            "events": [
                {"id": "d1", "time": "2026-07-01 08:00:00", "kind": "deposit", "amount": 500},
                {"id": "c1", "time": "2026-07-01 08:00:01", "kind": "bonus_grant", "amount": 500},
                {"id": "w1", "time": "2026-07-01 12:00:00", "kind": "withdrawal", "amount": -1125},
                {"id": "c2", "time": "2026-07-01 12:00:01", "kind": "bonus_remove", "amount": -500},
            ],
            "trades": [{
                "id": "p1", "symbol": "XAUUSD", "direction": "buy", "volume": 0.1,
                "openTime": "2026-07-01 09:00:00", "closeTime": "2026-07-01 11:00:00",
                "openPrice": 2000, "contractSize": 100, "netProfit": 625,
            }],
            "peers": [],
        }


def test_platform_scan_excludes_handled_accounts_and_returns_cycle_evidence() -> None:
    progress = []
    result = BonusArbitrageScanService(FakeBonusScanRepository()).run(
        {
            "start": "2026-07-01 00:00:00", "end": "2026-07-02 00:00:00",
            "environments": ["ac_gb"], "deepLimit": 10, "excludeHandled": True,
        },
        progress=lambda percent, message: progress.append((percent, message)),
        cancelled=lambda: False,
        handled_logins={"900001"},
    )

    assert result["summary"]["candidateAccounts"] == 2
    assert result["summary"]["excludedHandled"] == 1
    assert result["summary"]["analyzedAccounts"] == 1
    assert result["results"][0]["account"] == "621928"
    assert result["results"][0]["score"] == 90
    assert result["results"][0]["bestCycle"]["extractionMatch"] == 1
    assert result["results"][0]["bestCycle"]["earlyPeakOrderCount"] == 1
    assert result["results"][0]["bestCycle"]["earlyPeakOrders"][0]["tradeId"] == "p1"
    assert result["results"][0]["bestCycle"]["minimumMarginLevel"] == 500
    assert result["results"][0]["bestCycle"]["minimumConcurrentLots"] == 0.1
    assert result["results"][0]["bestCycle"]["minimumMarginOrders"][0]["tradeId"] == "p1"
    assert progress[-1] == (99, "正在整理赠金套利风险榜与失败明细")


class MarginRankBonusScanRepository(FakeBonusScanRepository):
    def enrich_ranking_metrics(self, candidates):
        metrics = {
            "621928": {"currentMargin": 200, "depositTotal": 1000, "marginToDeposit": 0.2},
            "900001": {"currentMargin": 600, "depositTotal": 1000, "marginToDeposit": 0.6},
        }
        return {
            "candidates": [{**candidate, **metrics[candidate["account"]]} for candidate in candidates],
            "failures": [],
        }

    def load_account_context(self, login, filters):
        return {
            "profile": {"account": login, "platform": "MT5", "server": filters["server"], "currency": "USD"},
            "events": [], "trades": [], "peers": [],
        }


def test_platform_scan_ranks_deep_queue_by_margin_to_deposit_ratio() -> None:
    result = BonusArbitrageScanService(MarginRankBonusScanRepository()).run(
        {
            "start": "2026-07-01 00:00:00", "end": "2026-07-02 00:00:00",
            "environments": ["ac_gb"], "deepLimit": 1, "excludeHandled": False,
        },
        progress=lambda *_args: None,
        cancelled=lambda: False,
    )

    assert result["summary"]["deepAccounts"] == 1
    assert result["allResults"][0]["account"] == "900001"
    assert result["allResults"][0]["currentMargin"] == 600
    assert result["allResults"][0]["depositTotal"] == 1000
    assert result["allResults"][0]["marginToDeposit"] == 0.6


class FailedMarginRankBonusScanRepository(MarginRankBonusScanRepository):
    def enrich_ranking_metrics(self, candidates):
        raise RuntimeError("margin query timeout")


def test_platform_scan_falls_back_to_grant_ranking_when_margin_query_fails() -> None:
    result = BonusArbitrageScanService(FailedMarginRankBonusScanRepository()).run(
        {
            "start": "2026-07-01 00:00:00", "end": "2026-07-02 00:00:00",
            "environments": ["ac_gb"], "deepLimit": 1, "excludeHandled": False,
        },
        progress=lambda *_args: None,
        cancelled=lambda: False,
    )

    assert result["allResults"][0]["account"] == "900001"
    assert result["failures"][0]["stage"] == "candidate_rank"
    assert result["failures"][0]["fallback"] == "赠金证据排序"


def test_candidate_deposit_amount_excludes_reversals_and_keeps_platform_fees() -> None:
    assert _candidate_deposit_amount(
        {"Comment": "CRM-DP-1", "Profit": 1000, "Commission": -5, "Storage": 0, "Fee": -1},
        mt5=True,
    ) == 994
    assert _candidate_deposit_amount({"Comment": "DEP-RS-1", "Profit": 1000}, mt5=False) == 0
    assert _candidate_deposit_amount({"Comment": "WDR-1", "Profit": 1000}, mt5=False) == 0


class FailingBonusScanRepository(FakeBonusScanRepository):
    def discover_candidates(self, unit_id, start, end):
        raise RuntimeError("query timeout")


def test_platform_scan_keeps_partial_candidate_failures() -> None:
    result = BonusArbitrageScanService(FailingBonusScanRepository()).run(
        {
            "start": "2026-07-01 00:00:00", "end": "2026-07-02 00:00:00",
            "environments": ["ac_gb"],
        },
        progress=lambda *_args: None,
        cancelled=lambda: False,
    )

    assert result["partialFailure"] is True
    assert result["failureTotal"] == 4
    assert result["summary"]["candidateAccounts"] == 0


class BatchedRouteBonusScanRepository(FakeBonusScanRepository):
    def __init__(self) -> None:
        self.route_calls = 0
        self.route_row_counts = []

    def discover_candidates(self, unit_id, start, end):
        return [{
            "Login": 621928,
            "GrantCount": 1,
            "ExplicitGrantCount": 1,
            "GrantAmount": 250,
            "LatestGrant": start,
        }]

    def route_candidates(self, unit_id, rows):
        self.route_calls += 1
        self.route_row_counts.append(len(rows))
        return [{
            "account": "621928", "source": "AC GB MT5", "platform": "MT5",
            "server": "AC GB MT5", "environment": "ac_gb", "crmSchema": "int_sass_crm_ac",
            "serverCode": "1", "databaseStatus": "", "currency": "USD",
            "grantCount": sum(row["GrantCount"] for row in rows),
            "explicitGrantCount": sum(row["ExplicitGrantCount"] for row in rows),
            "grantAmount": sum(row["GrantAmount"] for row in rows),
            "latestGrant": "2026-07-02 08:00:01",
        }]


def test_platform_scan_batches_route_validation_after_all_daily_shards() -> None:
    repository = BatchedRouteBonusScanRepository()

    result = BonusArbitrageScanService(repository).run(
        {
            "start": "2026-07-01 00:00:00", "end": "2026-07-03 00:00:00",
            "environments": ["ac_gb"], "deepLimit": 1, "excludeHandled": False,
        },
        progress=lambda *_args: None,
        cancelled=lambda: False,
    )

    assert repository.route_calls == 1
    assert repository.route_row_counts == [2]
    assert result["allResults"][0]["candidateGrantAmount"] == 500


class ConcurrentBonusScanRepository:
    def __init__(self) -> None:
        self.lock = Lock()
        self.candidate_active = 0
        self.candidate_max = 0
        self.deep_active = 0
        self.deep_max = 0
        self.prepare_calls = 0

    def scan_units(self, environments):
        return [{"id": f"unit-{index}", "label": f"Source {index}"} for index in range(8)]

    def discover_candidates(self, unit_id, start, end):
        with self.lock:
            self.candidate_active += 1
            self.candidate_max = max(self.candidate_max, self.candidate_active)
        sleep(0.04)
        with self.lock:
            self.candidate_active -= 1
        index = int(unit_id.rsplit("-", 1)[1])
        return [{
            "account": str(700000 + index), "source": unit_id, "platform": "MT5",
            "server": f"Server {index}", "environment": "ac_gb", "crmSchema": "crm",
            "serverCode": str(index), "databaseStatus": "", "currency": "USD",
            "grantCount": 1, "explicitGrantCount": 1, "grantAmount": 100 + index,
            "latestGrant": "2026-07-01 08:00:01",
        }]

    def load_account_context(self, login, filters):
        with self.lock:
            self.deep_active += 1
            self.deep_max = max(self.deep_max, self.deep_active)
        sleep(0.04)
        with self.lock:
            self.deep_active -= 1
        return {
            "profile": {"account": login, "platform": "MT5", "server": filters["server"], "currency": "USD"},
            "events": [], "trades": [], "peers": [],
        }

    def prepare_deep_candidates(self, candidates):
        self.prepare_calls += 1
        assert len(candidates) == 8


def test_platform_scan_bounds_candidate_and_deep_parallelism() -> None:
    repository = ConcurrentBonusScanRepository()

    result = BonusArbitrageScanService(repository).run(
        {
            "start": "2026-07-01 00:00:00", "end": "2026-07-02 00:00:00",
            "environments": ["ac_gb"], "deepLimit": 8, "excludeHandled": False,
        },
        progress=lambda *_args: None,
        cancelled=lambda: False,
    )

    assert result["summary"]["analyzedAccounts"] == 8
    assert repository.prepare_calls == 1
    assert 2 <= repository.candidate_max <= 4
    assert 2 <= repository.deep_max <= 3
