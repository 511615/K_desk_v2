from __future__ import annotations

import copy
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta

ENVIRONMENTS = ("gb", "cn", "dbg_cn", "dbg_vn")


def number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    for pattern, size in (("%Y-%m-%d %H:%M:%S.%f", 26), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:size], pattern)
        except ValueError:
            continue
    return None


def normalize_scan_options(payload: dict | None, *, now: datetime | None = None) -> dict:
    payload = payload or {}
    now = now or datetime.now()
    end = parse_datetime(payload.get("end")) or now
    start = parse_datetime(payload.get("start")) or end - timedelta(days=7)
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    if end - start > timedelta(days=31):
        raise ValueError("刷返佣扫描时间不能超过31天")
    requested = payload.get("environments") or list(ENVIRONMENTS)
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    environments = []
    for value in requested:
        key = str(value or "").strip().lower()
        if key not in ENVIRONMENTS:
            raise ValueError(f"未知环境：{value}")
        if key not in environments:
            environments.append(key)
    if not environments:
        raise ValueError("请至少选择一个环境")
    return {
        "start": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end.strftime("%Y-%m-%d %H:%M:%S"),
        "environments": environments,
    }


def ramp(value: object, low: float, high: float, maximum: float) -> float:
    value = number(value)
    if high <= low:
        return maximum if value >= high and high > 0 else 0.0
    return max(0.0, min(maximum, (value - low) / (high - low) * maximum))


def percentile(values: Iterable[object], quantile: float) -> float:
    ordered = sorted(number(value) for value in values if number(value) >= 0)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def coefficient_of_variation(values: Iterable[object]) -> float | None:
    clean = [number(value) for value in values if number(value) > 0]
    if len(clean) < 2:
        return None
    mean = statistics.fmean(clean)
    return statistics.pstdev(clean) / mean if mean else None


def cohort_thresholds(rows: list[dict]) -> dict:
    return {
        "ordersPerDayP95": max(percentile((row.get("ordersPerActiveDay") for row in rows), 0.95), 100.0),
        "ordersPerDayP99": max(percentile((row.get("ordersPerActiveDay") for row in rows), 0.99), 500.0),
        "ordersP95": max(percentile((row.get("orders") for row in rows), 0.95), 1000.0),
        "ordersP99": max(percentile((row.get("orders") for row in rows), 0.99), 5000.0),
        "lotsDepositP95": max(percentile((row.get("lotsPerDeposit") for row in rows), 0.95), 10.0),
        "lotsDepositP99": max(percentile((row.get("lotsPerDeposit") for row in rows), 0.99), 100.0),
        "rebatePerLotP95": percentile((row.get("rebatePerLot") for row in rows), 0.95),
        "rebateP95": percentile((row.get("currentIbRebate") for row in rows), 0.95),
    }


def candidate_accounts(proxies: list[dict]) -> tuple[set[tuple[str, int]], dict[tuple[str, str], dict]]:
    by_cohort: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in proxies:
        by_cohort[(str(row.get("serverCode") or ""), "USC" if row.get("isCent") else "USD")].append(row)
    thresholds = {key: cohort_thresholds(rows) for key, rows in by_cohort.items()}
    candidate_baselines = {
        key: {
            "ordersPerDayP95": percentile((row.get("ordersPerActiveDay") for row in rows), 0.95),
            "ordersP95": percentile((row.get("orders") for row in rows), 0.95),
            "rebatePerLotP95": percentile((row.get("rebatePerLot") for row in rows), 0.95),
            "rebateP95": percentile((row.get("currentIbRebate") for row in rows), 0.95),
        }
        for key, rows in by_cohort.items()
    }
    repeated_across_customers: set[tuple[str, int]] = set()
    signatures: dict[tuple, list[dict]] = defaultdict(list)
    for row in proxies:
        for signature in row.get("signatures") or []:
            signatures[tuple(signature)].append(row)
    for rows in signatures.values():
        if len({integer(row.get("userId")) for row in rows if integer(row.get("userId"))}) >= 2:
            repeated_across_customers.update((str(row.get("serverCode") or ""), integer(row.get("account"))) for row in rows)
    selected = set()
    for row in proxies:
        key = (str(row.get("serverCode") or ""), integer(row.get("account")))
        baseline = candidate_baselines[(key[0], "USC" if row.get("isCent") else "USD")]
        if (
            number(row.get("short10Coverage")) >= 0.30
            or number(row.get("rebatePerLot")) >= number(baseline.get("rebatePerLotP95")) > 0
            or number(row.get("orders")) >= number(baseline.get("ordersP95")) > 0
            or number(row.get("ordersPerActiveDay")) >= number(baseline.get("ordersPerDayP95")) > 0
            or (integer(row.get("orders")) >= 2 and max(number(row.get("fixedLotCoverage")), number(row.get("repeatCoverage"))) >= 0.8)
            or key in repeated_across_customers
            or (
                number(row.get("currentIbRebate")) >= number(baseline.get("rebateP95")) > 0
                and integer(row.get("orders")) <= 2
            )
        ):
            selected.add(key)
    return selected, thresholds


def _trade_time(row: dict, field: str) -> datetime | None:
    return parse_datetime(row.get(f"{field}_time_msc") or row.get(f"{field}_time"))


def _trade_volume(row: dict) -> float:
    return max(number(row.get("volume")), 0.0)


def _trade_profit(row: dict) -> float:
    return sum(number(row.get(key)) for key in ("profit", "commission", "swap", "fee", "taxes"))


def cross_account_pair_features(accounts: list[dict]) -> dict:
    trades = []
    total_volume = 0.0
    for account in accounts:
        account_id = integer(account.get("account"))
        user_id = integer(account.get("userId"))
        for trade in account.get("_trades") or []:
            volume = _trade_volume(trade)
            opened, closed = _trade_time(trade, "open"), _trade_time(trade, "close")
            direction = str(trade.get("type") or "").lower()
            symbol = str(trade.get("symbol") or "").upper()
            if volume <= 0 or not opened or not closed or direction not in {"buy", "sell"} or not symbol:
                continue
            total_volume += volume
            trades.append({
                "account": account_id,
                "user": user_id,
                "trade": trade,
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "open": opened,
                "close": closed,
            })
    buckets: dict[tuple[str, int, int], list[tuple[int, dict]]] = defaultdict(list)
    for index, row in enumerate(trades):
        buckets[(row["symbol"], int(row["open"].timestamp()), int(row["close"].timestamp()))].append((index, row))
    used: set[int] = set()
    pairs = []
    for index, left in enumerate(trades):
        if index in used:
            continue
        best = None
        for open_second in range(int(left["open"].timestamp()) - 2, int(left["open"].timestamp()) + 3):
            for close_second in range(int(left["close"].timestamp()) - 2, int(left["close"].timestamp()) + 3):
                for right_index, right in buckets.get((left["symbol"], open_second, close_second), []):
                    if right_index == index or right_index in used:
                        continue
                    if left["account"] == right["account"] or not left["user"] or left["user"] == right["user"]:
                        continue
                    if left["direction"] == right["direction"]:
                        continue
                    lot_error = abs(left["volume"] - right["volume"]) / max(left["volume"], right["volume"])
                    if lot_error > 0.05:
                        continue
                    distance = abs((left["open"] - right["open"]).total_seconds()) + abs((left["close"] - right["close"]).total_seconds()) + lot_error
                    if best is None or distance < best[0]:
                        best = (distance, right_index, right)
        if best is None:
            continue
        _, right_index, right = best
        used.update((index, right_index))
        pairs.append((left, right))
    matched_volume = sum(left["volume"] + right["volume"] for left, right in pairs)
    loss_volume = sum(
        left["volume"] + right["volume"]
        for left, right in pairs
        if _trade_profit(left["trade"]) < 0 and _trade_profit(right["trade"]) < 0
    )
    losses_per_lot = [
        (max(-_trade_profit(left["trade"]), 0) + max(-_trade_profit(right["trade"]), 0))
        / max(left["volume"] + right["volume"], 1e-9)
        for left, right in pairs
    ]
    short_volume = sum(
        left["volume"] + right["volume"]
        for left, right in pairs
        if (left["close"] - left["open"]).total_seconds() <= 10 and (right["close"] - right["open"]).total_seconds() <= 10
    )
    cv = coefficient_of_variation(losses_per_lot)
    coverage = matched_volume / total_volume if total_volume else 0.0
    sync_coverage = coverage
    both_loss_coverage = loss_volume / total_volume if total_volume else 0.0
    short_coverage = short_volume / total_volume if total_volume else 0.0
    stable_points = 8.0 if cv is not None and cv <= 0.10 else ramp(0.35 - (cv or 0.35), 0, 0.25, 8)
    path = min(
        ramp(coverage, 0.5, 0.9, 15)
        + ramp(sync_coverage, 0.2, 0.9, 10)
        + ramp(short_coverage, 0.3, 0.9, 7)
        + ramp(both_loss_coverage, 0.2, 0.9, 10)
        + stable_points,
        50.0,
    )
    return {
        "path": round(path, 1),
        "pairCount": len(pairs),
        "pairCoverage": round(coverage, 4),
        "sameSecondCoverage": round(sync_coverage, 4),
        "bothLossCoverage": round(both_loss_coverage, 4),
        "short10Coverage": round(short_coverage, 4),
        "customerCount": len({row["user"] for pair in pairs for row in pair}),
        "accountCount": len({row["account"] for pair in pairs for row in pair}),
        "accounts": sorted({row["account"] for pair in pairs for row in pair}),
        "lossPerLotCv": round(cv, 4) if cv is not None else None,
    }


def _percentile_points(value: float, p95: float, p99: float, maximum: float) -> float:
    if p99 <= p95:
        return maximum if value >= p99 and p99 > 0 else 0.0
    return ramp(value, p95, p99, maximum)


def _account_paths(account: dict, thresholds: dict, stable_loss_points: float) -> tuple[float, float, list[str]]:
    if integer(account.get("orders")) <= 0:
        return 0.0, 0.0, []
    pair_path = min(
        ramp(account.get("pairCoverage"), 0.5, 0.9, 15)
        + ramp(account.get("sameSecondCoverage"), 0.2, 0.9, 10)
        + ramp(account.get("short10Coverage"), 0.3, 0.9, 7)
        + ramp(account.get("bothLossCoverage"), 0.2, 0.9, 10)
        + stable_loss_points,
        50.0,
    )
    turnover = (
        _percentile_points(number(account.get("ordersPerActiveDay")), number(thresholds.get("ordersPerDayP95")), number(thresholds.get("ordersPerDayP99")), 15)
        + _percentile_points(number(account.get("orders")), number(thresholds.get("ordersP95")), number(thresholds.get("ordersP99")), 10)
        + _percentile_points(number(account.get("lotsPerDeposit")), number(thresholds.get("lotsDepositP95")), number(thresholds.get("lotsDepositP99")), 8)
        + max(ramp(account.get("short10Coverage"), 0.25, 0.8, 5), ramp(account.get("repeatCoverage"), 0.3, 0.8, 5))
        + max(ramp(account.get("eaCoverage"), 0.5, 0.9, 5), ramp(account.get("fixedLotCoverage"), 0.5, 0.9, 5))
    )
    profit, lots = number(account.get("tradeProfit")), max(number(account.get("lots")), 1e-9)
    turnover += 7 if profit <= 0 and abs(profit) / lots <= 500 else 4 if profit <= 0 else 3 if profit / lots <= 1 else 0
    tags = []
    if number(account.get("pairCoverage")) >= 0.9:
        tags.append("反向配对覆盖高")
    if number(account.get("sameSecondCoverage")) >= 0.8:
        tags.append("同秒等手数对锁")
    if number(account.get("bothLossCoverage")) >= 0.8:
        tags.append("配对双腿亏损")
    if number(account.get("eaCoverage")) >= 0.8:
        tags.append("EA执行占比高")
    return pair_path, min(turnover, 50.0), tags


def risk_level(score: float) -> str:
    return "严重" if score >= 90 else "高危" if score >= 75 else "预警" if score >= 60 else "低风险"


def score_ib(accounts: list[dict], *, ib_id: object, environment: str, thresholds: dict | None = None) -> dict:
    accounts = [copy.deepcopy(row) for row in accounts]
    for row in accounts:
        row["lotsPerDeposit"] = number(row.get("lots")) / max(number(row.get("externalNetDeposit")), 1.0)
    thresholds = thresholds or cohort_thresholds(accounts)
    loss_values = [row.get("pairedLossPerLot") for row in accounts if number(row.get("sameSecondCoverage")) >= 0.5]
    loss_cv = coefficient_of_variation(loss_values)
    stable_points = 8.0 if loss_cv is not None and loss_cv <= 0.10 else ramp(0.35 - (loss_cv or 0.35), 0, 0.25, 8)
    strongest_pair = strongest_turnover = 0.0
    evidence: list[str] = []
    for row in accounts:
        pair_path, turnover_path, tags = _account_paths(row, row.get("cohortThresholds") or thresholds, stable_points)
        row["pairedLossPath"], row["highTurnoverPath"] = round(pair_path, 1), round(turnover_path, 1)
        row["riskContribution"] = round(max(pair_path, turnover_path), 1)
        row["evidenceTags"] = list(dict.fromkeys([*(row.get("evidenceTags") or []), *tags]))
        strongest_pair, strongest_turnover = max(strongest_pair, pair_path), max(strongest_turnover, turnover_path)
    cross = cross_account_pair_features(accounts)
    structure = max(strongest_pair, strongest_turnover, number(cross.get("path")))
    suspicious = [
        row for row in accounts
        if number(row.get("riskContribution")) >= 30
        or (number(row.get("riskContribution")) >= 20 and number(row.get("currentIbRebate")) >= max(number(row.get("lots")), 1))
    ]
    if number(cross.get("path")) >= 30:
        paired_accounts = {integer(value) for value in cross.get("accounts") or []}
        suspicious.extend(row for row in accounts if integer(row.get("account")) in paired_accounts and row not in suspicious)
        evidence.append("跨客户账户同秒反向配对")
    orders = sum(integer(row.get("orders")) for row in accounts)
    lots = sum(number(row.get("lots")) for row in accounts)
    trade_profit = sum(number(row.get("tradeProfit")) for row in accounts)
    current_rebate = sum(number(row.get("currentIbRebate")) for row in accounts)
    hierarchy_rebate = sum(number(row.get("hierarchyRebate")) for row in accounts)
    rebate_rows = sum(integer(row.get("currentIbRebateRows")) for row in accounts)
    matched_orders = sum(integer(row.get("matchedRebateOrders")) for row in accounts)
    rebate_coverage = min(matched_orders / orders, 1.0) if orders else 0.0
    client_loss = sum(max(-number(row.get("tradeProfit")), 0.0) for row in accounts)
    deposit = sum(max(number(row.get("externalNetDeposit")), 0.0) for row in accounts)
    economics = ramp(rebate_coverage, 0.2, 0.8, 5) + ramp(current_rebate / client_loss if client_loss else 0, 0.2, 0.6, 10)
    economics += 6 if current_rebate > 0 and deposit <= 0 else ramp(current_rebate / deposit if deposit else 0, 0.1, 1.0, 6)
    per_lot = [number(row.get("currentIbRebate")) / number(row.get("lots")) for row in accounts if number(row.get("currentIbRebate")) > 0 and number(row.get("lots")) > 0]
    rebate_cv = coefficient_of_variation(per_lot)
    economics += 2 if len(per_lot) == 1 else ramp(0.35 - (rebate_cv or 0.35), 0, 0.25, 4)
    if current_rebate > 0 and trade_profit <= 0:
        economics += 5 if trade_profit + current_rebate >= 0 else ramp(current_rebate / max(-trade_profit, 1), 0.1, 0.6, 5)
    economics = min(economics, 30.0)
    suspicious_users = {integer(row.get("userId")) for row in suspicious if integer(row.get("userId"))}
    coordination = ramp(len(suspicious_users), 2, 5, 5)
    suspicious_lots = sum(number(row.get("lots")) for row in suspicious)
    suspicious_rebate = sum(number(row.get("currentIbRebate")) for row in suspicious)
    contribution = max(suspicious_lots / lots if lots else 0, suspicious_rebate / current_rebate if current_rebate else 0)
    coordination += ramp(contribution, 0.2, 0.6, 4)
    coordination += ramp(cross.get("accountCount"), 2, 5, 4)
    zero_ratio = sum(1 for row in suspicious if number(row.get("externalNetDeposit")) <= 0) / len(suspicious) if suspicious else 0
    positive = [max(number(row.get("externalNetDeposit")), 0) for row in suspicious]
    concentration = max(positive, default=0) / sum(positive) if sum(positive) else (1.0 if suspicious else 0.0)
    coordination += 2 if len(suspicious) >= 2 and zero_ratio >= 0.6 and concentration >= 0.7 else 0
    coordination = min(coordination, 15.0)
    funding = 2 if any(row.get("depositToTradeHours") is not None and 0 <= number(row.get("depositToTradeHours")) <= 6 for row in suspicious) else 0
    funding += 2 if any(row.get("tradeToWithdrawalHours") is not None and 0 <= number(row.get("tradeToWithdrawalHours")) <= 24 for row in suspicious) else 0
    funding += 1 if any(any(number(row.get(key)) != 0 for key in ("internalTransfer", "negativeBalanceClear", "compensation")) for row in suspicious) else 0
    counter = 0.0
    counter_tags = []
    if trade_profit > max(current_rebate, 1) and strongest_pair < 20 and coordination < 5:
        counter += 8
        counter_tags.append("独立交易利润高于返佣")
    if current_rebate > 0 and trade_profit > 0 and current_rebate < trade_profit * 0.1 and rebate_coverage < 0.2:
        counter += 5
        counter_tags.append("返佣金额及订单覆盖低")
    medians = [number(row.get("medianHoldingSeconds")) for row in accounts if row.get("medianHoldingSeconds") is not None]
    symbols = {symbol for row in accounts for symbol in row.get("symbols") or []}
    if len(symbols) >= 4 and medians and statistics.median(medians) >= 3600 and strongest_turnover < 25:
        counter += 4
        counter_tags.append("多品种长期低周转策略")
    if structure < 20 and coordination < 3:
        counter += 3
        counter_tags.append("无重复可疑结构")
    score = max(0.0, min(100.0, structure + economics + coordination + funding - min(counter, 20)))
    extreme_ea = any(integer(row.get("orders")) >= 1000 and max(number(row.get("eaCoverage")), number(row.get("fixedLotCoverage"))) >= 0.8 for row in accounts)
    economic_turnover = orders >= 1000 and rebate_coverage >= 0.8 and current_rebate >= max(abs(trade_profit) * 0.5, 100)
    if extreme_ea and not economic_turnover and coordination < 8:
        score = min(max(score, 60), 74)
        evidence.append("高频EA仅作预警，等待返佣经济证据")
    if current_rebate > 0:
        evidence.append("当前IB存在实收返佣")
    if len(suspicious_users) >= 2:
        evidence.append("多个客户贡献同类结构")
    clean_accounts = []
    for row in accounts:
        row.pop("_trades", None)
        clean_accounts.append(row)
    sample = sum(integer(row.get("orders")) for row in suspicious)
    return {
        "ibId": integer(ib_id) or str(ib_id), "environment": environment,
        "score": round(score, 1), "level": risk_level(score), "stage": "返佣确认",
        "confidence": "高" if sample >= 20 and len(suspicious) >= 2 else "中" if sample >= 5 else "低",
        "components": {"structure": round(structure, 1), "pairedLossPath": round(strongest_pair, 1), "highTurnoverPath": round(strongest_turnover, 1), "crossAccountPath": cross["path"], "rebateEconomics": round(economics, 1), "ibCoordination": round(coordination, 1), "fundingCycle": round(funding, 1), "counterevidence": round(min(counter, 20), 1)},
        "summary": {"accounts": len(accounts), "suspiciousAccounts": len(suspicious), "customers": len({integer(row.get("userId")) for row in accounts if integer(row.get("userId"))}), "suspiciousCustomers": len(suspicious_users), "orders": orders, "lots": round(lots, 4), "tradeProfit": round(trade_profit, 2), "currentIbRebate": round(current_rebate, 2), "hierarchyRebate": round(hierarchy_rebate, 2), "rebateRows": rebate_rows, "rebateOrderCoverage": round(rebate_coverage, 4), "rebateLossCoverage": round(current_rebate / client_loss, 4) if client_loss else None, "externalNetDeposit": round(deposit, 2), "zeroDepositRatio": round(zero_ratio, 4), "depositConcentration": round(concentration, 4)},
        "crossAccount": cross, "evidenceTags": list(dict.fromkeys(evidence)), "counterevidenceTags": counter_tags,
        "accounts": clean_accounts,
    }
