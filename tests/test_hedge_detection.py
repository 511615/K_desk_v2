from __future__ import annotations

from kdesk.application.hedge_detection import CrossAccountHedgeService


class Repository:
    captured_event: dict = {}

    @staticmethod
    def load_account_context(_account: str, _filters: dict) -> dict:
        return {
            "profile": {"platform": "MT5", "server": "AC GB MT5", "currency": "USD", "moneyScale": 1},
            "source": {"host": "ac", "schema": "ac_mt5", "table": "mt5_deals", "kind": "mt5_deals"},
            "trades": [
                {
                    "id": "position-1", "symbol": "XAUUSD", "direction": "sell", "volume": 2,
                    "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:30:00",
                    "entryOrders": [{"orderId": "target-order", "dealId": "target-deal", "time": "2026-07-20 22:00:00", "volume": 2}],
                },
                {
                    "id": "open-position", "symbol": "XAUUSD", "direction": "buy", "volume": 1,
                    "openTime": "2026-07-21 10:00:00", "closeTime": "", "isOpen": True,
                },
            ],
        }

    def load_peer_accounts(self, _account: str, _context: dict, event: dict) -> dict:
        self.captured_event = event
        return {
            "sameDirectionAccounts": ["same-account"],
            "sameDirectionMatches": [{"account": "same-account"}],
            "oppositeDirectionAccounts": ["2001"],
            "oppositeDirectionMatchTotal": 1,
            "oppositeDirectionMatches": [{
                "account": "2001", "platform": "MT4", "server": "DBG MT4 CN1",
                "database": "dbg.mt4_trades", "orderId": "peer-order", "positionId": "peer-order",
                "dealId": "", "targetOrderId": "target-order", "targetPositionId": "position-1",
                "symbol": "XAUUSD", "direction": "buy", "targetDirection": "sell",
                "volume": 1.8, "targetVolume": 2, "lotSimilarity": 0.9,
                "openDeltaSeconds": 2, "closeDeltaSeconds": 1,
                "openTime": "2026-07-20 22:00:02", "closeTime": "2026-07-20 22:30:01",
                "targetOpenTime": "2026-07-20 22:00:00", "targetCloseTime": "2026-07-20 22:30:00",
            }],
            "peerMatchDetailLimit": 500,
            "peerMatchesTruncated": False,
            "oppositeLotSimilarityThreshold": 0.8,
            "peerSearchCoverage": {
                "scope": "AC/DBG 全平台 MT4 + MT5", "status": "完成",
                "scannedSourceCount": 8, "physicalSourceTotal": 8, "failures": [],
            },
        }


def test_cross_account_hedge_query_returns_only_opposite_synchronized_orders() -> None:
    repository = Repository()
    analysis = CrossAccountHedgeService(repository).analyze("1001", {"platform": "MT5", "server": "AC GB MT5"})
    result = analysis["result"]
    evidence = analysis["evidence"]

    assert result["type"] == "internal_lock_arbitrage"
    assert result["level"] == "发现疑似对锁"
    assert evidence["accountCount"] == 1
    assert evidence["matchTotal"] == 1
    assert evidence["openPositionCount"] == 1
    assert evidence["matches"][0]["account"] == "2001"
    assert evidence["matches"][0]["lotSimilarity"] == 0.9
    assert evidence["lotSimilarityThreshold"] == 0.8
    assert evidence["accounts"][0]["server"] == "DBG MT4 CN1"
    assert repository.captured_event["heavyOrders"][0]["orderId"] == "target-order"
    assert "sameDirectionAccounts" not in evidence


def test_cross_account_hedge_query_does_not_claim_clean_when_coverage_is_partial() -> None:
    class PartialRepository(Repository):
        def load_peer_accounts(self, account: str, context: dict, event: dict) -> dict:
            result = super().load_peer_accounts(account, context, event)
            result["oppositeDirectionAccounts"] = []
            result["oppositeDirectionMatches"] = []
            result["oppositeDirectionMatchTotal"] = 0
            result["peerSearchCoverage"] = {
                "scope": "AC/DBG 全平台 MT4 + MT5", "status": "部分失败",
                "scannedSourceCount": 7, "physicalSourceTotal": 8,
                "failures": [{"platform": "MT4", "server": "DBG MT4 CN1", "database": "dbg.mt4_trades", "reason": "timeout"}],
            }
            return result

    result = CrossAccountHedgeService(PartialRepository()).analyze("1001", {})["result"]

    assert result["level"] == "数据不足"
    assert "不能作为全平台无对锁结论" in result["summary"]
    assert result["confidence"] == 65
