from __future__ import annotations

from datetime import datetime

import pytest

from kdesk.application.position_risk_scan import PositionRiskScanService, normalize_position_scan_options
from kdesk.domain.position_risk import number


class RepositoryStub:
    def scan_units(self, _environments):
        return [{"id": "unit-1", "label": "AC GB MT5"}]

    def discover_candidates(self, _unit_id, _start, _end):
        return [{"raw": True}]

    def route_candidates(self, _unit_id, _rows):
        return [
            {
                "account": "1001", "platform": "MT5", "server": "AC GB MT5", "environment": "ac_gb",
                "crmSchema": "int_sass_crm_ac", "serverCode": "1", "databaseStatus": "",
                "physicalSource": "ac-mt5", "bucket": "1", "symbol": "XAUUSD", "direction": "sell",
                "orderCount": 3, "eventLots": 3, "eventNotional": 720000, "equity": 3000,
                "leverage": 1000, "eventKind": "open", "firstEvent": "2026-07-20 22:01:00",
                "latestEvent": "2026-07-20 22:02:00", "_candidateMapping": {"mt_login": 1001},
            },
            {
                "account": "1002", "platform": "MT5", "server": "AC GB MT5", "environment": "ac_gb",
                "crmSchema": "int_sass_crm_ac", "serverCode": "1", "databaseStatus": "T",
                "physicalSource": "ac-mt5", "bucket": "1", "symbol": "XAUUSD", "direction": "sell",
                "orderCount": 1, "eventLots": 1, "eventNotional": 240000, "equity": 3000,
                "leverage": 500, "eventKind": "open", "firstEvent": "2026-07-20 22:01:00",
                "latestEvent": "2026-07-20 22:01:00", "_candidateMapping": {"mt_login": 1002},
            },
            {
                "account": "1003", "platform": "MT5", "server": "AC GB MT5", "environment": "ac_gb",
                "crmSchema": "int_sass_crm_ac", "serverCode": "1", "databaseStatus": "T",
                "physicalSource": "ac-mt5", "bucket": "1", "symbol": "XAUUSD", "direction": "buy",
                "orderCount": 1, "eventLots": 1, "eventNotional": 240000, "equity": 3000,
                "leverage": 500, "eventKind": "open", "firstEvent": "2026-07-20 22:01:03",
                "latestEvent": "2026-07-20 22:01:03", "_candidateMapping": {"mt_login": 1003},
            },
        ]

    def load_account_context(self, account, filters):
        rows = []
        for index in range(3):
            rows.append({
                "id": f"{account}-{index}", "ticket": f"{account}-{index}", "symbol": "XAUUSD",
                "direction": "sell", "openTime": f"2026-07-20 22:0{index}:00",
                "closeTime": f"2026-07-20 22:2{index}:00", "volume": 1,
                "openPrice": 2400, "closePrice": 2388, "contractSize": 100,
                "profit": 500, "netProfit": 500,
            })
        return {
            "profile": {"balance": 4500, "equity": 3000, "leverage": 1000, "currency": "USD", "platform": "MT5", "server": "AC GB MT5"},
            "trades": rows, "cashflows": [], "analysisStart": filters["start"], "analysisEnd": filters["end"],
        }

    def load_peer_accounts(self, _account, _context, event):
        return {
            "eventStart": event["start"], "eventEnd": event["end"],
            "sameDirectionAccounts": ["2001"], "oppositeDirectionAccounts": ["3001"],
            "sameDirectionMatches": [{"account": "2001", "targetOrderId": "1001-0", "orderId": "peer-1"}],
            "oppositeDirectionMatches": [{"account": "3001", "targetOrderId": "1001-0", "orderId": "peer-2"}],
            "peerSearchCoverage": {"status": "完成", "physicalSourceTotal": 8, "scannedSourceCount": 8},
        }


def test_scan_options_are_bounded() -> None:
    options = normalize_position_scan_options(
        {
            "start": "2026-07-01", "end": "2026-07-22", "deepLimit": 80, "environments": ["ac_gb"],
            "minPositionPercent": 20, "minLots": 2.5, "minProfit": 100,
        },
        now=datetime(2026, 7, 22),
    )
    assert options["deepLimit"] == 80
    assert options["minPositionPercent"] == 20
    assert options["minLots"] == 2.5
    assert options["minProfit"] == 100
    with pytest.raises(ValueError, match="90天"):
        normalize_position_scan_options({"start": "2026-01-01", "end": "2026-07-22"}, now=datetime(2026, 7, 22))
    with pytest.raises(ValueError, match="最低手数"):
        normalize_position_scan_options({"minLots": -1}, now=datetime(2026, 7, 22))


def test_scan_excludes_handled_and_returns_economic_warning() -> None:
    events = []
    result = PositionRiskScanService(RepositoryStub()).run(
        {"start": "2026-07-01", "end": "2026-07-22", "deepLimit": 10, "environments": ["ac_gb"]},
        progress=lambda percent, message: events.append((percent, message)),
        cancelled=lambda: False,
    )

    assert result["summary"]["candidateAccounts"] == 3
    assert result["summary"]["excludedHandled"] == 2
    assert result["summary"]["analyzedAccounts"] == 1
    assert result["results"][0]["account"] == "1001"
    assert result["results"][0]["stressRatio"] >= 0.1
    assert "2001" in result["results"][0]["peerAccounts"]
    assert result["results"][0]["sameDirectionAccounts"] == ["2001"]
    assert result["results"][0]["oppositeDirectionAccounts"] == ["3001"]
    assert result["results"][0]["peakLots"] == 3
    assert len(result["results"][0]["heavyOrders"]) == 3
    assert result["results"][0]["peerSearchCoverage"]["scannedSourceCount"] == 8
    assert events[-1][0] >= 90


def test_scan_never_falls_back_to_open_only_candidate_peers() -> None:
    class NoExactPeerRepository(RepositoryStub):
        def load_peer_accounts(self, _account, _context, event):
            return {
                "eventStart": event["start"], "eventEnd": event["end"],
                "sameDirectionAccounts": [], "oppositeDirectionAccounts": [],
                "sameDirectionMatches": [], "oppositeDirectionMatches": [],
                "peerSearchCoverage": {"status": "完成", "physicalSourceTotal": 8, "scannedSourceCount": 8},
            }

    result = PositionRiskScanService(NoExactPeerRepository()).run(
        {"start": "2026-07-01", "end": "2026-07-22", "deepLimit": 10, "environments": ["ac_gb"]},
        progress=lambda _percent, _message: None, cancelled=lambda: False,
    )

    assert result["results"][0]["sameDirectionAccounts"] == []
    assert result["results"][0]["oppositeDirectionAccounts"] == []
    assert result["results"][0]["peerAccounts"] == []


def test_scan_applies_optional_exact_position_lot_and_profit_filters() -> None:
    base_payload = {
        "start": "2026-07-01", "end": "2026-07-22", "deepLimit": 10, "environments": ["ac_gb"],
    }
    unfiltered = PositionRiskScanService(RepositoryStub()).run(
        base_payload, progress=lambda _percent, _message: None, cancelled=lambda: False,
    )
    row = unfiltered["allResults"][0]
    filtered = PositionRiskScanService(RepositoryStub()).run(
        {
            **base_payload,
            "minPositionPercent": number(row["marginRatio"]) * 100,
            "minLots": row["peakLots"],
            "minProfit": row["netProfit"],
        },
        progress=lambda _percent, _message: None,
        cancelled=lambda: False,
    )
    excluded = PositionRiskScanService(RepositoryStub()).run(
        {**base_payload, "minProfit": number(row["netProfit"]) + 0.01},
        progress=lambda _percent, _message: None,
        cancelled=lambda: False,
    )

    assert filtered["summary"]["matchedFilters"] == 1
    assert filtered["allResults"][0]["account"] == "1001"
    assert excluded["summary"]["matchedFilters"] == 0
    assert excluded["summary"]["excludedByFilters"] == 1
    assert excluded["allResults"] == []
