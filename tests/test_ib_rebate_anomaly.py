from kdesk.domain.ib_rebate_anomaly import select_ib_rebate_anomalies


def test_selects_rebate_dominated_profitable_account() -> None:
    result = select_ib_rebate_anomalies([
        {
            "account": "1001", "databaseStatus": "B", "rebateAmount": 100,
            "rebateOrderCount": 8, "tradeProfit": 10,
        },
    ])

    assert result["totalAccounts"] == 1
    assert result["abnormalAccounts"] == 1
    assert result["highestStatus"] == "B"
    assert result["accounts"][0]["rebateDominated"] is True
    assert result["accounts"][0]["combinedProfit"] == 110
    assert result["accounts"][0]["rebateShare"] == 100 / 110
    assert result["accounts"][0]["inclusionReasons"] == ["返佣主导盈利"]


def test_excludes_low_rebate_and_trade_dominated_accounts() -> None:
    result = select_ib_rebate_anomalies([
        {
            "account": "1001", "databaseStatus": "B", "rebateAmount": 10,
            "rebateOrderCount": 8, "tradeProfit": 1,
        },
        {
            "account": "1002", "databaseStatus": "M", "rebateAmount": 100,
            "rebateOrderCount": 8, "tradeProfit": 80,
        },
    ])

    assert result["totalAccounts"] == 2
    assert result["abnormalAccounts"] == 0
    assert result["accounts"] == []


def test_status_p_or_higher_bypasses_rebate_rules() -> None:
    result = select_ib_rebate_anomalies([
        {
            "account": "1001", "databaseStatus": "P", "rebateAmount": 0,
            "rebateOrderCount": 0, "tradeProfit": -500,
        },
        {
            "account": "1002", "databaseStatus": "TA", "rebateAmount": 1,
            "rebateOrderCount": 1, "tradeProfit": -1,
        },
        {
            "account": "1003", "databaseStatus": "M", "rebateAmount": 0,
            "rebateOrderCount": 0, "tradeProfit": 0,
        },
    ])

    assert [row["account"] for row in result["accounts"]] == ["1002", "1001"]
    assert result["accounts"][0]["inclusionReasons"] == ["数据库状态 TA"]
    assert result["highestStatus"] == "TA"


def test_combines_status_and_rebate_reasons_without_duplicate_account() -> None:
    result = select_ib_rebate_anomalies([
        {
            "account": "1001", "databaseStatus": "A", "rebateAmount": 200,
            "rebateOrderCount": 20, "tradeProfit": -20,
        },
    ])

    assert result["abnormalAccounts"] == 1
    assert result["accounts"][0]["inclusionReasons"] == ["数据库状态 A", "返佣主导盈利"]


def test_uses_cohort_percentile_to_ignore_ordinary_rebate_levels() -> None:
    result = select_ib_rebate_anomalies([
        {"account": "1001", "databaseStatus": "B", "rebateAmount": 30, "rebateOrderCount": 6, "tradeProfit": 0},
        {"account": "1002", "databaseStatus": "B", "rebateAmount": 40, "rebateOrderCount": 6, "tradeProfit": 0},
        {"account": "1003", "databaseStatus": "B", "rebateAmount": 50, "rebateOrderCount": 6, "tradeProfit": 0},
        {"account": "1004", "databaseStatus": "B", "rebateAmount": 200, "rebateOrderCount": 6, "tradeProfit": 0},
    ])

    assert result["rebateFloor"] > 50
    assert [row["account"] for row in result["accounts"]] == ["1004"]

