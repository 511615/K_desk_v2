from __future__ import annotations

from typing import Any

STATUS_ORDER = {"B": 0, "M": 1, "P": 2, "T": 3, "A": 4, "TA": 5}
STATUS_INCLUDE_MINIMUM = STATUS_ORDER["P"]


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_database_status(value: object) -> str:
    status = str(value or "").strip().upper()
    return status if status in STATUS_ORDER else "B"


def _linear_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def rebate_candidate_floor(
    members: list[dict[str, Any]],
    *,
    absolute_floor: float = 20.0,
    percentile: float = 0.75,
    minimum_rows: int = 3,
) -> float:
    meaningful = [
        _number(row.get("rebateAmount"))
        for row in members
        if int(_number(row.get("rebateOrderCount"))) >= minimum_rows
        and _number(row.get("rebateAmount")) > 0
    ]
    return max(float(absolute_floor), _linear_percentile(meaningful, percentile))


def select_ib_rebate_anomalies(
    members: list[dict[str, Any]],
    *,
    absolute_rebate_floor: float = 20.0,
    cohort_percentile: float = 0.75,
    minimum_rebate_rows: int = 3,
    minimum_rebate_share: float = 0.70,
    maximum_trade_to_rebate: float = 0.30,
) -> dict[str, Any]:
    """Select only investigation-worthy direct IB members.

    Monetary inputs must already use one comparable display currency.  The selector
    is deliberately independent from SQL and graph rendering so its business rules
    can be audited and changed without altering data access or UI code.
    """

    rebate_floor = rebate_candidate_floor(
        members,
        absolute_floor=absolute_rebate_floor,
        percentile=cohort_percentile,
        minimum_rows=minimum_rebate_rows,
    )
    selected: list[dict[str, Any]] = []
    highest_status = "B"

    for source in members:
        row = dict(source)
        status = normalize_database_status(row.get("databaseStatus"))
        rebate = _number(row.get("rebateAmount"))
        trade_profit = _number(row.get("tradeProfit"))
        combined_profit = trade_profit + rebate
        rebate_rows = int(_number(row.get("rebateOrderCount")))
        rebate_share = rebate / combined_profit if combined_profit > 0 else 0.0
        status_selected = STATUS_ORDER[status] >= STATUS_INCLUDE_MINIMUM
        rebate_selected = (
            rebate_rows >= minimum_rebate_rows
            and rebate >= rebate_floor
            and combined_profit > 0
            and rebate_share >= minimum_rebate_share
            and trade_profit <= rebate * maximum_trade_to_rebate
        )
        if not status_selected and not rebate_selected:
            continue

        reasons: list[str] = []
        if status_selected:
            reasons.append(f"数据库状态 {status}")
        if rebate_selected:
            reasons.append("返佣主导盈利")
        row.update({
            "databaseStatus": status,
            "rebateAmount": round(rebate, 5),
            "tradeProfit": round(trade_profit, 5),
            "combinedProfit": round(combined_profit, 5),
            "rebateShare": rebate_share,
            "rebateDominated": rebate_selected,
            "inclusionReasons": reasons,
        })
        selected.append(row)
        if STATUS_ORDER[status] > STATUS_ORDER[highest_status]:
            highest_status = status

    selected.sort(
        key=lambda row: (
            -STATUS_ORDER[normalize_database_status(row.get("databaseStatus"))],
            -int(bool(row.get("rebateDominated"))),
            -_number(row.get("rebateAmount")),
            str(row.get("account") or ""),
        )
    )
    return {
        "totalAccounts": len(members),
        "abnormalAccounts": len(selected),
        "highestStatus": highest_status,
        "rebateFloor": rebate_floor,
        "accounts": selected,
    }
