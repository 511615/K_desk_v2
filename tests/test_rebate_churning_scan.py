from __future__ import annotations

from datetime import datetime

import pytest

from kdesk.application.rebate_churning_scan import RebateChurningScanService, _batches
from kdesk.domain.rebate_churning import (
    candidate_accounts,
    cross_account_pair_features,
    normalize_scan_options,
    score_ib,
)


def trade(account: int, user: int, direction: str, *, profit: float = -10, second: int = 0) -> tuple[dict, dict]:
    account_row = {"account": account, "userId": user}
    trade_row = {
        "account": account, "symbol": "XAUUSD", "type": direction, "volume": 20,
        "open_time": f"2026-07-01 10:00:{second:02d}", "close_time": f"2026-07-01 10:00:{second + 1:02d}",
        "profit": profit, "commission": 0, "swap": 0,
    }
    return account_row, trade_row


def test_scan_options_default_to_all_environments_and_seven_days() -> None:
    options = normalize_scan_options({}, now=datetime(2026, 7, 20, 12, 0, 0))
    assert options == {
        "start": "2026-07-13 12:00:00", "end": "2026-07-20 12:00:00",
        "environments": ["gb", "cn", "dbg_cn", "dbg_vn"],
    }
    with pytest.raises(ValueError, match="31天"):
        normalize_scan_options({"start": "2026-06-01", "end": "2026-07-20"})


def test_cross_account_pairing_requires_different_customers() -> None:
    left_account, left = trade(1001, 501, "buy")
    right_account, right = trade(1002, 502, "sell")
    features = cross_account_pair_features([{**left_account, "_trades": [left]}, {**right_account, "_trades": [right]}])
    assert features["pairCount"] == 1
    assert features["pairCoverage"] == 1
    assert features["customerCount"] == 2

    same_customer = cross_account_pair_features([
        {**left_account, "_trades": [left]},
        {**right_account, "userId": 501, "_trades": [right]},
    ])
    assert same_customer["pairCount"] == 0


def test_single_small_rebate_is_not_promoted_by_rebate_presence() -> None:
    result = score_ib([{
        "account": 630830, "userId": 10, "orders": 1, "lots": 0.01, "tradeProfit": 0,
        "currentIbRebate": 0.45, "currentIbRebateRows": 1, "matchedRebateOrders": 1,
        "externalNetDeposit": 100, "pairCoverage": 0, "sameSecondCoverage": 0,
        "bothLossCoverage": 0, "short10Coverage": 0, "fixedLotCoverage": 1,
        "repeatCoverage": 0, "eaCoverage": 0, "symbols": ["XAUUSD"], "_trades": [],
    }], ib_id=1, environment="cn", thresholds={
        "ordersPerDayP95": 100, "ordersPerDayP99": 500, "ordersP95": 1000,
        "ordersP99": 5000, "lotsDepositP95": 10, "lotsDepositP99": 100,
    })
    assert result["score"] < 60
    assert result["summary"]["suspiciousAccounts"] == 0


def test_candidate_selection_has_no_top_n_cutoff() -> None:
    proxies = [{
        "serverCode": "1", "account": index, "userId": index, "orders": 2,
        "ordersPerActiveDay": 2, "lots": 40, "currentIbRebate": 20,
        "rebatePerLot": 0.5, "short10Coverage": 1, "fixedLotCoverage": 1,
        "repeatCoverage": 1, "signatures": [], "isCent": False,
    } for index in range(1, 401)]
    selected, _ = candidate_accounts(proxies)
    assert len(selected) == 400


def test_ib_batches_are_memory_bounded_without_truncation() -> None:
    batches = list(_batches(range(121), size=50))
    assert [len(batch) for batch in batches] == [50, 50, 21]
    assert [value for batch in batches for value in batch] == list(range(121))


class FakeRepository:
    def discover_active_ibs(self, environment, start, end):
        if environment == "cn":
            raise RuntimeError("timeout")
        return {9}

    def load_rebate_rows(self, environment, ib_ids, start, end):
        return [{"rebate_ib_id": 9, "mt_server_code": "1", "trade_mt_login": 1001}]

    def proxy_accounts(self, environment, rows):
        return [{"ibId": 9, "serverCode": "1", "account": 1001, "userId": 11, "orders": 1, "lots": 0.01, "currentIbRebate": 0.45, "short10Coverage": 0, "fixedLotCoverage": 1, "repeatCoverage": 0, "isCent": False}]

    def load_deep_accounts(self, environment, ib_id, keys, rows, start, end):
        return [{"account": 1001, "serverCode": "1", "userId": 11, "orders": 1, "lots": 0.01, "currentIbRebate": 0.45, "currentIbRebateRows": 1, "matchedRebateOrders": 1, "tradeProfit": 0, "externalNetDeposit": 100, "_trades": []}]

    def ib_names(self, environment, ib_ids):
        return {9: {"full_name": "Test IB"}}

    def ib_display_name(self, row):
        return row.get("full_name", "")


def test_scan_keeps_successes_when_one_environment_fails() -> None:
    events = []
    result = RebateChurningScanService(FakeRepository()).run(
        {"start": "2026-07-13", "end": "2026-07-20", "environments": ["gb", "cn"]},
        progress=lambda percent, message: events.append((percent, message)), cancelled=lambda: False,
    )
    assert result["summary"]["activeIbs"] == 1
    assert result["partialFailure"] is True
    assert result["failureTotal"] == 1
    assert result["allResults"][0]["ibId"] == 9
    assert result["allResults"][0]["score"] < 60
