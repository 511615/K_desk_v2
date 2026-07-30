from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from time import perf_counter, sleep

import pytest

from kdesk.domain.bonus_arbitrage import BonusAnalysisCancelled, detect_bonus_arbitrage
from kdesk.infrastructure.bonus_arbitrage import LegacyBonusArbitrageRepository


def event(event_id: str, time: str, kind: str, amount: float, counterparty: str = "") -> dict:
    return {"id": event_id, "time": time, "kind": kind, "amount": amount, "counterparty": counterparty}


def trade(trade_id: str, opened: str, closed: str, net: float, direction: str = "buy", volume: float = 1.0) -> dict:
    return {
        "id": trade_id, "openTime": opened, "closeTime": closed, "netProfit": net,
        "direction": direction, "symbol": "XAUUSD", "volume": volume, "isOpen": not bool(closed),
        "openPrice": 2000, "contractSize": 100,
    }


def profile() -> dict:
    return {"platform": "MT5", "server": "AC GB MT5", "currency": "USD", "moneyScale": 1.0, "leverage": 100}


def test_complete_profit_extraction_cycle_is_severe() -> None:
    events = [
        event("d1", "2026-02-02 14:25:57", "deposit", 500),
        event("c1", "2026-02-02 14:25:57", "bonus_grant", 500),
        event("t1", "2026-02-03 05:05:24", "transfer", -1125.53, "622002"),
        event("c2", "2026-02-03 05:05:24", "bonus_remove", -500),
    ]
    trades = [trade("p1", "2026-02-02 15:15:57", "2026-02-02 15:53:16", 625.53, volume=0.09)]

    result = detect_bonus_arbitrage(profile(), events, trades)

    assert result["score"] >= 90
    assert result["evidence"]["cycles"][0]["extractor"] is True
    assert "完整闭环" in result["triggeredRules"][0]


@pytest.mark.parametrize("grant", [100, 181.8])
def test_profit_extraction_below_bonus_ratio_gate_is_not_bonus_arbitrage(grant: float) -> None:
    events = [
        event("d1", "2026-02-02 08:00:00", "deposit", 1000),
        event("c1", "2026-02-02 08:00:01", "bonus_grant", grant),
        event("w1", "2026-02-02 12:00:00", "withdrawal", -2000),
        event("r1", "2026-02-02 12:00:01", "bonus_remove", -grant),
    ]
    trades = [trade("p1", "2026-02-02 09:00:00", "2026-02-02 11:00:00", 1000, volume=1.0)]

    result = detect_bonus_arbitrage(profile(), events, trades)
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] <= 39
    assert result["level"] == "无明显风险"
    assert cycle["bonusRatioEligible"] is False
    assert cycle["requiredBonusToCash"] == 0.2
    assert cycle["extractor"] is False
    assert "硬门槛" in result["summary"]


def test_coordinated_sacrifice_below_bonus_ratio_gate_is_not_bonus_arbitrage() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 100),
        event("c2", "2026-03-02 18:00:00", "bonus_remove", -100),
    ]
    trades = [trade("p1", "2026-03-02 09:00:00", "2026-03-02 16:00:00", -1100, direction="buy")]
    peers = [{
        "account": "900001",
        "trades": [trade("q1", "2026-03-02 09:00:02", "2026-03-02 16:00:00", 1050, direction="sell")],
    }]

    result = detect_bonus_arbitrage(profile(), events, trades, peers)
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] <= 39
    assert cycle["bonusRatioEligible"] is False
    assert cycle["sacrifice"] is False
    assert cycle["coordinatedSacrifice"] is False


def test_bonus_without_cashout_or_removal_stays_below_warning() -> None:
    events = [
        event("d1", "2026-03-01 10:00:00", "deposit", 1000),
        event("c1", "2026-03-01 10:00:01", "bonus_grant", 200),
    ]
    trades = [
        trade("p1", "2026-03-03 10:00:00", "2026-03-04 10:00:00", 35, volume=0.1),
        trade("p2", "2026-03-08 10:00:00", "2026-03-10 10:00:00", -20, direction="sell", volume=0.1),
    ]

    result = detect_bonus_arbitrage(profile(), events, trades)

    assert result["score"] < 60
    assert result["level"] in {"关注", "无明显风险"}


def test_bonus_cycle_heavy_position_is_high_risk_without_cashout_or_visible_peer() -> None:
    events = [
        event("d1", "2026-03-01 08:00:00", "deposit", 1000),
        event("c1", "2026-03-01 08:00:01", "bonus_grant", 1000),
    ]
    trades = [trade("p1", "2026-03-01 09:00:00", "", 0, volume=1.5)]

    result = detect_bonus_arbitrage(profile(), events, trades)
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] >= 75
    assert result["level"] == "高危形态"
    assert cycle["highBonusHeavyPosition"] is True
    assert cycle["coordinatedHeavyPosition"] is False
    assert cycle["openTradeCount"] == 1
    assert cycle["minimumMarginLevel"] == pytest.approx(66.6667)
    assert cycle["minimumUsedMargin"] == 3000
    assert cycle["minimumConcurrentLots"] == 1.5
    assert cycle["minimumOrderCount"] == 1
    assert cycle["minimumMarginAt"] == "2026-03-01 09:00:00"
    assert cycle["minimumMarginOrders"][0]["tradeId"] == "p1"
    assert cycle["minimumMarginOrders"][0]["volume"] == 1.5
    assert cycle["minimumMarginOrders"][0]["estimatedMargin"] == 3000
    assert cycle["heavyMarginLevelThreshold"] == 200
    assert any("重点风险" in rule for rule in result["triggeredRules"])


def test_peak_position_evidence_lists_only_orders_open_at_the_peak() -> None:
    events = [
        event("d1", "2026-03-01 08:00:00", "deposit", 1000),
        event("c1", "2026-03-01 08:00:01", "bonus_grant", 1000),
    ]
    trades = [
        trade("p1", "2026-03-01 09:00:00", "2026-03-01 10:30:00", 10, volume=0.8),
        trade("p2", "2026-03-01 09:30:00", "2026-03-01 11:00:00", -5, direction="sell", volume=0.7),
        trade("p3", "2026-03-01 10:45:00", "2026-03-01 12:00:00", 3, volume=0.4),
    ]

    cycle = detect_bonus_arbitrage(profile(), events, trades)["evidence"]["cycles"][0]

    assert cycle["minimumConcurrentLots"] == 1.5
    assert cycle["minimumOrderCount"] == 2
    assert cycle["minimumMarginAt"] == "2026-03-01 09:30:00"
    assert [row["tradeId"] for row in cycle["minimumMarginOrders"]] == ["p1", "p2"]


def test_visible_opposite_leg_promotes_high_bonus_heavy_position_to_high_risk() -> None:
    events = [
        event("d1", "2026-03-01 08:00:00", "deposit", 1000),
        event("c1", "2026-03-01 08:00:01", "bonus_grant", 1000),
    ]
    trades = [trade("p1", "2026-03-01 09:00:00", "", 0, direction="buy", volume=1.5)]
    peers = [{
        "account": "900001",
        "trades": [trade("q1", "2026-03-01 09:00:02", "", 0, direction="sell", volume=1.5)],
    }]

    result = detect_bonus_arbitrage(profile(), events, trades, peers)
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] >= 75
    assert cycle["highBonusHeavyPosition"] is True
    assert cycle["coordinatedHeavyPosition"] is True
    assert any("同步反向订单" in rule for rule in result["triggeredRules"])


def test_visible_opposite_leg_only_increases_heavy_position_confidence() -> None:
    events = [
        event("d1", "2026-03-01 08:00:00", "deposit", 1000),
        event("c1", "2026-03-01 08:00:01", "bonus_grant", 1000),
    ]
    trades = [trade("p1", "2026-03-01 09:00:00", "", 0, direction="buy", volume=1.5)]
    peers = [{
        "account": "900001",
        "trades": [trade("q1", "2026-03-01 09:00:02", "", 0, direction="sell", volume=1.5)],
    }]

    without_peer = detect_bonus_arbitrage(profile(), events, trades)
    with_peer = detect_bonus_arbitrage(profile(), events, trades, peers)

    assert with_peer["score"] == without_peer["score"]
    assert with_peer["confidence"] > without_peer["confidence"]


@pytest.mark.parametrize(
    ("grant", "trades"),
    [
        (100, [trade("low-ratio", "2026-03-01 09:00:00", "", 0, volume=1.0)]),
        (1000, [trade("light", "2026-03-01 09:00:00", "", 0, volume=0.2)]),
    ],
)
def test_cycle_heavy_warning_rejects_low_ratio_or_light_positions(
    grant: float,
    trades: list[dict],
) -> None:
    events = [
        event("d1", "2026-03-01 08:00:00", "deposit", 1000),
        event("c1", "2026-03-01 08:00:01", "bonus_grant", grant),
    ]

    result = detect_bonus_arbitrage(profile(), events, trades)
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] < 60
    assert cycle["highBonusHeavyPosition"] is False


def test_heavy_position_later_in_bonus_cycle_is_still_high_risk() -> None:
    events = [
        event("d1", "2026-03-01 08:00:00", "deposit", 1000),
        event("c1", "2026-03-01 08:00:01", "bonus_grant", 200),
    ]
    trades = [trade("late", "2026-03-05 09:00:02", "", 0, volume=1.5)]

    result = detect_bonus_arbitrage(profile(), events, trades)
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] >= 75
    assert cycle["highBonusHeavyPosition"] is True
    assert cycle["minimumMarginAt"] == "2026-03-05 09:00:02"


def test_balanced_directions_do_not_clear_high_bonus_heavy_position_risk() -> None:
    events = [
        event("d1", "2026-03-01 08:00:00", "deposit", 1000),
        event("c1", "2026-03-01 08:00:01", "bonus_grant", 1000),
    ]
    trades = [
        trade("buy", "2026-03-01 09:00:00", "", 0, direction="buy", volume=0.6),
        trade("sell", "2026-03-01 09:00:00", "", 0, direction="sell", volume=0.6),
    ]

    result = detect_bonus_arbitrage(profile(), events, trades)

    assert result["score"] >= 75
    assert result["evidence"]["cycles"][0]["highBonusHeavyPosition"] is True


def test_historical_loss_over_75_percent_warns_without_visible_peer() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
        event("c2", "2026-03-02 18:00:00", "bonus_remove", -1000),
    ]
    trades = [trade("p1", "2026-03-02 09:00:00", "2026-03-02 16:00:00", -1980, volume=0.35)]

    result = detect_bonus_arbitrage(profile(), events, trades)

    assert result["score"] >= 60
    assert result["evidence"]["cycles"][0]["sacrifice"] is True
    assert result["evidence"]["cycles"][0]["coordinatedSacrifice"] is False
    assert result["evidence"]["cycles"][0]["nearFundingBreach"] is True


def test_recovered_near_breach_does_not_cap_completed_extraction() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 200),
        event("w1", "2026-03-03 16:00:00", "withdrawal", -1300),
        event("c2", "2026-03-03 16:00:01", "bonus_remove", -200),
    ]
    trades = [
        trade("loss", "2026-03-02 09:00:00", "2026-03-02 12:00:00", -970, volume=0.2),
        trade("recovery", "2026-03-03 09:00:00", "2026-03-03 12:00:00", 1270, volume=0.2),
    ]

    result = detect_bonus_arbitrage(profile(), events, trades)
    cycle = result["evidence"]["cycles"][0]

    assert cycle["nearFundingBreach"] is True
    assert cycle["extractor"] is True
    assert result["score"] >= 75


def test_negative_balance_reset_during_bonus_cycle_is_severe() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
        {**event("rst1", "2026-03-02 18:00:00", "reset", 125), "comment": "Negative balance clearing"},
        event("c2", "2026-03-02 18:00:01", "bonus_remove", -1000),
    ]

    result = detect_bonus_arbitrage(profile(), events, [])
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] >= 90
    assert cycle["everFundingBreach"] is True
    assert cycle["resetCount"] == 1
    assert cycle["resetEvents"][0]["id"] == "rst1"


def test_historical_funding_breach_survives_later_profit_recovery() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
        event("c2", "2026-03-04 18:00:00", "bonus_remove", -1000),
    ]
    trades = [
        trade("loss", "2026-03-02 09:00:00", "2026-03-02 12:00:00", -2100, volume=0.2),
        trade("recovery", "2026-03-03 09:00:00", "2026-03-03 12:00:00", 2300, volume=0.2),
    ]

    result = detect_bonus_arbitrage(profile(), events, trades)
    cycle = result["evidence"]["cycles"][0]

    assert cycle["netProfit"] == 200
    assert cycle["worstTradeLoss"] == 2100
    assert cycle["worstTradeLossAt"] == "2026-03-02 12:00:00"
    assert cycle["everFundingBreach"] is True
    assert result["score"] >= 90


def test_same_time_closes_are_net_before_historical_breach_decision() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
    ]
    trades = [
        trade("loss", "2026-03-02 09:00:00", "2026-03-02 12:00:00", -2100, volume=0.2),
        trade("hedge", "2026-03-02 09:00:00", "2026-03-02 12:00:00", 2300, volume=0.2),
    ]

    result = detect_bonus_arbitrage(profile(), events, trades)
    cycle = result["evidence"]["cycles"][0]

    assert cycle["worstTradeLoss"] == 0
    assert cycle["everFundingBreach"] is False


def test_current_negative_balance_or_equity_is_severe() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 500),
    ]
    negative_profile = {**profile(), "balance": 50, "equity": -10}

    result = detect_bonus_arbitrage(negative_profile, events, [])
    cycle = result["evidence"]["cycles"][0]

    assert result["score"] >= 90
    assert cycle["everFundingBreach"] is True
    assert cycle["currentNegativeAccount"] is True


def test_low_bonus_ratio_still_caps_historical_breach_at_39() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 100),
        event("rst1", "2026-03-02 18:00:00", "reset", 100),
    ]

    result = detect_bonus_arbitrage(profile(), events, [])

    assert result["score"] <= 39
    assert result["evidence"]["cycles"][0]["everFundingBreach"] is False


def test_opposite_peer_promotes_sacrifice_account_to_high_risk() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
        event("c2", "2026-03-02 18:00:00", "bonus_remove", -1000),
    ]
    trades = [trade("p1", "2026-03-02 09:00:00", "2026-03-02 16:00:00", -1980, direction="buy", volume=1.0)]
    peers = [{
        "account": "900001",
        "trades": [trade("q1", "2026-03-02 09:00:02", "2026-03-02 16:00:00", 1900, direction="sell", volume=1.0)],
    }]

    result = detect_bonus_arbitrage(profile(), events, trades, peers)

    assert result["score"] >= 75
    assert result["evidence"]["cycles"][0]["coordinatedSacrifice"] is True
    assert result["evidence"]["cycles"][0]["peerMatch"]["lotCoverage"] == 1.0


def test_peer_matching_keeps_one_to_one_and_prefers_closest_best_volume() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
        event("c2", "2026-03-02 18:00:00", "bonus_remove", -1000),
    ]
    trades = [
        trade("p1", "2026-03-02 09:00:00", "2026-03-02 16:00:00", -990, direction="buy", volume=1.0),
        trade("p2", "2026-03-02 09:00:00", "2026-03-02 16:00:00", -990, direction="buy", volume=1.0),
    ]
    peers = [{
        "account": "900001",
        "trades": [
            trade("far", "2026-03-02 09:00:03", "2026-03-02 16:00:00", 900, direction="sell", volume=1.0),
            trade("near-small", "2026-03-02 09:00:01", "2026-03-02 16:00:00", 900, direction="sell", volume=0.8),
            trade("near-full", "2026-03-02 09:00:01", "2026-03-02 16:00:00", 900, direction="sell", volume=1.0),
        ],
    }]

    result = detect_bonus_arbitrage(profile(), events, trades, peers)
    match = result["evidence"]["cycles"][0]["peerMatch"]

    assert match["matches"] == 2
    assert match["details"][0]["peerTrade"] == "near-full"
    assert match["details"][1]["peerTrade"] == "near-small"


def test_peer_matching_large_history_stays_linearithmic() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
        event("c2", "2026-03-04 00:00:00", "bonus_remove", -1000),
    ]
    base = 9 * 3600
    trades = []
    peer_trades = []
    for index in range(10_000):
        second = base + index * 10
        hour, remainder = divmod(second, 3600)
        minute, second_value = divmod(remainder, 60)
        opened = f"2026-03-{2 + hour // 24:02d} {hour % 24:02d}:{minute:02d}:{second_value:02d}"
        peer_opened = f"2026-03-{2 + hour // 24:02d} {hour % 24:02d}:{minute:02d}:{second_value + 1:02d}"
        trades.append(trade(f"p{index}", opened, "2026-03-04 00:00:00", -1, direction="buy", volume=1.0))
        peer_trades.append(trade(f"q{index}", peer_opened, "2026-03-04 00:00:00", 1, direction="sell", volume=1.0))

    started = perf_counter()
    result = detect_bonus_arbitrage(profile(), events, trades, [{"account": "900001", "trades": peer_trades}])
    elapsed = perf_counter() - started

    match = result["evidence"]["cycles"][0]["peerMatch"]
    assert match["matches"] == 10_000
    assert match["lotCoverage"] == 1.0
    assert elapsed < 3.0


def test_peer_matching_large_history_can_be_cancelled() -> None:
    events = [
        event("d1", "2026-03-02 08:00:00", "deposit", 1000),
        event("c1", "2026-03-02 08:00:01", "bonus_grant", 1000),
    ]
    trades = [
        trade(f"p{index}", "2026-03-02 09:00:00", "2026-03-02 10:00:00", -1)
        for index in range(1_000)
    ]
    peer_trades = [
        trade(f"q{index}", "2026-03-02 09:00:01", "2026-03-02 10:00:00", 1, direction="sell")
        for index in range(1_000)
    ]
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(BonusAnalysisCancelled):
        detect_bonus_arbitrage(
            profile(), events, trades, [{"account": "900001", "trades": peer_trades}], cancelled=cancelled,
        )


class _FakeBridge:
    def module(self):
        return object()


def test_repository_keeps_current_mt4_and_mt5_positions_for_preventive_scoring() -> None:
    repository = LegacyBonusArbitrageRepository(_FakeBridge())

    mt5 = repository._mt5_trades([{
        "Deal": 1,
        "PositionID": 1001,
        "Entry": 0,
        "Action": 0,
        "Time": "2026-07-22 08:00:00",
        "TimeMsc": "2026-07-22 08:00:00",
        "Symbol": "XAUUSD",
        "Price": 3350,
        "ContractSize": 100,
        "VolumeExt": 100000000,
        "Profit": 0,
        "Commission": -1,
        "Storage": 0,
        "Fee": 0,
    }], 0.01)
    mt4 = repository._mt4_trades([{
        "TICKET": 2001,
        "CMD": 1,
        "SYMBOL": "XAUUSD",
        "VOLUME": 50,
        "OPEN_TIME": "2026-07-22 08:00:00",
        "OPEN_PRICE": 3350,
        "CLOSE_TIME": "1970-01-01 00:00:00",
        "CLOSE_PRICE": 0,
        "PROFIT": -5,
        "COMMISSION": -1,
        "SWAPS": 0,
        "TAXES": 0,
    }], 0.01)

    assert mt5[0]["isOpen"] is True
    assert mt5[0]["closeTime"] == ""
    assert mt5[0]["remainingVolume"] == 1.0
    assert mt5[0]["openPrice"] == 3350
    assert mt5[0]["contractSize"] == 100
    assert mt5[0]["netProfit"] == -0.01
    assert mt4[0]["isOpen"] is True
    assert mt4[0]["closeTime"] == ""
    assert mt4[0]["remainingVolume"] == 0.5
    assert mt4[0]["openPrice"] == 3350
    assert mt4[0]["netProfit"] == -0.06


class _CountingBonusRepository(LegacyBonusArbitrageRepository):
    def __init__(self) -> None:
        super().__init__(_FakeBridge())
        self.raw_calls = 0
        self.peer_calls = 0
        self.calls_lock = Lock()

    def _raw_rows(self, source, login, start, end):
        with self.calls_lock:
            self.raw_calls += 1
        sleep(0.03)
        row_time = datetime(2026, 6, 1)
        return ([{"Deal": login, "Time": row_time}], [{"PositionID": login, "Time": row_time}])

    def _peer_family_mappings(self, source, user_id):
        with self.calls_lock:
            self.peer_calls += 1
        return [{"mt_login": login, "user_id": user_id} for login in range(1, 22)]


def test_repository_reuses_account_history_across_parallel_deep_checks() -> None:
    repository = _CountingBonusRepository()
    source = {
        "host": "db", "schema": "trading", "table": "mt5_deals", "kind": "mt5_deals",
        "account_route": {"schema": "crm", "mt_server_code": "2"},
    }
    start = datetime(2026, 1, 1)
    end = datetime(2026, 7, 20)

    with ThreadPoolExecutor(max_workers=6) as executor:
        rows = list(executor.map(
            lambda _: repository._cached_raw_rows(source, 3066283, start, end),
            range(6),
        ))

    assert repository.raw_calls == 1
    assert all(value is rows[0] for value in rows)


def test_repository_reuses_peer_family_and_preserves_exclusion_limit() -> None:
    repository = _CountingBonusRepository()
    source = {
        "host": "db", "schema": "trading", "table": "mt5_deals", "kind": "mt5_deals",
        "account_route": {"schema": "crm", "mt_server_code": "2"},
    }
    mapping = {"user_id": 88}

    first = repository._peer_mappings(source, mapping, 1)
    second = repository._peer_mappings(source, mapping, 2)

    assert repository.peer_calls == 1
    assert len(first) == len(second) == 20
    assert all(row["mt_login"] != 1 for row in first)
    assert all(row["mt_login"] != 2 for row in second)


class _HintedRouteRepository(LegacyBonusArbitrageRepository):
    def __init__(self) -> None:
        super().__init__(_FakeBridge())
        self.source_lookups = 0
        self.source = {
            "host": "db", "schema": "trading", "table": "mt5_deals", "kind": "mt5_deals",
            "platform": "MT5", "server": "DBG GB MT5",
            "account_route": {"schema": "crm_vn", "mt_server_code": "2"},
        }

    def _source_for_mapping(self, crm_schema, mapping):
        assert crm_schema == "crm_vn"
        return self.source

    def _sources(self, login, filters):
        self.source_lookups += 1
        raise AssertionError("candidate mapping should bypass account route lookup")

    def _profile(self, source, mapping, login):
        return {
            "account": str(login), "platform": "MT5", "server": "DBG GB MT5",
            "currency": "USD", "moneyScale": 1, "registration": "2026-07-01 00:00:00",
        }

    def _peer_mappings(self, source, mapping, login):
        return []

    def _raw_rows(self, source, login, start, end):
        return [], []


def test_candidate_mapping_bypasses_redundant_deep_route_lookup() -> None:
    repository = _HintedRouteRepository()

    context = repository.load_account_context("3066283", {
        "platform": "MT5",
        "server": "DBG GB MT5",
        "_candidateMapping": {
            "crmSchema": "crm_vn", "serverCode": "2", "user_id": 88,
            "mt_login": "3066283", "mt_server_code": "2", "status": "",
            "mt_type_name": "USD", "create_time": "2026-07-01 00:00:00",
        },
    })

    assert context["profile"]["account"] == "3066283"
    assert repository.source_lookups == 0


def test_repeated_extraction_cycles_raise_profile_score() -> None:
    events = []
    trades = []
    for day in (1, 8):
        prefix = f"2026-04-{day:02d}"
        events.extend([
            event(f"d{day}", f"{prefix} 08:00:00", "deposit", 100),
            event(f"c{day}", f"{prefix} 08:00:01", "bonus_grant", 20),
            event(f"w{day}", f"{prefix} 12:00:00", "withdrawal", -180),
            event(f"r{day}", f"{prefix} 12:00:01", "bonus_remove", -20),
        ])
        trades.append(trade(f"p{day}", f"{prefix} 09:00:00", f"{prefix} 11:00:00", 80, volume=0.2))

    result = detect_bonus_arbitrage(profile(), events, trades)

    assert result["score"] >= 85
    assert result["evidence"]["cycles"][0]["bonusRatioEligible"] is True
    assert any("2 个重复套利资金周期" in rule for rule in result["triggeredRules"])


def test_locked_profit_without_cashout_is_warning_not_high_risk() -> None:
    events = [
        event("d1", "2026-05-01 08:00:00", "deposit", 1000),
        event("c1", "2026-05-01 08:00:01", "bonus_grant", 1000),
        event("r1", "2026-05-12 08:00:00", "bonus_remove", -1000),
    ]
    trades = [
        trade(f"p{index}", f"2026-05-{index + 1:02d} 09:00:00", f"2026-05-{index + 1:02d} 10:00:00", 100, volume=0.4)
        for index in range(7)
    ]

    result = detect_bonus_arbitrage(profile(), events, trades)

    assert result["score"] == 60
    assert result["level"] == "预警"
    assert result["evidence"]["cycles"][0]["profitLocked"] is True
