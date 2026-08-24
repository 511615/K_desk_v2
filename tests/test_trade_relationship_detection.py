from __future__ import annotations

from kdesk.application.trade_relationship_detection import (
    TradeRelationshipDetectionService,
    select_principal_orders,
)


def _order(order_id: str, volume: float, symbol: str = "XAUUSD") -> dict:
    return {
        "orderId": order_id,
        "positionId": order_id,
        "symbol": symbol,
        "direction": "buy",
        "volume": volume,
        "openTime": "2026-08-23 10:00:00",
        "closeTime": "2026-08-23 10:10:00",
    }


def test_select_principal_orders_preserves_small_symbols_and_covers_95_percent_volume() -> None:
    small = [_order(f"small-{index}", 0.01, "EURUSD") for index in range(4)]
    large = [_order(f"large-{index}", volume) for index, volume in enumerate([10, 9, 8, 7, 6, 1, 1, 1, 1, 1])]

    selected, stats = select_principal_orders([*small, *large])

    assert {row["orderId"] for row in small} <= {row["orderId"] for row in selected}
    selected_large = [row for row in selected if row["symbol"] == "XAUUSD"]
    assert len(selected_large) >= 5
    assert sum(row["volume"] for row in selected_large) / sum(row["volume"] for row in large) >= 0.95
    assert stats["targetVolumeCoverage"] == 95.0
    assert stats["rawOrderCount"] == 14


class _Repository:
    def load_account_context(self, account: str, filters: dict) -> dict:
        trades = []
        for index in range(10):
            trades.append({
                "id": f"position-{index}",
                "symbol": "XAUUSD",
                "direction": "buy",
                "volume": 1.0,
                "openTime": f"2026-08-23 10:00:{index:02d}",
                "closeTime": f"2026-08-23 10:10:{index:02d}",
                "isOpen": False,
                "entryOrders": [{
                    "orderId": f"root-{index}",
                    "dealId": f"deal-{index}",
                    "time": f"2026-08-23 10:00:{index:02d}",
                    "volume": 1.0,
                }],
            })
        return {
            "trades": trades,
            "analysisStart": "2026-08-23 00:00:00",
            "analysisEnd": "2026-08-23 23:59:59",
            "profile": {"platform": "MT5", "server": "AC CN MT5"},
        }

    def load_peer_accounts(self, account: str, context: dict, event: dict) -> dict:
        assert account == "100"
        assert len(event["heavyOrders"]) == 10
        same = [
            {
                "relation": "same", "account": "500", "platform": "MT5", "server": "AC CN MT5",
                "symbol": "XAUUSD", "targetOrderId": "root-0", "orderId": "peer-0",
                "targetVolume": 1.0, "volume": 1.0, "openDeltaSeconds": 1.0, "closeDeltaSeconds": 1.5,
            },
            # Same target duplicated by a second peer order: it must not inflate the account score.
            {
                "relation": "same", "account": "500", "platform": "MT5", "server": "AC CN MT5",
                "symbol": "XAUUSD", "targetOrderId": "root-0", "orderId": "peer-0b",
                "targetVolume": 1.0, "volume": 1.0, "openDeltaSeconds": 1.5, "closeDeltaSeconds": 1.8,
            },
            {
                "relation": "same", "account": "500", "platform": "MT5", "server": "AC CN MT5",
                "symbol": "XAUUSD", "targetOrderId": "root-1", "orderId": "peer-1",
                "targetVolume": 1.0, "volume": 1.0, "openDeltaSeconds": 0.8, "closeDeltaSeconds": 1.2,
            },
            # One hit is below the recurrence floor and must be omitted.
            {
                "relation": "same", "account": "501", "platform": "MT5", "server": "AC CN MT5",
                "symbol": "XAUUSD", "targetOrderId": "root-2", "orderId": "peer-2",
                "targetVolume": 1.0, "volume": 1.0, "openDeltaSeconds": 0.5, "closeDeltaSeconds": 0.5,
            },
            # Outside the stricter push-style two-second window.
            {
                "relation": "same", "account": "502", "platform": "MT5", "server": "AC CN MT5",
                "symbol": "XAUUSD", "targetOrderId": "root-3", "orderId": "peer-3",
                "targetVolume": 1.0, "volume": 1.0, "openDeltaSeconds": 3.0, "closeDeltaSeconds": 1.0,
            },
        ]
        opposite = [{
            "relation": "opposite", "account": "600", "platform": "MT4", "server": "DBG CN MT4",
            "symbol": "XAUUSD", "targetOrderId": "root-4", "orderId": "hedge-4",
            "targetVolume": 1.0, "volume": 0.9, "openDeltaSeconds": 4.0, "closeDeltaSeconds": 3.0,
            "lotSimilarity": 0.9, "lotSimilarityPct": 90.0,
        }]
        return {
            "sameDirectionMatches": same,
            "oppositeDirectionMatches": opposite,
            "peerSearchCoverage": {
                "status": "完成", "scope": "AC/DBG 全平台 MT4 + MT5",
                "physicalSourceTotal": 9, "scannedSourceCount": 9,
            },
        }


def test_trade_relationship_detection_aggregates_by_peer_and_applies_distinct_rules() -> None:
    result = TradeRelationshipDetectionService(_Repository()).analyze("100", {})

    assert {(row["relation"], row["account"]) for row in result["matches"]} == {
        ("same", "500"), ("opposite", "600"),
    }
    same = next(row for row in result["matches"] if row["relation"] == "same")
    opposite = next(row for row in result["matches"] if row["relation"] == "opposite")
    assert same["matchCount"] == 2
    assert same["matchRatioPct"] == 20.0
    assert len(same["orderPairs"]) == 2
    assert opposite["matchCount"] == 1
    assert opposite["minimumLotSimilarityPct"] == 90.0
    assert result["summary"]["principalOrderCount"] == 10
    assert result["summary"]["sameDirectionAccountCount"] == 1
    assert result["summary"]["oppositeDirectionAccountCount"] == 1


def test_trade_relationship_detection_preserves_partial_source_coverage() -> None:
    class _PartialRepository(_Repository):
        def load_peer_accounts(self, account: str, context: dict, event: dict) -> dict:
            payload = super().load_peer_accounts(account, context, event)
            payload["peerSearchCoverage"] = {
                "status": "部分完成",
                "reason": "DBG MT4 查询超时",
                "scope": "AC/DBG 全平台 MT4 + MT5",
                "physicalSourceTotal": 9,
                "scannedSourceCount": 8,
            }
            return payload

    result = TradeRelationshipDetectionService(_PartialRepository()).analyze("100", {})

    assert result["coverage"][0]["status"] == "部分完成"
    assert result["coverage"][0]["reason"] == "DBG MT4 查询超时"
    assert result["coverage"][0]["scannedSourceCount"] == 8
    assert result["matches"]
