from kdesk.domain.account_position_replay import build_account_position_replay


def test_account_position_replay_keeps_all_products_and_sweeps_chart_times_once():
    replay = build_account_position_replay(
        [
            {
                "Ticket": "EUR-1",
                "Item": "EURUSD",
                "Type": "buy",
                "Volume": 0.10,
                "Open Time": "2026-08-20 10:00:00",
                "Close Time": "2026-08-20 10:03:00",
                "Open Price": 1.1000,
            },
            {
                "Ticket": "GOLD-1",
                "Item": "XAUUSD",
                "Type": "sell",
                "Volume": 0.20,
                "Open Time": "2026-08-20 10:01:00",
                "Close Time": "2026-08-20 10:04:00",
                "Open Price": 2400.0,
            },
            {
                "Ticket": "OLD",
                "Item": "US30Roll",
                "Type": "buy",
                "Volume": 1.0,
                "Open Time": "2026-08-01 10:00:00",
                "Close Time": "2026-08-01 10:10:00",
                "Open Price": 53000.0,
            },
        ],
        start="2026-08-20 10:00:00",
        end="2026-08-20 10:05:00",
        chart_times_by_symbol={"EURUSD": ["2026-08-20 10:00:00", "2026-08-20 10:01:00", "2026-08-20 10:03:00"]},
    )

    assert replay["coverage"] == {
        "scope": "all_products_in_chart_window",
        "sourceTradeCount": 3,
        "includedTradeCount": 2,
        "symbolCount": 2,
        "start": "2026-08-20 10:00:00",
        "end": "2026-08-20 10:05:00",
    }
    assert replay["fields"] == [
        "openTime", "closeTime", "ticket", "symbol", "type", "volume", "openPrice", "isOpen",
        "contractSize", "profitRate", "marginRate",
    ]
    assert replay["rows"] == [
        ["2026-08-20 10:00:00", "2026-08-20 10:03:00", "EUR-1", "EURUSD", "buy", 0.1, 1.1, False, 0.0, 0.0, 0.0],
        ["2026-08-20 10:01:00", "2026-08-20 10:04:00", "GOLD-1", "XAUUSD", "sell", 0.2, 2400.0, False, 0.0, 0.0, 0.0],
    ]
    assert replay["seriesBySymbol"]["EURUSD"] == [
        ["2026-08-20 10:00:00", 1, 0.1],
        ["2026-08-20 10:01:00", 2, 0.3],
        ["2026-08-20 10:03:00", 1, 0.2],
    ]


def test_account_position_replay_keeps_execution_contract_and_conversion_inputs_for_valuation():
    replay = build_account_position_replay(
        [
            {
                "Ticket": "GOLD-1",
                "Item": "XAUUSD",
                "Type": "sell",
                "Volume": 0.04,
                "Open Time": "2026-08-20 10:00:00",
                "Close Time": "2026-08-20 10:03:00",
                "Open Price": 4589.26,
                "Contract Size": 100,
                "Profit Rate": 1,
                "Margin Rate": 1,
            }
        ],
        start="2026-08-20 10:00:00",
        end="2026-08-20 10:05:00",
        chart_times_by_symbol={"XAUUSD": ["2026-08-20 10:00:00"]},
    )

    assert replay["fields"][-3:] == ["contractSize", "profitRate", "marginRate"]
    assert replay["rows"] == [[
        "2026-08-20 10:00:00", "2026-08-20 10:03:00", "GOLD-1", "XAUUSD", "sell", 0.04,
        4589.26, False, 100.0, 1.0, 1.0,
    ]]
