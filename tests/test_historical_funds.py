from __future__ import annotations

from kdesk.domain.historical_funds import build_historical_funds


def test_replays_mt4_cash_credit_and_trade_events_after_daily_anchor() -> None:
    payload = build_historical_funds(
        platform="MT4",
        currency="USD",
        anchors=[
            {"timestamp": "2026-01-01 00:00:00", "balance": 1000, "credit": 200, "equity": 1200},
        ],
        events=[
            {"id": "1", "timestamp": "2026-01-01 10:00:00", "CMD": 7, "PROFIT": -50, "COMMENT": "BONUS-REMOVE"},
            {"id": "2", "timestamp": "2026-01-01 10:00:01", "CMD": 6, "PROFIT": -300, "COMMENT": "RST-negative balance"},
            {"id": "3", "timestamp": "2026-01-01 10:00:02", "CMD": 0, "OPEN_TIME": "2026-01-01 09:00:00", "CLOSE_TIME": "2026-01-01 10:00:02", "PROFIT": -100, "COMMISSION": -2, "SWAPS": 1, "TAXES": 0, "COMMENT": ""},
        ],
    )

    assert payload["summary"]["eventCount"] == 3
    rows = payload["events"]
    assert [row["kind"] for row in rows] == ["bonus_remove", "negative_balance_clear", "trade_close"]
    assert rows[0]["balance"] == 1000
    assert rows[0]["credit"] == 150
    assert rows[1]["balance"] == 700
    assert rows[2]["balance"] == 599
    assert rows[2]["realizedPnl"] == -101


def test_classifies_external_cash_and_internal_transfer_separately() -> None:
    payload = build_historical_funds(
        platform="MT4",
        currency="USD",
        anchors=[{"timestamp": "2026-01-01 00:00:00", "balance": 0, "credit": 0, "equity": 0}],
        events=[
            {"id": "1", "timestamp": "2026-01-01 01:00:00", "CMD": 6, "PROFIT": 1000, "COMMENT": "DEP-EO-1"},
            {"id": "2", "timestamp": "2026-01-01 02:00:00", "CMD": 6, "PROFIT": -400, "COMMENT": "TRS-AC-1#TO123"},
            {"id": "3", "timestamp": "2026-01-01 03:00:00", "CMD": 6, "PROFIT": -200, "COMMENT": "WDR-EO-2"},
        ],
    )

    summary = payload["summary"]
    assert summary["externalDeposit"] == 1000
    assert summary["externalWithdrawal"] == 200
    assert summary["internalTransfer"] == -400
    assert summary["externalNetDeposit"] == 800


def test_mt5_deal_and_credit_actions_are_replayed_in_sequence() -> None:
    payload = build_historical_funds(
        platform="MT5",
        currency="USD",
        anchors=[{"timestamp": "2026-01-01 00:00:00", "balance": 0, "credit": 0, "equity": 0}],
        events=[
            {"id": "10", "timestamp": "2026-01-01 01:00:00", "Action": 2, "Profit": 500, "Comment": "DEP-EO-1"},
            {"id": "11", "timestamp": "2026-01-01 01:00:01", "Action": 3, "Profit": 100, "Comment": "BONUS"},
            {"id": "12", "timestamp": "2026-01-01 01:00:02", "Action": 1, "Entry": 1, "Profit": -80, "Commission": -2, "Storage": 1, "Fee": 0, "Comment": ""},
        ],
    )

    rows = payload["events"]
    assert [row["kind"] for row in rows] == ["deposit", "bonus_grant", "trade_close"]
    assert rows[-1]["balance"] == 419
    assert rows[-1]["credit"] == 100
    assert rows[-1]["realizedPnl"] == -81


def test_mt4_closed_order_uses_close_time_and_internal_routes_do_not_become_cashflow() -> None:
    payload = build_historical_funds(
        platform="MT4",
        currency="USD",
        anchors=[{"timestamp": "2026-01-01 00:00:00", "balance": 1000, "credit": 0, "equity": 1000}],
        events=[
            {
                "TICKET": 10,
                "CMD": 0,
                "OPEN_TIME": "2026-01-01 08:00:00",
                "CLOSE_TIME": "2026-01-01 10:00:00",
                "PROFIT": -250,
                "COMMENT": "so: forced close",
            },
            {"TICKET": 11, "CMD": 6, "OPEN_TIME": "2026-01-01 10:01:00", "PROFIT": 250, "COMMENT": "RST-20260101"},
            {"TICKET": 12, "CMD": 6, "OPEN_TIME": "2026-01-01 11:00:00", "PROFIT": 500, "COMMENT": "CRM-T-FROM-123"},
        ],
    )

    rows = payload["events"]
    assert [row["timestamp"] for row in rows] == [
        "2026-01-01 10:00:00",
        "2026-01-01 10:01:00",
        "2026-01-01 11:00:00",
    ]
    assert [row["kind"] for row in rows] == ["trade_close", "negative_balance_clear", "internal_transfer"]
    assert rows[0]["balance"] == 750
    assert rows[1]["balance"] == 1000
    assert rows[2]["balance"] == 1500
    assert payload["summary"]["externalNetDeposit"] == 0
    assert payload["summary"]["internalTransfer"] == 500


def test_events_before_first_daily_anchor_are_retained_without_invented_balance_or_equity() -> None:
    payload = build_historical_funds(
        platform="MT4",
        currency="USD",
        anchors=[{"timestamp": "2026-01-02 00:00:00", "balance": 500, "credit": 0, "equity": 500}],
        events=[
            {"TICKET": 1, "CMD": 6, "OPEN_TIME": "2026-01-01 12:00:00", "PROFIT": 500, "COMMENT": "DEP-EO-1"},
            {"TICKET": 2, "CMD": 6, "OPEN_TIME": "2026-01-02 01:00:00", "PROFIT": -100, "COMMENT": "WDR-EO-1"},
        ],
    )

    before_anchor, after_anchor = payload["events"]
    assert before_anchor["balance"] is None
    assert before_anchor["equity"] is None
    assert before_anchor["equityStatus"] == "before_first_anchor"
    assert after_anchor["balance"] == 400
    assert after_anchor["equity"] is None
    assert after_anchor["equityStatus"] == "missing_intraday_snapshot"


def test_reconstructs_balance_and_credit_from_current_anchor_when_daily_view_is_unavailable() -> None:
    payload = build_historical_funds(
        platform="MT5",
        currency="USD",
        anchors=[],
        current_anchor={
            "timestamp": "2026-01-02 00:00:00",
            "balance": 0,
            "credit": 0,
            "equity": 0,
        },
        events=[
            {"id": "1", "timestamp": "2026-01-01 01:00:00", "Action": 2, "Profit": 100, "Comment": "DEP-EO-1"},
            {"id": "2", "timestamp": "2026-01-01 02:00:00", "Action": 2, "Profit": -100, "Comment": "WDR-EO-1"},
            {"id": "3", "timestamp": "2026-01-01 03:00:00", "Action": 3, "Profit": 50, "Comment": "BONUS"},
            {"id": "4", "timestamp": "2026-01-01 04:00:00", "Action": 3, "Profit": -50, "Comment": "Credit cancelled"},
        ],
    )

    rows = payload["events"]
    assert [row["balance"] for row in rows] == [100, 0, 0, 0]
    assert [row["credit"] for row in rows] == [0, 0, 50, 0]
    assert all(row["equity"] is None for row in rows)
    assert payload["summary"]["reconstructionMode"] == "current_account_anchor"
    assert payload["summary"]["equityCoverage"] == "current_anchor_only"
    assert payload["curve"][-1]["equityStatus"] == "authoritative_current"


def test_marks_only_platform_stop_out_and_negative_balance_clear_as_liquidation_points() -> None:
    payload = build_historical_funds(
        platform="MT4",
        currency="USD",
        anchors=[{"timestamp": "2026-01-01 00:00:00", "balance": 1000, "credit": 0, "equity": 1000}],
        events=[
            {
                "TICKET": 10,
                "CMD": 0,
                "REASON": 3,
                "OPEN_TIME": "2026-01-01 09:00:00",
                "CLOSE_TIME": "2026-01-01 10:00:00",
                "PROFIT": -200,
                "COMMENT": "regular stop loss",
            },
            {
                "TICKET": 11,
                "CMD": 1,
                "REASON": 5,
                "OPEN_TIME": "2026-01-01 09:30:00",
                "CLOSE_TIME": "2026-01-01 10:00:01",
                "PROFIT": -800,
                "COMMENT": "",
            },
            {
                "TICKET": 12,
                "CMD": 6,
                "OPEN_TIME": "2026-01-01 10:00:02",
                "PROFIT": 35,
                "COMMENT": "RST-negative balance",
            },
        ],
    )

    assert payload["summary"]["liquidationCount"] == 2
    assert [point["type"] for point in payload["liquidationPoints"]] == [
        "platform_stop_out",
        "negative_balance_clear",
    ]
    assert [point["eventIndex"] for point in payload["liquidationPoints"]] == [1, 2]
    assert payload["events"][0]["liquidation"] is None
    assert payload["events"][1]["liquidation"]["label"] == "平台强平"
    assert payload["events"][2]["liquidation"]["label"] == "负余额清零"


def test_marks_mt5_stop_out_reason_but_not_an_ordinary_loss() -> None:
    payload = build_historical_funds(
        platform="MT5",
        currency="USD",
        current_anchor={"timestamp": "2026-01-02 00:00:00", "balance": 0, "credit": 0, "equity": 0},
        events=[
            {"Deal": 1, "Time": "2026-01-01 10:00:00", "Action": 0, "Entry": 1, "Reason": 0, "Profit": -20},
            {"Deal": 2, "Time": "2026-01-01 10:00:01", "Action": 1, "Entry": 1, "Reason": 6, "Profit": -80},
        ],
    )

    assert payload["summary"]["liquidationCount"] == 1
    assert payload["liquidationPoints"][0]["orderId"] == "2"
    assert payload["events"][1]["liquidation"]["source"] == "MT5 Reason=6"
