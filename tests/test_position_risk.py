from __future__ import annotations

from pathlib import Path

from kdesk.domain.position_risk import analyze_position_risk, match_synchronized_peer_orders


def trade(ticket: str, opened: str, closed: str, *, direction: str = "sell", profit: float = 600, volume: float = 1) -> dict:
    return {
        "id": ticket,
        "ticket": ticket,
        "symbol": "XAUUSD",
        "direction": direction,
        "openTime": opened,
        "closeTime": closed,
        "volume": volume,
        "openPrice": 2400,
        "closePrice": 2388 if direction == "sell" else 2412,
        "contractSize": 100,
        "profit": profit,
        "netProfit": profit,
    }


def context(rows: list[dict], *, balance: float = 2_000, leverage: float = 500) -> dict:
    return {
        "now": "2026-07-22 12:00:00",
        "profile": {"balance": balance + sum(row["netProfit"] for row in rows), "equity": balance, "leverage": leverage},
        "cashflows": [],
        "trades": rows,
    }


def test_weekend_requires_economic_heavy_position_before_timing() -> None:
    heavy = context([
        trade("1", "2026-07-17 20:55:00", "2026-07-19 22:01:00"),
        trade("2", "2026-07-17 20:56:00", "2026-07-19 22:02:00"),
    ])
    result = analyze_position_risk(heavy, type_ids=["weekend_gap_trading"])["results"][0]

    assert result["score"] >= 60
    assert result["evidence"]["bestEvent"]["heavyPosition"] is True
    assert "先确认经济重仓" in result["summary"]

    light = context([
        trade("3", "2026-07-17 20:55:00", "2026-07-19 22:01:00", profit=1, volume=0.01),
    ], balance=100_000)
    light_result = analyze_position_risk(light, type_ids=["weekend_gap_trading"])["results"][0]
    assert light_result["score"] < 40
    assert light_result["evidence"]["bestEvent"]["heavyPosition"] is False


def test_open_betting_uses_leverage_adjusted_margin_and_stress() -> None:
    rows = [
        trade("1", "2026-07-20 22:01:00", "2026-07-20 22:24:00", profit=-500),
        trade("2", "2026-07-20 22:01:30", "2026-07-20 22:24:30", profit=-450),
        trade("3", "2026-07-20 22:02:00", "2026-07-20 22:25:00", profit=-550),
    ]
    result = analyze_position_risk(context(rows, balance=3_000, leverage=1000), type_ids=["open_betting"])["results"][0]
    event = result["evidence"]["bestEvent"]

    assert result["score"] >= 60
    assert event["leverage"] == 1000
    assert event["stressRatio"] >= 0.1
    assert result["requiresTick"] is False
    assert "亏损" not in result["summary"] or event["heavyPosition"] is True


def test_combined_weekend_and_reopen_positions_are_shared_without_double_counting() -> None:
    rows = [
        trade("weekend", "2026-07-17 20:54:00", "2026-07-19 22:01:00", profit=500),
        trade("reopen", "2026-07-19 22:11:00", "2026-07-19 22:40:00", direction="buy", profit=-300),
    ]
    result = analyze_position_risk(context(rows, balance=1_000), type_ids=["weekend_gap_trading", "open_betting"])

    assert {row["type"] for row in result["results"]} == {"weekend_gap_trading", "open_betting"}
    assert all(row["evidence"]["bestEvent"]["classification"] == "combined" for row in result["results"])


def test_staggered_entries_are_counterevidence() -> None:
    batch = [
        trade("b1", "2026-07-20 22:00:00", "2026-07-20 22:30:00"),
        trade("b2", "2026-07-20 22:01:00", "2026-07-20 22:31:00"),
        trade("b3", "2026-07-20 22:02:00", "2026-07-20 22:32:00"),
    ]
    staggered = [
        trade("s1", "2026-07-20 21:46:00", "2026-07-20 23:30:00"),
        trade("s2", "2026-07-20 22:00:00", "2026-07-20 23:31:00"),
        trade("s3", "2026-07-20 22:25:00", "2026-07-20 23:32:00"),
    ]

    batch_score = analyze_position_risk(context(batch), type_ids=["open_betting"])["results"][0]["score"]
    staggered_score = analyze_position_risk(context(staggered), type_ids=["open_betting"])["results"][0]["score"]
    assert staggered_score < batch_score


def test_result_lists_peak_heavy_orders_position_size_and_peer_direction() -> None:
    rows = [
        trade("o1", "2026-07-20 22:00:00", "2026-07-20 22:25:00", volume=1.5),
        trade("o2", "2026-07-20 22:00:30", "2026-07-20 22:25:30", volume=2.0),
    ]
    payload = context(rows, balance=2_000)
    payload["peerEvidence"] = {
        "eventStart": "2026-07-20 22:00:00", "eventEnd": "2026-07-20 22:25:30",
        "sameDirectionAccounts": ["2001", "2002"], "oppositeDirectionAccounts": ["3001"],
    }

    event = analyze_position_risk(payload, type_ids=["open_betting"])["results"][0]["evidence"]["bestEvent"]

    assert event["peakLots"] == 3.5
    assert event["peakOrderCount"] == 2
    assert {row["orderId"] for row in event["heavyOrders"]} == {"o1", "o2"}
    assert event["sameDirectionAccounts"] == ["2001", "2002"]
    assert event["oppositeDirectionAccounts"] == ["3001"]
    assert event["peerAccounts"] == ["2001", "2002"]


def test_peer_orders_require_synchronized_open_and_close() -> None:
    target = [{
        "orderId": "t-1", "positionId": "tp-1", "symbol": "XAUUSD", "direction": "sell", "volume": 2,
        "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:30:00",
    }]
    peers = [
        {
            "account": "2001", "platform": "MT5", "server": "AC GB MT5", "database": "ac.mt5_deals",
            "physicalSource": "ac", "orderId": "same", "positionId": "p1", "dealId": "d1",
            "symbol": "XAUUSD.a", "direction": "sell", "volume": 1, "fullyClosed": True,
            "openTime": "2026-07-20 22:00:05", "closeTime": "2026-07-20 22:29:56",
        },
        {
            "account": "3001", "platform": "MT4", "server": "DBG MT4 CN1", "database": "dbg.mt4_trades",
            "physicalSource": "dbg", "orderId": "opposite", "positionId": "opposite", "dealId": "",
            "symbol": "XAUUSD", "direction": "buy", "volume": 1.6, "fullyClosed": True,
            "openTime": "2026-07-20 21:59:56", "closeTime": "2026-07-20 22:30:05",
        },
        {
            "account": "3002", "platform": "MT4", "server": "DBG MT4 CN1", "database": "dbg.mt4_trades",
            "physicalSource": "dbg", "orderId": "opposite-small", "positionId": "opposite-small", "dealId": "",
            "symbol": "XAUUSD", "direction": "buy", "volume": 1.59, "fullyClosed": True,
            "openTime": "2026-07-20 21:59:56", "closeTime": "2026-07-20 22:30:05",
        },
        {
            "account": "4001", "platform": "MT5", "server": "AC CN MT5", "database": "ac2.mt5_deals",
            "physicalSource": "ac2", "orderId": "late-close", "positionId": "p4", "dealId": "d4",
            "symbol": "XAUUSD", "direction": "sell", "volume": 1, "fullyClosed": True,
            "openTime": "2026-07-20 22:00:01", "closeTime": "2026-07-20 22:30:06",
        },
        {
            "account": "5001", "platform": "MT5", "server": "AC CN MT5", "database": "ac2.mt5_deals",
            "physicalSource": "ac2", "orderId": "open-only", "positionId": "p5", "dealId": "d5",
            "symbol": "XAUUSD", "direction": "sell", "volume": 1, "fullyClosed": False,
            "openTime": "2026-07-20 22:00:01", "closeTime": "",
        },
    ]

    result = match_synchronized_peer_orders(target, peers)

    assert result["sameDirectionAccounts"] == ["2001"]
    assert result["oppositeDirectionAccounts"] == ["3001"]
    assert result["sameDirectionMatches"][0]["targetOrderId"] == "t-1"
    assert result["sameDirectionMatches"][0]["closeDeltaSeconds"] == 4
    assert result["oppositeDirectionMatches"][0]["lotSimilarity"] == 0.8
    assert result["oppositeLotSimilarityThreshold"] == 0.8


def test_peer_order_detail_is_bounded_without_losing_account_totals() -> None:
    target = [{
        "orderId": "target", "symbol": "XAUUSD", "direction": "sell", "volume": 1,
        "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:30:00",
    }]
    peers = [{
        "account": str(2000 + index), "platform": "MT5", "server": "AC GB MT5", "database": "ac.mt5_deals",
        "physicalSource": "ac", "orderId": f"peer-{index}", "positionId": f"peer-{index}", "dealId": f"deal-{index}",
        "symbol": "XAUUSD", "direction": "sell", "volume": 1, "fullyClosed": True,
        "openTime": "2026-07-20 22:00:00", "closeTime": "2026-07-20 22:30:00",
    } for index in range(501)]

    result = match_synchronized_peer_orders(target, peers)

    assert result["sameDirectionMatchTotal"] == 501
    assert len(result["sameDirectionAccounts"]) == 501
    assert len(result["sameDirectionMatches"]) == 500
    assert result["peerMatchesTruncated"] is True


def test_margin_fields_and_penetration_gaps_are_explicit() -> None:
    rows = [trade("m1", "2026-07-20 22:00:00", "2026-07-20 22:25:00", volume=2)]
    event = analyze_position_risk(context(rows, balance=2_000, leverage=500), type_ids=["open_betting"])["results"][0]["evidence"]["bestEvent"]

    assert event["estimatedMargin"] == round(event["peakGrossExposure"] / 500, 2)
    assert event["estimatedMarginLevel"] == round(100 / event["marginRatio"], 2)
    assert event["eventClosed"] is True
    assert event["penetrationDataGaps"] == []

    open_row = trade("open", "2026-07-20 22:00:00", "", volume=2)
    open_row["isOpen"] = True
    open_event = analyze_position_risk(context([open_row], balance=2_000), type_ids=["open_betting"])["results"][0]["evidence"]["bestEvent"]
    assert open_event["penetrationStatus"] == "数据不足"
    assert "事件仍有未平仓订单" in open_event["penetrationDataGaps"]


def test_legacy_account_toxic_modal_exposes_position_and_peer_orders() -> None:
    source = Path("legacy/apps/problem_account_registry/app.py").read_text(encoding="utf-8")

    assert "重仓与全平台同步开平仓证据" in source
    assert "保证金占权益" in source
    assert "同步同向订单" in source
    assert "同步反向疑似对锁订单" in source
    assert "event.sameDirectionMatches" in source


def test_legacy_account_toxic_modal_exposes_dedicated_internal_lock_query() -> None:
    source = Path("legacy/apps/problem_account_registry/app.py").read_text(encoding="utf-8")

    assert "function renderInternalLockEvidence" in source
    assert "平台内多账户对锁查询" in source
    assert "反向同步开平仓订单" in source
    assert "query.matches" in source
    assert "手数相似度" in source


def test_penetration_status_distinguishes_actual_loss_and_reset_clue() -> None:
    breached_rows = [
        trade("l1", "2026-07-20 22:00:00", "2026-07-20 22:25:00", profit=-1_200),
        trade("l2", "2026-07-20 22:00:30", "2026-07-20 22:25:30", profit=-1_100),
    ]
    breached = analyze_position_risk(
        context(breached_rows, balance=1_000), type_ids=["open_betting"],
    )["results"][0]["evidence"]["bestEvent"]
    assert breached["penetrationStatus"] == "是"
    assert breached["actualLoss"] == 2300

    reset_payload = context([
        trade("r1", "2026-07-20 22:00:00", "2026-07-20 22:25:00", profit=-100),
    ], balance=1_000)
    reset_payload["cashflows"] = [{
        "time": "2026-07-20 22:30:00", "amount": 100, "affectsBalance": True,
        "comment": "Negative Balance Protection",
    }]
    reset = analyze_position_risk(reset_payload, type_ids=["open_betting"])["results"][0]["evidence"]["bestEvent"]
    assert reset["penetrationStatus"] == "疑似"
    assert reset["negativeBalanceEvidence"][0]["comment"] == "Negative Balance Protection"
