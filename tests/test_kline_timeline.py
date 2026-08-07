from __future__ import annotations

from kdesk.domain.kline_timeline import build_kline_timeline


def test_kline_timeline_keeps_a_known_opening_cash_credit_state_and_interleaves_events() -> None:
    replay = {
        "summary": {"currency": "USD", "moneyScale": 1.0, "eventCount": 5},
        "events": [
            {
                "eventIndex": 0,
                "id": "cash-1",
                "timestamp": "2026-01-01 09:00:00",
                "kind": "deposit",
                "balance": 1000.0,
                "credit": 0.0,
                "deltaBalance": 1000.0,
                "deltaCredit": 0.0,
            },
            {
                "eventIndex": 1,
                "id": "open-1",
                "timestamp": "2026-01-01 09:30:00",
                "kind": "trade_open",
                "balance": 1000.0,
                "credit": 0.0,
                "deltaBalance": 0.0,
                "deltaCredit": 0.0,
                "orderId": "101",
            },
            {
                "eventIndex": 2,
                "id": "credit-1",
                "timestamp": "2026-01-01 09:45:00",
                "kind": "bonus_grant",
                "balance": 1000.0,
                "credit": 100.0,
                "deltaBalance": 0.0,
                "deltaCredit": 100.0,
            },
            {
                "eventIndex": 3,
                "id": "close-1",
                "timestamp": "2026-01-01 10:00:00",
                "kind": "trade_close",
                "balance": 875.0,
                "credit": 100.0,
                "deltaBalance": -125.0,
                "deltaCredit": 0.0,
                "orderId": "101",
            },
            {
                "eventIndex": 4,
                "id": "clear-1",
                "timestamp": "2026-01-01 10:15:00",
                "kind": "negative_balance_clear",
                "balance": 0.0,
                "credit": 0.0,
                "deltaBalance": 25.0,
                "deltaCredit": 0.0,
                "liquidation": {"label": "负余额清零"},
            },
        ],
        "curve": [
            {"timestamp": "2026-01-01 09:00:00", "balance": 1000.0, "credit": 0.0},
            {"timestamp": "2026-01-01 09:45:00", "balance": 1000.0, "credit": 100.0},
            {"timestamp": "2026-01-01 10:00:00", "balance": 875.0, "credit": 100.0},
            {"timestamp": "2026-01-01 10:15:00", "balance": 0.0, "credit": 0.0},
        ],
        "liquidationPoints": [{"eventIndex": 4, "id": "clear-1", "timestamp": "2026-01-01 10:15:00"}],
    }

    timeline = build_kline_timeline(replay, start="2026-01-01 09:30:00", end="2026-01-01 10:00:00")

    assert timeline["version"] == 1
    assert timeline["openingState"] == {
        "timestamp": "2026-01-01 09:00:00",
        "balance": 1000.0,
        "credit": 0.0,
        "known": True,
    }
    assert [item["kind"] for item in timeline["events"]] == ["trade_open", "bonus_grant", "trade_close"]
    assert [item["category"] for item in timeline["events"]] == ["order", "funds", "order"]
    assert timeline["curve"][-1]["balance"] == 875.0
    assert timeline["summary"]["liquidationCount"] == 0


def test_kline_timeline_keeps_unknown_pre_anchor_state_unknown_instead_of_using_defaults() -> None:
    replay = {
        "summary": {"currency": "USD", "moneyScale": 1.0, "eventCount": 1},
        "events": [
            {
                "eventIndex": 0,
                "id": "open-1",
                "timestamp": "2026-01-01 09:30:00",
                "kind": "trade_open",
                "balance": None,
                "credit": None,
                "deltaBalance": 0.0,
                "deltaCredit": 0.0,
            }
        ],
        "curve": [],
        "liquidationPoints": [],
    }

    timeline = build_kline_timeline(replay, start="2026-01-01 09:00:00", end="2026-01-01 10:00:00")

    assert timeline["openingState"]["known"] is False
    assert timeline["openingState"]["balance"] is None
    assert timeline["events"][0]["balance"] is None
    assert timeline["summary"]["knownStateEventCount"] == 0
