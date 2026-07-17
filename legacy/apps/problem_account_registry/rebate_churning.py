from __future__ import annotations

import copy
import math
import re
import statistics
import threading
import uuid
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from typing import Callable, Iterable


MAX_RANGE_DAYS = 366
MAX_ACCOUNT_RANGE_DAYS = 2200
MAX_USERS = 2500
MAX_ACCOUNTS = 5000
DETAIL_BATCH_SIZE = 25
SCAN_ENVIRONMENTS = {
    "gb": {"label": "AC GB", "crm_schema": "int_sass_crm_ac"},
    "cn": {"label": "AC CN", "crm_schema": "sass_crm_ac"},
    "dbg_cn": {"label": "DBG CN", "crm_schema": "crm_cn"},
    "dbg_vn": {"label": "DBG VN", "crm_schema": "crm_vn"},
}
ACCOUNT_HISTORY_STARTS = {
    "gb": "2023-10-04 00:00:00",
    "cn": "2023-03-27 00:00:00",
    "dbg_cn": "2021-06-02 00:00:00",
    "dbg_vn": "2021-11-19 00:00:00",
}
CENT_RE = re.compile(r"(?i)(?:\bcent\b|\busc\b|\.cent\b)")
TARGET_COHORT_THRESHOLDS = {
    "ordersPerDayP95": 100.0,
    "ordersPerDayP99": 500.0,
    "ordersP95": 1000.0,
    "ordersP99": 5000.0,
    "lotsDepositP95": 10.0,
    "lotsDepositP99": 100.0,
}


class AmbiguousAccountError(ValueError):
    def __init__(self, message: str, candidates: list[dict]):
        super().__init__(message)
        self.candidates = candidates


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _round(value: object, digits: int = 2) -> float:
    return round(_number(value), digits)


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _text(value).replace("T", " ")
    if not text:
        return None
    for fmt, size in (("%Y-%m-%d %H:%M:%S.%f", 26), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def _datetime_text(value: object) -> str:
    parsed = _datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else _text(value)


def _batches(values: Iterable, size: int = DETAIL_BATCH_SIZE):
    batch = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def ramp(value: object, low: float, high: float, maximum: float) -> float:
    value = _number(value)
    if high <= low:
        return maximum if value >= high else 0.0
    return max(0.0, min(maximum, (value - low) / (high - low) * maximum))


def percentile(values: Iterable[object], quantile: float) -> float:
    ordered = sorted(_number(value) for value in values if _number(value) >= 0)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def coefficient_of_variation(values: Iterable[object]) -> float | None:
    clean = [_number(value) for value in values if _number(value) > 0]
    if len(clean) < 2:
        return None
    mean = statistics.fmean(clean)
    return statistics.pstdev(clean) / mean if mean else None


def parse_period(
    start: object = "",
    end: object = "",
    *,
    now: datetime | None = None,
    max_range_days: int = MAX_RANGE_DAYS,
) -> dict:
    now = now or datetime.now()
    end_dt = _datetime(end) if _text(end) else now
    start_dt = _datetime(start) if _text(start) else end_dt - timedelta(days=7)
    if not start_dt or not end_dt:
        raise ValueError("日期格式无效")
    if end_dt <= start_dt:
        raise ValueError("结束时间必须晚于开始时间")
    if end_dt - start_dt > timedelta(days=max_range_days):
        raise ValueError(f"扫描时间不能超过{max_range_days}天")
    return {
        "start": start_dt,
        "end": end_dt,
        "startText": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "endText": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def parse_scan_options(payload: dict | None, *, now: datetime | None = None) -> dict:
    payload = payload or {}
    period = parse_period(payload.get("start"), payload.get("end"), now=now)
    raw_environments = payload.get("environments") or ["gb", "cn"]
    if isinstance(raw_environments, str):
        raw_environments = [item.strip() for item in raw_environments.split(",") if item.strip()]
    environments = []
    for value in raw_environments:
        key = _text(value).lower()
        if key not in SCAN_ENVIRONMENTS:
            raise ValueError(f"未知环境：{value}")
        if key not in environments:
            environments.append(key)
    if not environments:
        raise ValueError("请至少选择一个环境")
    return {**period, "environments": environments}


def _trade_net_profit(row: dict) -> float:
    return sum(_number(row.get(key)) for key in ("profit", "commission", "swap", "fee", "taxes"))


def _trade_time(row: dict, field: str) -> datetime | None:
    return _datetime(row.get(f"{field}_time_msc") or row.get(f"{field}_time"))


def _trade_volume(row: dict) -> float:
    return max(_number(row.get("volume")), 0.0)


def _pair_features(trades: list[dict]) -> dict:
    total_volume = sum(_trade_volume(row) for row in trades)
    directional = defaultdict(lambda: [0.0, 0.0])
    by_symbol = defaultdict(list)
    for index, row in enumerate(trades):
        symbol = _text(row.get("symbol")).upper()
        direction = 0 if _text(row.get("type")).lower() == "buy" else 1
        directional[symbol][direction] += _trade_volume(row)
        by_symbol[symbol].append((index, row))
    broad_matched_volume = sum(2 * min(volumes) for volumes in directional.values())

    exact_pairs = []
    for symbol_rows in by_symbol.values():
        buys = [(index, row) for index, row in symbol_rows if _text(row.get("type")).lower() == "buy"]
        sells = [(index, row) for index, row in symbol_rows if _text(row.get("type")).lower() == "sell"]
        # Index the larger side by second-level open/close buckets. A trade can
        # only match one of 25 neighboring time buckets, avoiding O(n^2) on EA accounts.
        left_rows, right_rows = (buys, sells) if len(buys) <= len(sells) else (sells, buys)
        buckets = defaultdict(lambda: defaultdict(deque))
        for right_index, right in right_rows:
            right_open = _trade_time(right, "open")
            right_close = _trade_time(right, "close")
            if not right_open or not right_close:
                continue
            bucket = (int(right_open.timestamp()), int(right_close.timestamp()))
            buckets[bucket][round(_trade_volume(right), 6)].append((right_index, right))
        for _, left in left_rows:
            left_open = _trade_time(left, "open")
            left_close = _trade_time(left, "close")
            if not left_open or not left_close:
                continue
            left_volume = _trade_volume(left)
            best = None
            for open_second in range(int(left_open.timestamp()) - 2, int(left_open.timestamp()) + 3):
                for close_second in range(int(left_close.timestamp()) - 2, int(left_close.timestamp()) + 3):
                    volume_buckets = buckets.get((open_second, close_second))
                    if not volume_buckets:
                        continue
                    for right_volume, queue in volume_buckets.items():
                        if not queue:
                            continue
                        lot_error = abs(left_volume - right_volume) / max(left_volume, right_volume, 1e-9)
                        if lot_error > 0.05:
                            continue
                        distance = abs(open_second - left_open.timestamp()) + abs(close_second - left_close.timestamp()) + lot_error
                        if best is None or distance < best[0]:
                            best = (distance, queue)
            if best is None:
                continue
            _, queue = best
            _, right = queue.popleft()
            exact_pairs.append((left, right, _trade_volume(left) + _trade_volume(right)))

    exact_volume = sum(pair[2] for pair in exact_pairs)
    both_loss_volume = sum(
        pair[2] for pair in exact_pairs if _trade_net_profit(pair[0]) < 0 and _trade_net_profit(pair[1]) < 0
    )
    paired_loss = sum(max(-_trade_net_profit(row), 0.0) for pair in exact_pairs for row in pair[:2])
    paired_lots = sum(_trade_volume(row) for pair in exact_pairs for row in pair[:2])
    return {
        "pairCoverage": broad_matched_volume / total_volume if total_volume else 0.0,
        "sameSecondCoverage": exact_volume / total_volume if total_volume else 0.0,
        "bothLossCoverage": both_loss_volume / total_volume if total_volume else 0.0,
        "pairCount": len(exact_pairs),
        "pairedLossPerLot": paired_loss / paired_lots if paired_lots else 0.0,
    }


def account_features(trades: list[dict], *, active_days: object = 0) -> dict:
    trades = [row for row in trades if _trade_volume(row) > 0]
    total_volume = sum(_trade_volume(row) for row in trades)
    net_profit = sum(_trade_net_profit(row) for row in trades)
    holding = []
    short_volume = 0.0
    ea_volume = 0.0
    lot_counts = Counter()
    signatures = Counter()
    symbols = Counter()
    dates = set()
    for row in trades:
        volume = _trade_volume(row)
        open_dt = _trade_time(row, "open")
        close_dt = _trade_time(row, "close")
        seconds = _number(row.get("holding_seconds"), -1)
        if seconds < 0 and open_dt and close_dt:
            seconds = max((close_dt - open_dt).total_seconds(), 0.0)
        if seconds >= 0:
            holding.append(seconds)
            if seconds <= 10:
                short_volume += volume
        reason = _text(row.get("reason")).lower()
        comment = _text(row.get("comment"))
        expert = _text(row.get("expert_id"))
        if reason == "expert" or expert not in {"", "0"} or re.search(r"(?i)(\bEA\b|expert|robot|copy|signal)", comment):
            ea_volume += volume
        lot_counts[round(volume, 4)] += 1
        signatures[(_text(row.get("symbol")).upper(), _text(row.get("type")).lower(), round(volume, 4), round(seconds, 0))] += 1
        symbols[_text(row.get("symbol")).upper()] += 1
        if open_dt:
            dates.add(open_dt.date())
    order_count = len(trades)
    fixed_count = max(lot_counts.values(), default=0)
    repeat_count = sum(count for count in signatures.values() if count >= 2)
    pairs = _pair_features(trades)
    days = max(_integer(active_days), len(dates), 1 if order_count else 0)
    first_trade = min((_trade_time(row, "open") for row in trades if _trade_time(row, "open")), default=None)
    last_trade = max((_trade_time(row, "close") or _trade_time(row, "open") for row in trades if _trade_time(row, "close") or _trade_time(row, "open")), default=None)
    return {
        "orders": order_count,
        "lots": _round(total_volume, 4),
        "tradeProfit": _round(net_profit),
        "activeDays": days,
        "ordersPerActiveDay": _round(order_count / days, 2) if days else 0.0,
        "short10Coverage": short_volume / total_volume if total_volume else 0.0,
        "eaCoverage": ea_volume / total_volume if total_volume else 0.0,
        "fixedLotCoverage": fixed_count / order_count if order_count else 0.0,
        "repeatCoverage": repeat_count / order_count if order_count else 0.0,
        "medianHoldingSeconds": statistics.median(holding) if holding else None,
        "symbols": sorted(symbol for symbol in symbols if symbol),
        "firstTrade": _datetime_text(first_trade),
        "lastTrade": _datetime_text(last_trade),
        "tradeKeys": sorted({_text(row.get("id")) for row in trades if _text(row.get("id"))}),
        "ticketKeys": sorted({_text(row.get("ticket")) for row in trades if _text(row.get("ticket"))}),
        **pairs,
    }


def cohort_thresholds(rows: list[dict]) -> dict:
    return {
        "ordersPerDayP95": percentile((row.get("ordersPerActiveDay") for row in rows), 0.95),
        "ordersPerDayP99": percentile((row.get("ordersPerActiveDay") for row in rows), 0.99),
        "ordersP95": percentile((row.get("orders") for row in rows), 0.95),
        "ordersP99": percentile((row.get("orders") for row in rows), 0.99),
        "lotsDepositP95": percentile((row.get("lotsPerDeposit") for row in rows), 0.95),
        "lotsDepositP99": percentile((row.get("lotsPerDeposit") for row in rows), 0.99),
    }


def _percentile_points(value: float, p95: float, p99: float, maximum: float) -> float:
    if p99 <= p95:
        return maximum if value >= p99 and p99 > 0 else 0.0
    return ramp(value, p95, p99, maximum)


def _account_paths(account: dict, thresholds: dict, stable_loss_points: float) -> tuple[float, float, list[str]]:
    if _integer(account.get("orders")) <= 0:
        return 0.0, 0.0, []
    pair_path = (
        ramp(account.get("pairCoverage"), 0.5, 0.9, 15)
        + ramp(account.get("sameSecondCoverage"), 0.2, 0.9, 10)
        + ramp(account.get("short10Coverage"), 0.3, 0.9, 7)
        + ramp(account.get("bothLossCoverage"), 0.2, 0.9, 10)
        + stable_loss_points
    )
    turnover_path = (
        _percentile_points(_number(account.get("ordersPerActiveDay")), _number(thresholds.get("ordersPerDayP95")), _number(thresholds.get("ordersPerDayP99")), 15)
        + _percentile_points(_number(account.get("orders")), _number(thresholds.get("ordersP95")), _number(thresholds.get("ordersP99")), 10)
        + _percentile_points(_number(account.get("lotsPerDeposit")), _number(thresholds.get("lotsDepositP95")), _number(thresholds.get("lotsDepositP99")), 8)
        + max(ramp(account.get("short10Coverage"), 0.25, 0.8, 5), ramp(account.get("repeatCoverage"), 0.3, 0.8, 5))
        + max(ramp(account.get("eaCoverage"), 0.5, 0.9, 5), ramp(account.get("fixedLotCoverage"), 0.5, 0.9, 5))
    )
    profit = _number(account.get("tradeProfit"))
    lots = max(_number(account.get("lots")), 1e-9)
    if profit <= 0:
        turnover_path += 7 if abs(profit) / lots <= 500 else 4
    elif profit / lots <= 1:
        turnover_path += 3
    tags = []
    if _number(account.get("pairCoverage")) >= 0.9:
        tags.append("反向配对覆盖高")
    if _number(account.get("sameSecondCoverage")) >= 0.8:
        tags.append("同秒等手数对锁")
    if _number(account.get("bothLossCoverage")) >= 0.8:
        tags.append("配对双腿亏损")
    if _number(account.get("ordersPerActiveDay")) >= _number(thresholds.get("ordersPerDayP99")) > 0:
        tags.append("周转强度P99")
    if _number(account.get("eaCoverage")) >= 0.8:
        tags.append("EA执行占比高")
    return min(pair_path, 50.0), min(turnover_path, 50.0), tags


def _risk_level(score: float) -> str:
    if score >= 90:
        return "严重"
    if score >= 75:
        return "高危"
    if score >= 60:
        return "预警"
    return "低风险"


def score_ib(accounts: list[dict], *, ib_id: object = "", environment: str = "", thresholds: dict | None = None) -> dict:
    accounts = [copy.deepcopy(account) for account in accounts]
    for account in accounts:
        account["lotsPerDeposit"] = _number(account.get("lots")) / max(_number(account.get("externalNetDeposit")), 1.0)
    thresholds = thresholds or cohort_thresholds(accounts)
    loss_per_lot = [
        row.get("pairedLossPerLot") for row in accounts
        if _number(row.get("pairedLossPerLot")) > 0 and _number(row.get("sameSecondCoverage")) >= 0.5
    ]
    loss_cv = coefficient_of_variation(loss_per_lot)
    stable_loss_points = 8.0 if loss_cv is not None and loss_cv <= 0.10 else ramp(0.35 - (loss_cv or 0.35), 0, 0.25, 8)

    strongest_pair = 0.0
    strongest_turnover = 0.0
    suspicious = []
    evidence = []
    for account in accounts:
        pair_path, turnover_path, tags = _account_paths(
            account, account.get("cohortThresholds") or thresholds, stable_loss_points
        )
        account["pairedLossPath"] = _round(pair_path, 1)
        account["highTurnoverPath"] = _round(turnover_path, 1)
        account["riskContribution"] = _round(max(pair_path, turnover_path), 1)
        account["evidenceTags"] = list(dict.fromkeys([*(account.get("evidenceTags") or []), *tags]))
        strongest_pair = max(strongest_pair, pair_path)
        strongest_turnover = max(strongest_turnover, turnover_path)
        if max(pair_path, turnover_path) >= 30 or _number(account.get("currentIbRebate")) > 0:
            suspicious.append(account)
            evidence.extend(tags)

    structure = max(strongest_pair, strongest_turnover)
    orders = sum(_integer(row.get("orders")) for row in accounts)
    lots = sum(_number(row.get("lots")) for row in accounts)
    trade_profit = sum(_number(row.get("tradeProfit")) for row in accounts)
    current_rebate = sum(_number(row.get("currentIbRebate")) for row in accounts)
    hierarchy_rebate = sum(_number(row.get("hierarchyRebate")) for row in accounts)
    rebate_rows = sum(_integer(row.get("currentIbRebateRows")) for row in accounts)
    matched_rebate_orders = sum(_integer(row.get("matchedRebateOrders")) for row in accounts)
    rebate_coverage = min(matched_rebate_orders / orders, 1.0) if orders else 0.0
    client_loss = sum(max(-_number(row.get("tradeProfit")), 0.0) for row in accounts)
    external_deposit = sum(max(_number(row.get("externalNetDeposit")), 0.0) for row in accounts)

    economics = ramp(rebate_coverage, 0.2, 0.8, 5)
    economics += ramp(current_rebate / client_loss if client_loss else 0.0, 0.2, 0.6, 10)
    if current_rebate > 0 and external_deposit <= 0:
        economics += 6
    else:
        economics += ramp(current_rebate / external_deposit if external_deposit else 0.0, 0.1, 1.0, 6)
    rebate_per_lot = [
        _number(row.get("currentIbRebate")) / _number(row.get("lots"))
        for row in accounts if _number(row.get("currentIbRebate")) > 0 and _number(row.get("lots")) > 0
    ]
    rebate_cv = coefficient_of_variation(rebate_per_lot)
    if len(rebate_per_lot) == 1:
        economics += 2
    elif rebate_cv is not None:
        economics += ramp(0.35 - rebate_cv, 0, 0.25, 4)
    if current_rebate > 0 and trade_profit <= 0:
        economics += 5 if trade_profit + current_rebate >= 0 else ramp(current_rebate / max(-trade_profit, 1), 0.1, 0.6, 5)
    economics = min(economics, 30.0)

    suspicious_users = {_integer(row.get("userId")) for row in suspicious if _integer(row.get("userId"))}
    coordination = ramp(len(suspicious_users), 2, 5, 5)
    suspicious_lots = sum(_number(row.get("lots")) for row in suspicious)
    suspicious_rebate = sum(_number(row.get("currentIbRebate")) for row in suspicious)
    contribution_share = max(suspicious_lots / lots if lots else 0.0, suspicious_rebate / current_rebate if current_rebate else 0.0)
    coordination += ramp(contribution_share, 0.2, 0.6, 4)
    paired_symbols = Counter(symbol for row in suspicious if _number(row.get("pairCoverage")) >= 0.5 for symbol in row.get("symbols", []))
    rotation_accounts = sum(1 for row in suspicious if any(paired_symbols[symbol] >= 2 for symbol in row.get("symbols", [])))
    coordination += ramp(rotation_accounts, 2, 5, 4)
    zero_deposit_ratio = sum(1 for row in suspicious if _number(row.get("externalNetDeposit")) <= 0) / len(suspicious) if suspicious else 0.0
    positive_deposits = [max(_number(row.get("externalNetDeposit")), 0.0) for row in suspicious]
    deposit_concentration = max(positive_deposits, default=0.0) / sum(positive_deposits) if sum(positive_deposits) else (1.0 if suspicious else 0.0)
    coordination += 2 if len(suspicious) >= 2 and zero_deposit_ratio >= 0.6 and deposit_concentration >= 0.7 else 0
    coordination = min(coordination, 15.0)

    funding = 0.0
    if any(row.get("depositToTradeHours") is not None and 0 <= _number(row.get("depositToTradeHours")) <= 6 for row in suspicious):
        funding += 2
    if any(row.get("tradeToWithdrawalHours") is not None and 0 <= _number(row.get("tradeToWithdrawalHours")) <= 24 for row in suspicious):
        funding += 2
    if any(_number(row.get("internalTransfer")) != 0 or _number(row.get("negativeBalanceClear")) != 0 or _number(row.get("compensation")) != 0 for row in suspicious):
        funding += 1

    counterevidence = 0.0
    counter_tags = []
    if trade_profit > max(current_rebate, 1.0) and strongest_pair < 20 and coordination < 5:
        counterevidence += 8
        counter_tags.append("独立交易利润高于返佣")
    if current_rebate > 0 and trade_profit > 0 and current_rebate < trade_profit * 0.1 and rebate_coverage < 0.2:
        counterevidence += 5
        counter_tags.append("返佣金额及订单覆盖低")
    median_holding = statistics.median([
        _number(row.get("medianHoldingSeconds")) for row in accounts if row.get("medianHoldingSeconds") is not None
    ]) if any(row.get("medianHoldingSeconds") is not None for row in accounts) else 0
    all_symbols = {symbol for row in accounts for symbol in row.get("symbols", [])}
    if len(all_symbols) >= 4 and median_holding >= 3600 and strongest_turnover < 25:
        counterevidence += 4
        counter_tags.append("多品种长期低周转策略")
    if structure < 20 and coordination < 3:
        counterevidence += 3
        counter_tags.append("无重复可疑结构")
    counterevidence = min(counterevidence, 20.0)

    raw_score = structure + economics + coordination + funding - counterevidence
    strong_pair_accounts = sum(
        1 for row in accounts
        if _number(row.get("pairCoverage")) >= 0.6
        and _number(row.get("sameSecondCoverage")) >= 0.6
        and _number(row.get("bothLossCoverage")) >= 0.6
    )
    repeated_funded_pair = strong_pair_accounts >= 2 and structure >= 40 and funding >= 4
    if repeated_funded_pair:
        raw_score = max(raw_score, 60)
        evidence.append("重复同秒双亏并伴随资金闭环")

    economic_turnover = (
        orders >= 1000
        and rebate_coverage >= 0.8
        and current_rebate >= max(abs(trade_profit) * 0.5, 100)
    )
    if economic_turnover:
        raw_score = max(raw_score, 75)
        evidence.append("高周转且返佣经济贡献超过交易盈亏一半")

    extreme_execution = any(
        _integer(row.get("orders")) >= 1000
        and max(_number(row.get("eaCoverage")), _number(row.get("fixedLotCoverage"))) >= 0.8
        and (
            _number(row.get("orders")) >= _number((row.get("cohortThresholds") or thresholds).get("ordersP99")) > 0
            or _number(row.get("ordersPerActiveDay")) >= _number((row.get("cohortThresholds") or thresholds).get("ordersPerDayP99")) > 0
        )
        for row in accounts
    )
    turnover_only_guard = extreme_execution and not economic_turnover and coordination < 8
    if turnover_only_guard:
        raw_score = min(max(raw_score, 60), 74)
        evidence.append("高频EA仅作预警，等待返佣经济证据")
    score = max(0.0, min(100.0, raw_score))
    if current_rebate > 0:
        evidence.append("当前IB存在实收返佣")
    if client_loss > 0 and current_rebate / client_loss >= 0.6:
        evidence.append("返佣覆盖客户亏损60%以上")
    if len(suspicious_users) >= 2:
        evidence.append("多个客户贡献同类结构")
    evidence = list(dict.fromkeys(evidence))
    total_sample = sum(_integer(row.get("orders")) for row in suspicious)
    confidence = "高" if total_sample >= 20 and len(suspicious) >= 2 else "中" if total_sample >= 5 else "低"
    return {
        "ibId": _integer(ib_id) or _text(ib_id),
        "environment": environment,
        "score": _round(score, 1),
        "level": _risk_level(score),
        "stage": "返佣确认" if current_rebate > 0 else "交易结构预警",
        "confidence": confidence,
        "components": {
            "structure": _round(structure, 1),
            "pairedLossPath": _round(strongest_pair, 1),
            "highTurnoverPath": _round(strongest_turnover, 1),
            "rebateEconomics": _round(economics, 1),
            "ibCoordination": _round(coordination, 1),
            "fundingCycle": _round(funding, 1),
            "counterevidence": _round(counterevidence, 1),
        },
        "summary": {
            "accounts": len(accounts),
            "suspiciousAccounts": len(suspicious),
            "customers": len({_integer(row.get("userId")) for row in accounts if _integer(row.get("userId"))}),
            "orders": orders,
            "lots": _round(lots, 4),
            "tradeProfit": _round(trade_profit),
            "currentIbRebate": _round(current_rebate),
            "hierarchyRebate": _round(hierarchy_rebate),
            "rebateRows": rebate_rows,
            "rebateOrderCoverage": _round(rebate_coverage, 4),
            "rebateLossCoverage": _round(current_rebate / client_loss, 4) if client_loss else None,
            "externalNetDeposit": _round(external_deposit),
            "zeroDepositRatio": _round(zero_deposit_ratio, 4),
            "depositConcentration": _round(deposit_concentration, 4),
            "lossPerLotCv": _round(loss_cv, 4) if loss_cv is not None else None,
            "rebatePerLotCv": _round(rebate_cv, 4) if rebate_cv is not None else None,
        },
        "evidenceTags": evidence,
        "counterevidenceTags": counter_tags,
        "accounts": accounts,
    }


def _full_name(row: dict) -> str:
    return _text(row.get("full_name")) or " ".join(
        value for value in (_text(row.get("first_name")), _text(row.get("middle_name")), _text(row.get("last_name"))) if value
    )


def _source_route_code(source: dict, crm_schema: str) -> str:
    if _text(source.get("crm_schema")) == crm_schema:
        direct = _text(source.get("mt_server_code"))
        if direct:
            return direct
    routes = source.get("crm_routes") or {}
    if isinstance(routes, dict):
        return _text(routes.get(crm_schema))
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, dict):
                continue
            if _text(route.get("schema") or route.get("crm_schema")) == crm_schema:
                return _text(route.get("mt_server_code") or route.get("server_code"))
    return ""


def _sources_for_crm(sources: list[dict], crm_schema: str) -> list[dict]:
    return [source for source in sources if _source_route_code(source, crm_schema)]


def _source_for(sources: list[dict], crm_schema: str, server_code: object) -> dict | None:
    code = _text(server_code)
    return next(
        (source for source in sources if _source_route_code(source, crm_schema) == code),
        None,
    )


def _money_scale(account: dict, rebate_rows: list[dict] | None = None) -> float:
    type_name = _text(account.get("mt_type_name"))
    rebate_currency = " ".join(_text(row.get("usd_or_usc")) for row in (rebate_rows or []))
    return 0.01 if CENT_RE.search(type_name) or "USC" in rebate_currency.upper() else 1.0


def _rebate_amount(row: dict) -> float:
    scale = 0.01 if "USC" in _text(row.get("usd_or_usc")).upper() else 1.0
    return _round(_number(row.get("rebate_amount")) * scale, 5)


def _mt5_rows_to_trades(rows: list[dict], scale_by_login: dict[int, float], source: dict) -> dict[int, list[dict]]:
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[_integer(row.get("Login"))][_integer(row.get("PositionID"))].append(row)
    result = defaultdict(list)
    for login, positions in grouped.items():
        scale = scale_by_login.get(login, 1.0)
        for position_id, deals in positions.items():
            if not position_id:
                continue
            deals.sort(key=lambda row: (_datetime(row.get("TimeMsc")) or datetime.min, _integer(row.get("Deal"))))
            opens = [row for row in deals if _integer(row.get("Entry"), -1) == 0 and _integer(row.get("Action"), -1) in (0, 1)]
            closes = [row for row in deals if _integer(row.get("Entry"), -1) in (1, 2, 3) and _integer(row.get("Action"), -1) in (0, 1)]
            if not opens or not closes:
                continue
            open_row = opens[0]
            for close_row in closes:
                volume_raw = close_row.get("VolumeClosed") or close_row.get("Volume") or open_row.get("Volume")
                result[login].append({
                    "id": _text(close_row.get("Deal")), "ticket": _text(position_id),
                    "platform": "MT5", "server": source.get("server"),
                    "type": "buy" if _integer(open_row.get("Action")) == 0 else "sell",
                    "symbol": _text(close_row.get("Symbol") or open_row.get("Symbol")),
                    "volume": _number(volume_raw) / 10000.0,
                    "open_time": _datetime_text(open_row.get("TimeMsc") or open_row.get("Time")),
                    "close_time": _datetime_text(close_row.get("TimeMsc") or close_row.get("Time")),
                    "profit": _number(close_row.get("Profit")) * scale,
                    "commission": (_number(open_row.get("Commission")) + _number(close_row.get("Commission"))) * scale,
                    "swap": (_number(open_row.get("Storage")) + _number(close_row.get("Storage"))) * scale,
                    "fee": (_number(open_row.get("Fee")) + _number(close_row.get("Fee"))) * scale,
                    "reason": "Expert" if _integer(open_row.get("Reason"), -1) == 1 else "",
                    "expert_id": _text(open_row.get("ExpertID") or close_row.get("ExpertID")),
                    "comment": " / ".join(filter(None, [_text(open_row.get("Comment")), _text(close_row.get("Comment"))])),
                })
    return result


def _mt4_rows_to_trades(rows: list[dict], scale_by_login: dict[int, float], source: dict) -> dict[int, list[dict]]:
    result = defaultdict(list)
    for row in rows:
        login = _integer(row.get("LOGIN"))
        scale = scale_by_login.get(login, 1.0)
        result[login].append({
            "id": _text(row.get("TICKET")), "ticket": _text(row.get("TICKET")),
            "platform": "MT4", "server": source.get("server"),
            "type": "buy" if _integer(row.get("CMD")) == 0 else "sell",
            "symbol": _text(row.get("SYMBOL")), "volume": _number(row.get("VOLUME")) / 100.0,
            "open_time": _datetime_text(row.get("OPEN_TIME")), "close_time": _datetime_text(row.get("CLOSE_TIME")),
            "profit": _number(row.get("PROFIT")) * scale, "commission": _number(row.get("COMMISSION")) * scale,
            "swap": _number(row.get("SWAPS")) * scale, "taxes": _number(row.get("TAXES")) * scale,
            "reason": "Expert" if _integer(row.get("REASON"), -1) == 1 else "",
            "expert_id": _text(row.get("MAGIC")) if _integer(row.get("MAGIC")) else "",
            "comment": _text(row.get("COMMENT")),
        })
    return result


class RebateChurningService:
    """Read-only IB rebate-churning scanner with in-memory asynchronous jobs."""

    def __init__(
        self,
        sources: list[dict],
        connect: Callable,
        *,
        classify_mt5_cashflows: Callable | None = None,
        classify_mt4_cashflows: Callable | None = None,
        now_text: Callable[[], str] | None = None,
    ):
        self.sources = sources
        self.connect = connect
        self.classify_mt5_cashflows = classify_mt5_cashflows
        self.classify_mt4_cashflows = classify_mt4_cashflows
        self.now_text = now_text or (lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.jobs: dict[str, dict] = {}
        self.jobs_lock = threading.Lock()
        self.detail_cache: dict[tuple, dict] = {}

    def _update_job(self, job_id: str, **changes) -> None:
        with self.jobs_lock:
            job = self.jobs.setdefault(job_id, {"id": job_id})
            job.update(changes)
            job["updatedAt"] = self.now_text()

    def get_job(self, job_id: str) -> dict:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            return copy.deepcopy(job) if job else {"id": job_id, "status": "missing", "message": "扫描任务不存在"}

    def start_scan(self, payload: dict | None = None) -> dict:
        options = parse_scan_options(payload)
        job_id = f"RBC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self._update_job(
            job_id, status="queued", percent=0, message="已提交，等待扫描", options={
                "start": options["startText"], "end": options["endText"], "environments": options["environments"]
            }, createdAt=self.now_text(), results=[], summary={}
        )
        threading.Thread(target=self._run_scan, args=(job_id, options), daemon=True, name=f"rebate-scan-{job_id}").start()
        return self.get_job(job_id)

    def _run_scan(self, job_id: str, options: dict) -> None:
        started = datetime.now()
        try:
            self._update_job(job_id, status="running", percent=2, message="正在读取返佣候选与交易分位")
            results = []
            errors = []
            for index, environment in enumerate(options["environments"]):
                try:
                    rows = self._scan_environment(environment, options, job_id)
                    results.extend(rows)
                except Exception as exc:
                    errors.append(f"{SCAN_ENVIRONMENTS[environment]['label']}: {exc}")
                self._update_job(job_id, percent=10 + round((index + 1) / len(options["environments"]) * 82))
            results.sort(key=lambda row: (-_number(row.get("score")), -_number((row.get("summary") or {}).get("currentIbRebate"))))
            levels = Counter(row.get("level") for row in results)
            elapsed = (datetime.now() - started).total_seconds()
            self._update_job(
                job_id, status="done", percent=100,
                message="扫描完成" if not errors else "扫描完成，部分环境失败",
                results=results,
                summary={
                    "ibs": len(results), "warnings": sum(1 for row in results if _number(row.get("score")) >= 60),
                    "highRisk": sum(1 for row in results if _number(row.get("score")) >= 75),
                    "severe": levels.get("严重", 0), "elapsedSeconds": _round(elapsed, 1), "errors": errors,
                },
            )
        except Exception as exc:
            self._update_job(job_id, status="failed", percent=100, message=str(exc), error=str(exc))

    def _environment_source(self, environment: str) -> dict:
        crm_schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        source = next(iter(_sources_for_crm(self.sources, crm_schema)), None)
        if not source:
            raise ValueError(f"环境{environment}没有可用CRM数据源")
        return source

    def resolve_account(self, account: object, environment: object = "", server_code: object = "") -> dict:
        login = _integer(account)
        if not login or not re.fullmatch(r"\d{4,12}", _text(account)):
            raise ValueError("交易账户格式无效")
        environment = _text(environment).lower()
        server_code = _text(server_code)
        if environment and environment not in SCAN_ENVIRONMENTS:
            raise ValueError("环境无效")
        matches = []
        for environment_key, config in SCAN_ENVIRONMENTS.items():
            if environment and environment_key != environment:
                continue
            source = self._environment_source(environment_key)
            schema = config["crm_schema"]
            parameters: list[object] = [login]
            server_filter = ""
            if server_code:
                server_filter = " and a.mt_server_code=%s"
                parameters.append(server_code)
            with self.connect(source) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        select a.user_id, a.mt_login, a.mt_server_code, a.mt_type_name, a.status,
                               u.supper_id, u.top_ib_id, u.user_type, u.customer_type, u.ib_level,
                               u.full_name, u.first_name, u.middle_name, u.last_name
                        from `{schema}`.`mt_users_account` a
                        join `{schema}`.`sys_user_view` u on u.id=a.user_id
                        where a.mt_login=%s {server_filter}
                        """,
                        parameters,
                    )
                    for row in cur.fetchall():
                        route = _source_for(self.sources, schema, row.get("mt_server_code")) or {}
                        matches.append({
                            "environment": environment_key,
                            "environmentLabel": config["label"],
                            "crmSchema": schema,
                            "source": source,
                            "account": login,
                            "serverCode": _text(row.get("mt_server_code")),
                            "platform": _text(route.get("platform")),
                            "server": _text(route.get("server") or route.get("name")),
                            "sourceAvailable": bool(route),
                            "typeName": _text(row.get("mt_type_name")),
                            "status": row.get("status"),
                            "userId": _integer(row.get("user_id")),
                            "parentUserId": _integer(row.get("supper_id")) or None,
                            "topIbId": _integer(row.get("top_ib_id")) or None,
                            "userType": _integer(row.get("user_type"), -1),
                            "customerType": _text(row.get("customer_type")),
                            "ibLevel": row.get("ib_level"),
                            "ownerName": _full_name(row),
                        })
        deduplicated = {
            (row["environment"], row["serverCode"], row["account"], row["userId"]): row
            for row in matches
        }
        matches = sorted(deduplicated.values(), key=lambda row: (row["environment"], row["serverCode"], row["userId"]))
        if not matches:
            raise ValueError("没有找到对应的交易账户")
        if len(matches) > 1:
            candidates = [
                {
                    key: row[key]
                    for key in (
                        "environment", "environmentLabel", "account", "serverCode", "platform",
                        "server", "sourceAvailable", "typeName", "userId", "ownerName",
                    )
                }
                for row in matches
            ]
            raise AmbiguousAccountError("该账户在多个环境或服务器存在，请选择具体账户", candidates)
        if not matches[0]["sourceAvailable"]:
            raise ValueError("账户已找到，但没有经过验证的交易数据源")
        return matches[0]

    def _ancestor_chain(self, subject: dict) -> list[dict]:
        source = subject["source"]
        schema = subject["crmSchema"]
        fields = "id,supper_id,top_ib_id,user_type,customer_type,ib_level,status,full_name,first_name,middle_name,last_name"
        chain = []
        seen = set()
        current_id = subject["userId"]
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                while current_id:
                    if current_id in seen or len(chain) >= 50:
                        raise ValueError("CRM上级链存在循环或超过50层安全上限")
                    seen.add(current_id)
                    cur.execute(f"select {fields} from `{schema}`.`sys_user_view` where id=%s", (current_id,))
                    row = cur.fetchone()
                    if not row:
                        break
                    chain.append(row)
                    current_id = _integer(row.get("supper_id"))
        if not chain:
            raise ValueError("没有找到账户所属CRM用户")
        chain.reverse()
        return chain

    def _owner_accounts(self, subject: dict) -> list[dict]:
        source = subject["source"]
        schema = subject["crmSchema"]
        verified_codes = tuple(sorted({
            _source_route_code(item, schema)
            for item in self.sources
            if _source_route_code(item, schema)
        }))
        if not verified_codes:
            raise ValueError("账户所属环境没有经过验证的交易数据源")
        placeholders = ",".join(["%s"] * len(verified_codes))
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    select user_id,mt_login,mt_server_code,mt_type_name,status,create_time
                    from `{schema}`.`mt_users_account`
                    where user_id=%s and mt_server_code in ({placeholders})
                    order by mt_server_code,mt_login
                    """,
                    [subject["userId"], *verified_codes],
                )
                rows = cur.fetchall()
        if not rows:
            raise ValueError("账户所属客户没有可用交易账户")
        return rows

    def _historical_ib_accounts(self, environment: str, ib_ids: set[int], end: object) -> list[dict]:
        if not ib_ids:
            return []
        source = self._environment_source(environment)
        schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        end_time = _datetime(end) or datetime.now()
        history_start = end_time - timedelta(days=5 * 366)
        output = []
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                for batch in _batches(sorted(ib_ids)):
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"""
                        select trade_user_id as user_id, trade_mt_login as mt_login,
                               mt_server_code, min(create_time) as create_time,
                               max(create_time) as last_rebate_time
                        from `{schema}`.`rebate_task_detail` force index (idx_covering)
                        where rebate_ib_id in ({placeholders})
                          and create_time >= %s and create_time < %s
                        group by trade_user_id, trade_mt_login, mt_server_code
                        """,
                        [*batch, history_start.strftime("%Y-%m-%d %H:%M:%S"), end_time.strftime("%Y-%m-%d %H:%M:%S")],
                    )
                    output.extend(cur.fetchall())
        return output

    @staticmethod
    def _lineage_tree(chain: list[dict], account_nodes: list[dict], risk_by_ib: dict[int, dict], target_account: int) -> dict:
        root = None
        parent = None
        ib_ids = [_integer(row.get("id")) for row in chain if _integer(row.get("user_type"), -1) == 1]
        direct_ib_id = ib_ids[-1] if ib_ids else None
        for row in chain:
            user_id = _integer(row.get("id"))
            is_ib = _integer(row.get("user_type"), -1) == 1
            node = {
                "type": "ib" if is_ib else "customer",
                "userId": user_id,
                "name": _full_name(row),
                "ibLevel": row.get("ib_level"),
                "relationship": (
                    "直属IB" if is_ib and user_id == direct_ib_id
                    else "上级IB" if is_ib
                    else "账户所属客户"
                ),
                "risk": risk_by_ib.get(user_id) if is_ib else None,
                "accounts": [],
                "children": [],
            }
            if user_id == _integer(chain[-1].get("id")):
                node["accounts"] = [
                    {**account, "isTarget": _integer(account.get("account")) == target_account}
                    for account in account_nodes
                ]
            if parent is None:
                root = node
            else:
                parent["children"].append(node)
            parent = node
        return root or {}

    @staticmethod
    def _subtree_user_ids(users: dict[int, dict], root_id: int) -> set[int]:
        children = defaultdict(list)
        for user_id, row in users.items():
            children[_integer(row.get("supper_id"))].append(user_id)
        output = set()
        queue = deque([root_id])
        while queue:
            user_id = queue.popleft()
            if user_id in output or user_id not in users:
                continue
            output.add(user_id)
            queue.extend(children.get(user_id, []))
        return output

    @staticmethod
    def _tree_financials(users: dict[int, dict], features: list[dict]) -> dict[int, dict]:
        output = {
            user_id: {
                "accounts": 0,
                "orders": 0,
                "lots": 0.0,
                "tradeProfit": 0.0,
                "currentIbRebate": 0.0,
                "hierarchyRebate": 0.0,
                "externalNetDeposit": 0.0,
            }
            for user_id in users
        }
        for feature in features:
            owner_id = _integer(feature.get("userId"))
            rebate_by_ib = defaultdict(float)
            for rebate in feature.get("_rebateRows", []):
                rebate_by_ib[_integer(rebate.get("rebate_ib_id"))] += _rebate_amount(rebate)
            current_id = owner_id
            seen = set()
            while current_id in users and current_id not in seen:
                seen.add(current_id)
                totals = output[current_id]
                totals["accounts"] += 1
                totals["orders"] += _integer(feature.get("orders"))
                totals["lots"] += _number(feature.get("lots"))
                totals["tradeProfit"] += _number(feature.get("tradeProfit"))
                totals["hierarchyRebate"] += _number(feature.get("hierarchyRebate"))
                totals["externalNetDeposit"] += _number(feature.get("externalNetDeposit"))
                if _integer(users[current_id].get("user_type"), -1) == 1:
                    totals["currentIbRebate"] += rebate_by_ib.get(current_id, 0.0)
                current_id = _integer(users[current_id].get("supper_id"))
        for user_id, totals in output.items():
            is_ib = _integer(users[user_id].get("user_type"), -1) == 1
            for key in ("lots", "tradeProfit", "currentIbRebate", "hierarchyRebate", "externalNetDeposit"):
                totals[key] = _round(totals[key], 5)
            totals["combinedProfit"] = _round(
                totals["tradeProfit"] + totals["currentIbRebate"] if is_ib else totals["tradeProfit"],
                5,
            )
        return output

    @staticmethod
    def _account_audit_tree(
        users: dict[int, dict],
        account_nodes: list[dict],
        risk_by_ib: dict[int, dict],
        financials_by_user: dict[int, dict],
        root_id: int,
        direct_ib_id: int,
        ancestor_ib_ids: set[int],
        target_account: int,
    ) -> dict:
        children = defaultdict(list)
        for user_id, row in users.items():
            parent_id = _integer(row.get("supper_id"))
            if parent_id in users:
                children[parent_id].append(user_id)
        accounts_by_user = defaultdict(list)
        for account in account_nodes:
            accounts_by_user[_integer(account.get("userId"))].append({
                **account,
                "isTarget": _integer(account.get("account")) == target_account,
            })

        def build(user_id: int) -> dict:
            row = users[user_id]
            is_ib = _integer(row.get("user_type"), -1) == 1
            if is_ib and user_id == direct_ib_id:
                relationship = "直属IB"
            elif is_ib and user_id in ancestor_ib_ids:
                relationship = "上级IB"
            elif is_ib:
                relationship = "下级IB"
            else:
                relationship = "客户"
            child_ids = sorted(
                children.get(user_id, []),
                key=lambda item: (
                    0 if _integer(users[item].get("user_type"), -1) == 1 else 1,
                    _full_name(users[item]),
                    item,
                ),
            )
            return {
                "type": "ib" if is_ib else "customer",
                "userId": user_id,
                "name": _full_name(row),
                "ibLevel": row.get("ib_level"),
                "relationship": relationship,
                "risk": risk_by_ib.get(user_id) if is_ib else None,
                "financials": financials_by_user.get(user_id, {}),
                "accounts": sorted(accounts_by_user.get(user_id, []), key=lambda item: _integer(item.get("account"))),
                "children": [build(child_id) for child_id in child_ids],
            }

        return build(root_id)

    def target_account_audit(
        self,
        account: object,
        start: object = "",
        end: object = "",
        environment: object = "",
        server_code: object = "",
    ) -> dict:
        subject = self.resolve_account(account, environment, server_code)
        period = parse_period(
            start or ACCOUNT_HISTORY_STARTS[subject["environment"]],
            end,
            max_range_days=MAX_ACCOUNT_RANGE_DAYS,
        )
        chain = self._ancestor_chain(subject)
        ib_rows = [row for row in chain if _integer(row.get("user_type"), -1) == 1]
        if not ib_rows:
            raise ValueError("该账户没有可识别的上级IB")
        first_ib_index = next(
            index for index, row in enumerate(chain) if _integer(row.get("user_type"), -1) == 1
        )
        chain = chain[first_ib_index:]

        root_ib_id = _integer(ib_rows[0].get("id"))
        users, current_accounts = self._fetch_tree(subject["environment"], root_ib_id)
        raw_accounts = [
            {**row, "isHistorical": False}
            for row in current_accounts
            if _integer(users.get(_integer(row.get("user_id")), {}).get("user_type"), -1) != 1
        ]
        current_keys = {
            (_text(row.get("mt_server_code")), _integer(row.get("mt_login")))
            for row in raw_accounts
        }
        historical_rows = self._historical_ib_accounts(
            subject["environment"],
            {_integer(row.get("id")) for row in ib_rows},
            period["end"],
        )
        for row in historical_rows:
            user_id = _integer(row.get("user_id"))
            key = (_text(row.get("mt_server_code")), _integer(row.get("mt_login")))
            if (
                user_id not in users
                or _integer(users[user_id].get("user_type"), -1) == 1
                or not key[1]
                or key in current_keys
            ):
                continue
            raw_accounts.append({
                **row,
                "mt_type_name": "历史返佣账户",
                "status": None,
                "isHistorical": True,
            })
            current_keys.add(key)
        account_keys = {
            (_text(row.get("mt_server_code")), _integer(row.get("mt_login")))
            for row in raw_accounts
            if _source_for(self.sources, subject["crmSchema"], row.get("mt_server_code"))
        }
        mappings = self._account_mappings(subject["environment"], account_keys)
        for raw in raw_accounts:
            key = (_text(raw.get("mt_server_code")), _integer(raw.get("mt_login")))
            if key not in account_keys or key in mappings:
                continue
            owner = users.get(_integer(raw.get("user_id")), {})
            mappings[key] = {**raw, **{
                name_key: owner.get(name_key)
                for name_key in ("full_name", "first_name", "middle_name", "last_name", "supper_id", "top_ib_id", "user_type")
            }}
        raw_accounts = [
            row for row in raw_accounts
            if (_text(row.get("mt_server_code")), _integer(row.get("mt_login"))) in mappings
        ]
        if not raw_accounts:
            raise ValueError("上级IB子树没有可访问的交易账户")
        account_keys = {(_text(row.get("mt_server_code")), _integer(row.get("mt_login"))) for row in raw_accounts}
        rebates = self._rebate_details(subject["environment"], account_keys, period)
        trades = self._detailed_trades(subject["environment"], mappings, rebates, period)
        cashflows = self._cashflow_metrics(subject["environment"], mappings, rebates, trades, period)
        aggregate_rows = self._trade_aggregates_for_accounts(subject["environment"], raw_accounts, period)
        aggregate_map = {(row["serverCode"], row["login"]): row for row in aggregate_rows}

        features = []
        for raw in raw_accounts:
            key = (_text(raw.get("mt_server_code")), _integer(raw.get("mt_login")))
            aggregate = aggregate_map.get(key, {})
            feature = account_features(trades.get(key, []), active_days=aggregate.get("activeDays"))
            feature.update(cashflows.get(key, {}))
            source = _source_for(self.sources, subject["crmSchema"], key[0]) or {}
            details = rebates.get(key, [])
            user_id = _integer(raw.get("user_id"))
            owner = users.get(user_id, mappings.get(key, {}))
            feature.update({
                "account": key[1],
                "serverCode": key[0],
                "userId": user_id,
                "ownerName": _full_name(owner),
                "typeName": _text(raw.get("mt_type_name")),
                "platform": _text(source.get("platform")),
                "server": _text(source.get("server") or source.get("name")),
                "isHistorical": bool(raw.get("isHistorical")),
                "isCent": _money_scale(raw, details) == 0.01,
                "hierarchyRebate": _round(sum(_rebate_amount(row) for row in details), 5),
                "hierarchyRebateRows": len(details),
                "_rebateRows": details,
            })
            features.append(feature)

        risk_by_ib = {}
        financials_by_user = self._tree_financials(users, features)
        direct_ib_id = _integer(ib_rows[-1].get("id"))
        subtree_by_ib = {
            _integer(row.get("id")): self._subtree_user_ids(users, _integer(row.get("id")))
            for row in ib_rows
        }
        scored_accounts_by_ib = {}
        for row in ib_rows:
            ib_id = _integer(row.get("id"))
            attached = [
                self._attach_ib_rebate(feature, ib_id)
                for feature in features
                if _integer(feature.get("userId")) in subtree_by_ib[ib_id]
            ]
            scored = score_ib(
                attached,
                ib_id=ib_id,
                environment=subject["environment"],
                thresholds=TARGET_COHORT_THRESHOLDS,
            )
            scored["ibName"] = _full_name(row) or f"IB {ib_id}"
            scored["ibLevel"] = row.get("ib_level")
            scored["relationship"] = "直属IB" if ib_id == direct_ib_id else "上级IB"
            scored_accounts_by_ib[ib_id] = scored.get("accounts", [])
            risk_by_ib[ib_id] = {key: value for key, value in scored.items() if key != "accounts"}

        display_by_key = {}
        for row in reversed(ib_rows):
            ib_id = _integer(row.get("id"))
            for account_row in scored_accounts_by_ib.get(ib_id, []):
                key = (_text(account_row.get("serverCode")), _integer(account_row.get("account")))
                display_by_key.setdefault(key, account_row)
        account_nodes = []
        for feature in features:
            key = (_text(feature.get("serverCode")), _integer(feature.get("account")))
            owner_id = _integer(feature.get("userId"))
            preferred_ib_id = next(
                (
                    _integer(row.get("id"))
                    for row in reversed(ib_rows)
                    if owner_id in subtree_by_ib[_integer(row.get("id"))]
                ),
                root_ib_id,
            )
            fallback = self._attach_ib_rebate(feature, preferred_ib_id)
            account_nodes.append(display_by_key.get(key, fallback))

        tree = self._account_audit_tree(
            users,
            account_nodes,
            risk_by_ib,
            financials_by_user,
            root_ib_id,
            direct_ib_id,
            set(risk_by_ib),
            subject["account"],
        )
        ib_risks = list(risk_by_ib.values())
        highest = max(ib_risks, key=lambda row: _number(row.get("score")))
        direct_risk = risk_by_ib[direct_ib_id]
        lineage = [
            {
                "type": "ib" if _integer(row.get("user_type"), -1) == 1 else "customer",
                "userId": _integer(row.get("id")),
                "name": _full_name(row),
                "ibLevel": row.get("ib_level"),
            }
            for row in chain
        ]
        return {
            "ok": True,
            "query": {
                "account": subject["account"],
                "environment": subject["environment"],
                "serverCode": subject["serverCode"],
                "start": period["startText"],
                "end": period["endText"],
            },
            "account": {
                key: subject[key]
                for key in (
                    "account", "environment", "environmentLabel", "serverCode", "platform", "server",
                    "typeName", "userId", "ownerName",
                )
            },
            "assessment": {
                "score": highest["score"],
                "level": highest["level"],
                "stage": highest["stage"],
                "confidence": highest["confidence"],
                "highestRiskIbId": highest["ibId"],
                "highestRiskIbName": highest["ibName"],
                "directIbId": direct_ib_id,
                "directIbScore": direct_risk["score"],
                "directIbLevel": direct_risk["level"],
                "evidenceTags": highest.get("evidenceTags", []),
            },
            "lineage": lineage,
            "ibRisks": ib_risks,
            "tree": tree,
            "scope": {
                "ibs": sum(1 for row in users.values() if _integer(row.get("user_type"), -1) == 1),
                "customers": sum(1 for row in users.values() if _integer(row.get("user_type"), -1) != 1),
                "accounts": len(account_nodes),
                "historicalAccounts": sum(1 for row in account_nodes if row.get("isHistorical")),
            },
            "refreshedAt": self.now_text(),
            "limitations": [
                "本次分析目标账户最高上级IB的完整CRM子树，并补充五年内存在返佣的历史账户",
                "各级IB仅使用该IB在所选期间实际收到的返佣计分",
            ],
        }

    def _rebate_summaries(self, environment: str, period: dict) -> tuple[list[dict], dict[tuple, dict]]:
        source = self._environment_source(environment)
        schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        sql = f"""
            select rebate_ib_id, trade_user_id, trade_mt_login, mt_server_code,
                   sum(coalesce(rebate_amount,0) * case when upper(coalesce(usd_or_usc,''))='USC' then 0.01 else 1 end) as CurrentIbRebate,
                   count(*) as CurrentIbRebateRows,
                   count(distinct case when trade_mt_deal > 0 then trade_mt_deal else trade_mt_ticket end) as RebateOrders
            from `{schema}`.`rebate_task_detail`
            where create_time >= %s and create_time < %s and rebate_ib_id is not null
            group by rebate_ib_id, trade_user_id, trade_mt_login, mt_server_code
        """
        total_sql = f"""
            select trade_user_id, trade_mt_login, mt_server_code,
                   sum(coalesce(rebate_amount,0) * case when upper(coalesce(usd_or_usc,''))='USC' then 0.01 else 1 end) as HierarchyRebate, count(*) as HierarchyRebateRows
            from `{schema}`.`rebate_task_detail`
            where create_time >= %s and create_time < %s
            group by trade_user_id, trade_mt_login, mt_server_code
        """
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (period["startText"], period["endText"]))
                current = cur.fetchall()
                cur.execute(total_sql, (period["startText"], period["endText"]))
                totals = {
                    (_integer(row.get("trade_user_id")), _integer(row.get("trade_mt_login")), _text(row.get("mt_server_code"))): row
                    for row in cur.fetchall()
                }
        return current, totals

    def _trade_aggregates(self, environment: str, period: dict) -> list[dict]:
        crm_schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        result = []
        for source in [item for item in _sources_for_crm(self.sources, crm_schema) if item.get("kind") in {"mt5_deals", "mt4_trades"}]:
            with self.connect(source) as conn:
                with conn.cursor() as cur:
                    if source.get("kind") == "mt5_deals":
                        cur.execute(
                            f"""
                            select Login, count(*) as Orders, count(distinct date(Time)) as ActiveDays,
                                   sum(coalesce(nullif(VolumeClosed,0),Volume))/10000.0 as Lots,
                                   sum(coalesce(Profit,0)+coalesce(Commission,0)+coalesce(Storage,0)+coalesce(Fee,0)) as TradeProfit
                            from `{source['schema']}`.`{source['table']}`
                            where Action in (0,1) and Entry in (1,2,3) and Time >= %s and Time < %s
                            group by Login
                            """, (period["startText"], period["endText"]),
                        )
                        rows = cur.fetchall()
                        login_key = "Login"
                    else:
                        cur.execute(
                            f"""
                            select LOGIN, count(*) as Orders, count(distinct date(CLOSE_TIME)) as ActiveDays,
                                   sum(VOLUME)/100.0 as Lots,
                                   sum(coalesce(PROFIT,0)+coalesce(COMMISSION,0)+coalesce(SWAPS,0)+coalesce(TAXES,0)) as TradeProfit
                            from `{source['schema']}`.`{source['table']}`
                            where CMD in (0,1) and CLOSE_TIME >= %s and CLOSE_TIME < %s
                            group by LOGIN
                            """, (period["startText"], period["endText"]),
                        )
                        rows = cur.fetchall()
                        login_key = "LOGIN"
            for row in rows:
                orders = _integer(row.get("Orders"))
                days = max(_integer(row.get("ActiveDays")), 1)
                result.append({
                    "login": _integer(row.get(login_key)), "serverCode": _source_route_code(source, crm_schema),
                    "source": source, "orders": orders, "activeDays": days,
                    "ordersPerActiveDay": orders / days, "lots": _number(row.get("Lots")),
                    "tradeProfit": _number(row.get("TradeProfit")),
                })
        return result

    def _opposite_candidates(self, environment: str, period: dict) -> set[tuple[str, int]]:
        """Find same-second, opposite, near-equal opening volume using bounded read-only SQL."""
        crm_schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        candidates = set()
        sources = [
            item for item in self.sources
            if _source_route_code(item, crm_schema) and item.get("kind") in {"mt5_deals", "mt4_trades"}
        ]
        for source in sources:
            with self.connect(source) as conn:
                with conn.cursor() as cur:
                    if source.get("kind") == "mt5_deals":
                        cur.execute(
                            f"""
                            select Login
                            from (
                                select Login, Symbol, date_format(TimeMsc,'%%Y-%%m-%%d %%H:%%i:%%s') as OpenSecond,
                                       sum(case when Action=0 then Volume else 0 end) as BuyVolume,
                                       sum(case when Action=1 then Volume else 0 end) as SellVolume
                                from `{source['schema']}`.`{source['table']}`
                                where Entry=0 and Action in (0,1) and Time >= %s and Time < %s
                                group by Login, Symbol, OpenSecond
                                having BuyVolume > 0 and SellVolume > 0
                                   and abs(BuyVolume-SellVolume) <= greatest(BuyVolume,SellVolume)*0.05
                            ) paired
                            group by Login
                            """, (period["startText"], period["endText"]),
                        )
                        rows, login_key = cur.fetchall(), "Login"
                    else:
                        cur.execute(
                            f"""
                            select LOGIN
                            from (
                                select LOGIN, SYMBOL, date_format(OPEN_TIME,'%%Y-%%m-%%d %%H:%%i:%%s') as OpenSecond,
                                       sum(case when CMD=0 then VOLUME else 0 end) as BuyVolume,
                                       sum(case when CMD=1 then VOLUME else 0 end) as SellVolume
                                from `{source['schema']}`.`{source['table']}`
                                where CMD in (0,1) and OPEN_TIME >= %s and OPEN_TIME < %s
                                group by LOGIN, SYMBOL, OpenSecond
                                having BuyVolume > 0 and SellVolume > 0
                                   and abs(BuyVolume-SellVolume) <= greatest(BuyVolume,SellVolume)*0.05
                            ) paired
                            group by LOGIN
                            """, (period["startText"], period["endText"]),
                        )
                        rows, login_key = cur.fetchall(), "LOGIN"
            candidates.update(
                (_source_route_code(source, crm_schema), _integer(row.get(login_key)))
                for row in rows if _integer(row.get(login_key))
            )
        return candidates

    def _account_mappings(self, environment: str, keys: set[tuple[str, int]]) -> dict[tuple[str, int], dict]:
        if not keys:
            return {}
        source = self._environment_source(environment)
        schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        by_code = defaultdict(list)
        for code, login in keys:
            by_code[code].append(login)
        mapped = {}
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                for code, logins in by_code.items():
                    for batch in _batches(sorted(set(logins))):
                        placeholders = ",".join(["%s"] * len(batch))
                        cur.execute(
                            f"""
                            select a.user_id, a.mt_login, a.mt_server_code, a.mt_type_name, a.status,
                                   u.supper_id, u.top_ib_id, u.user_type, u.full_name,
                                   u.first_name, u.middle_name, u.last_name
                            from `{schema}`.`mt_users_account` a
                            join `{schema}`.`sys_user_view` u on u.id=a.user_id
                            where a.mt_server_code=%s and a.mt_login in ({placeholders})
                            """, [code, *batch],
                        )
                        for row in cur.fetchall():
                            mapped[(_text(row.get("mt_server_code")), _integer(row.get("mt_login")))] = row
        return mapped

    def _rebate_details(self, environment: str, keys: set[tuple[str, int]], period: dict) -> dict[tuple[str, int], list[dict]]:
        source = self._environment_source(environment)
        schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        grouped = defaultdict(list)
        by_code = defaultdict(list)
        for code, login in keys:
            by_code[code].append(login)
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                for code, logins in by_code.items():
                    for batch in _batches(sorted(set(logins))):
                        placeholders = ",".join(["%s"] * len(batch))
                        cur.execute(
                            f"""
                            select rebate_ib_id, trade_user_id, trade_mt_login, mt_server_code,
                                   trade_mt_ticket, trade_mt_deal, rebate_amount, create_time,
                                   mt_symbol, mt_volume, mt_open_time, mt_close_time, usd_or_usc, rebate_type
                            from `{schema}`.`rebate_task_detail` force index (idx_mtLogin)
                            where mt_server_code=%s and trade_mt_login in ({placeholders})
                              and create_time >= %s and create_time < %s
                            """, [code, *batch, period["startText"], period["endText"]],
                        )
                        for row in cur.fetchall():
                            grouped[(_text(row.get("mt_server_code")), _integer(row.get("trade_mt_login")))].append(row)
        return grouped

    def ib_contributor_keys(self, environment: str, ib_ids: set[int], period: dict) -> set[tuple[str, int]]:
        if not ib_ids:
            return set()
        source = self._environment_source(environment)
        schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        keys = set()
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                for batch in _batches(sorted(ib_ids)):
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"""
                        select distinct mt_server_code, trade_mt_login
                        from `{schema}`.`rebate_task_detail` force index (idx_covering)
                        where rebate_ib_id in ({placeholders})
                          and create_time >= %s and create_time < %s
                        """, [*batch, period["startText"], period["endText"]],
                    )
                    for row in cur.fetchall():
                        login = _integer(row.get("trade_mt_login"))
                        if login:
                            keys.add((_text(row.get("mt_server_code")), login))
                        if len(keys) > MAX_ACCOUNTS:
                            raise ValueError(f"关联IB贡献账户超过{MAX_ACCOUNTS}个安全上限")
        return keys

    def _detailed_trades(self, environment: str, accounts: dict[tuple[str, int], dict], rebates: dict, period: dict) -> dict[tuple[str, int], list[dict]]:
        crm_schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        by_source = defaultdict(list)
        for key, account in accounts.items():
            source = _source_for(self.sources, crm_schema, key[0])
            if source:
                by_source[source.get("name")].append((key, account, source))
        output = defaultdict(list)
        for source_name, rows in by_source.items():
            source = rows[0][2]
            for batch_rows in _batches(rows):
                logins = [key[1] for key, _, _ in batch_rows]
                placeholders = ",".join(["%s"] * len(logins))
                scale_by_login = {key[1]: _money_scale(account, rebates.get(key)) for key, account, _ in batch_rows}
                with self.connect(source) as conn:
                    with conn.cursor() as cur:
                        if source.get("kind") == "mt5_deals":
                            cur.execute(
                                f"""
                                select Deal, Login, `Order`, PositionID, Action, Entry, Reason, Time, TimeMsc,
                                       Symbol, Volume, VolumeClosed, Profit, Commission, Storage, Fee, Comment, ExpertID
                                from `{source['schema']}`.`{source['table']}` force index (idx_mt5_deals_Login_Time_Comment)
                                where Login in ({placeholders}) and Action in (0,1) and Entry in (0,1,2,3)
                                  and Time >= %s and Time < %s
                                order by Login, PositionID, Time, Deal
                                """, [*logins, period["startText"], period["endText"]],
                            )
                            converted = _mt5_rows_to_trades(cur.fetchall(), scale_by_login, source)
                        else:
                            cur.execute(
                                f"""
                                select TICKET, LOGIN, CMD, SYMBOL, VOLUME, OPEN_TIME, CLOSE_TIME,
                                       COMMISSION, SWAPS, PROFIT, TAXES, REASON, MAGIC, COMMENT
                                from `{source['schema']}`.`{source['table']}`
                                where LOGIN in ({placeholders}) and CMD in (0,1)
                                  and CLOSE_TIME >= %s and CLOSE_TIME < %s
                                order by LOGIN, OPEN_TIME, TICKET
                                """, [*logins, period["startText"], period["endText"]],
                            )
                            converted = _mt4_rows_to_trades(cur.fetchall(), scale_by_login, source)
                for key, _, _ in batch_rows:
                    output[key] = converted.get(key[1], [])
        return output

    def _cashflow_metrics(self, environment: str, accounts: dict[tuple[str, int], dict], rebates: dict, trades: dict, period: dict) -> dict[tuple[str, int], dict]:
        crm_schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        output = defaultdict(dict)
        by_source = defaultdict(list)
        for key, account in accounts.items():
            source = _source_for(self.sources, crm_schema, key[0])
            if source:
                by_source[source.get("name")].append((key, account, source))
        for rows in by_source.values():
            source = rows[0][2]
            for batch_rows in _batches(rows):
                logins = [key[1] for key, _, _ in batch_rows]
                placeholders = ",".join(["%s"] * len(logins))
                raw_by_login = defaultdict(list)
                with self.connect(source) as conn:
                    with conn.cursor() as cur:
                        if source.get("kind") == "mt5_deals":
                            cur.execute(
                                f"select Login, Action, Profit, Comment, Time, TimeMsc from `{source['schema']}`.`{source['table']}` force index (idx_mt5_deals_Login_Time_Comment) where Login in ({placeholders}) and Action not in (0,1) and Time >= %s and Time < %s",
                                [*logins, period["startText"], period["endText"]],
                            )
                            for row in cur.fetchall():
                                raw_by_login[_integer(row.get("Login"))].append(row)
                        else:
                            cur.execute(
                                f"select LOGIN, CMD, PROFIT, COMMENT, OPEN_TIME, CLOSE_TIME from `{source['schema']}`.`{source['table']}` where LOGIN in ({placeholders}) and CMD in (6,7) and OPEN_TIME >= %s and OPEN_TIME < %s",
                                [*logins, period["startText"], period["endText"]],
                            )
                            for row in cur.fetchall():
                                raw_by_login[_integer(row.get("LOGIN"))].append(row)
                for key, account, _ in batch_rows:
                    scale = _money_scale(account, rebates.get(key))
                    classifier = self.classify_mt5_cashflows if source.get("kind") == "mt5_deals" else self.classify_mt4_cashflows
                    cash = classifier(raw_by_login.get(key[1], []), scale) if classifier else {}
                    account_trades = trades.get(key, [])
                    first_trade = min((_trade_time(row, "open") for row in account_trades if _trade_time(row, "open")), default=None)
                    last_trade = max((_trade_time(row, "close") or _trade_time(row, "open") for row in account_trades if _trade_time(row, "close") or _trade_time(row, "open")), default=None)
                    deposits = [_datetime(value) for value in cash.get("depositTimes", []) if _datetime(value)]
                    withdrawals = [_datetime(value) for value in cash.get("withdrawalTimes", []) if _datetime(value)]
                    before_trade = max((value for value in deposits if first_trade and value <= first_trade), default=None)
                    after_trade = min((value for value in withdrawals if last_trade and value >= last_trade), default=None)
                    output[key] = {
                        "externalNetDeposit": _number(cash.get("netDeposit")),
                        "deposit": _number(cash.get("depositTotal")), "withdrawal": _number(cash.get("withdrawalTotal")),
                        "internalTransfer": _number(cash.get("internalTransfer")), "negativeBalanceClear": _number(cash.get("negativeBalanceClear")),
                        "compensation": _number(cash.get("compensation")),
                        "depositToTradeHours": (first_trade - before_trade).total_seconds() / 3600 if first_trade and before_trade else None,
                        "tradeToWithdrawalHours": (after_trade - last_trade).total_seconds() / 3600 if after_trade and last_trade else None,
                    }
        return output

    def _feature_rows(self, environment: str, keys: set[tuple[str, int]], aggregate_map: dict, current_rows: list[dict], totals: dict, period: dict) -> list[dict]:
        mappings = self._account_mappings(environment, keys)
        rebate_details = self._rebate_details(environment, keys, period)
        trades = self._detailed_trades(environment, mappings, rebate_details, period)
        cashflows = self._cashflow_metrics(environment, mappings, rebate_details, trades, period)
        current_by_ib_account = defaultdict(list)
        for row in current_rows:
            current_by_ib_account[(_integer(row.get("rebate_ib_id")), _text(row.get("mt_server_code")), _integer(row.get("trade_mt_login")))].append(row)
        features = []
        for key in keys:
            mapping = mappings.get(key, {})
            aggregate = aggregate_map.get(key, {})
            row = account_features(trades.get(key, []), active_days=aggregate.get("activeDays"))
            row.update(cashflows.get(key, {}))
            row.update({
                "account": key[1], "serverCode": key[0], "userId": _integer(mapping.get("user_id")),
                "ownerName": _full_name(mapping), "parentUserId": _integer(mapping.get("supper_id")) or None,
                "topIbId": _integer(mapping.get("top_ib_id")) or None, "typeName": _text(mapping.get("mt_type_name")),
                "platform": (_source_for(self.sources, SCAN_ENVIRONMENTS[environment]["crm_schema"], key[0]) or {}).get("platform", ""),
                "server": (_source_for(self.sources, SCAN_ENVIRONMENTS[environment]["crm_schema"], key[0]) or {}).get("server", ""),
                "hierarchyRebate": _number(totals.get((_integer(mapping.get("user_id")), key[1], key[0]), {}).get("HierarchyRebate")),
                "hierarchyRebateRows": _integer(totals.get((_integer(mapping.get("user_id")), key[1], key[0]), {}).get("HierarchyRebateRows")),
                "aggregateOrders": _integer(aggregate.get("orders")), "aggregateLots": _number(aggregate.get("lots")),
                "evidenceTags": [],
            })
            all_rebate_rows = rebate_details.get(key, [])
            row["_rebateRows"] = all_rebate_rows
            row["_currentByIb"] = current_by_ib_account
            features.append(row)
        return features

    def _attach_ib_rebate(self, account: dict, ib_id: int) -> dict:
        row = copy.deepcopy(account)
        details = [item for item in row.pop("_rebateRows", []) if _integer(item.get("rebate_ib_id")) == ib_id]
        row.pop("_currentByIb", None)
        row["currentIbRebate"] = _round(sum(_rebate_amount(item) for item in details), 5)
        row["currentIbRebateRows"] = len(details)
        trade_keys = set(row.get("tradeKeys", []))
        ticket_keys = set(row.get("ticketKeys", []))
        matched = set()
        for item in details:
            deal = _text(item.get("trade_mt_deal"))
            ticket = _text(item.get("trade_mt_ticket"))
            if deal in trade_keys or ticket in ticket_keys:
                matched.add(deal if deal in trade_keys else ticket)
        row["matchedRebateOrders"] = len(matched)
        return row

    def _ib_names(self, environment: str, ib_ids: set[int]) -> dict[int, dict]:
        if not ib_ids:
            return {}
        source = self._environment_source(environment)
        schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        output = {}
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                for batch in _batches(sorted(ib_ids)):
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"select id, supper_id, top_ib_id, user_type, ib_level, full_name, first_name, middle_name, last_name from `{schema}`.`sys_user_view` where id in ({placeholders})",
                        batch,
                    )
                    for row in cur.fetchall():
                        output[_integer(row.get("id"))] = row
        return output

    def _scan_environment(self, environment: str, period: dict, job_id: str = "") -> list[dict]:
        current_rows, totals = self._rebate_summaries(environment, period)
        aggregates = self._trade_aggregates(environment, period)
        aggregate_map = {(row["serverCode"], row["login"]): row for row in aggregates}
        by_server = defaultdict(list)
        for row in aggregates:
            by_server[row["serverCode"]].append({**row, "lotsPerDeposit": row.get("lots", 0)})
        server_thresholds = {server: cohort_thresholds(rows) for server, rows in by_server.items()}
        threshold_base = cohort_thresholds([row for rows in by_server.values() for row in rows])
        candidate_keys = {(_text(row.get("mt_server_code")), _integer(row.get("trade_mt_login"))) for row in current_rows}
        candidate_keys.update(
            (row["serverCode"], row["login"]) for row in aggregates
            if row["ordersPerActiveDay"] >= server_thresholds[row["serverCode"]]["ordersPerDayP99"] > 0
            or row["orders"] >= server_thresholds[row["serverCode"]]["ordersP99"] > 0
        )
        candidate_keys.update(self._opposite_candidates(environment, period))
        if job_id:
            self._update_job(job_id, message=f"{SCAN_ENVIRONMENTS[environment]['label']}：正在读取{len(candidate_keys)}个候选账户证据")
        feature_rows = self._feature_rows(environment, candidate_keys, aggregate_map, current_rows, totals, period)
        for row in feature_rows:
            row["cohortThresholds"] = server_thresholds.get(row.get("serverCode"), threshold_base)
        ib_accounts = defaultdict(list)
        rebate_ib_ids = {_integer(row.get("rebate_ib_id")) for row in current_rows if _integer(row.get("rebate_ib_id"))}
        for feature in feature_rows:
            detail_ibs = {_integer(row.get("rebate_ib_id")) for row in feature.get("_rebateRows", []) if _integer(row.get("rebate_ib_id"))}
            if not detail_ibs:
                fallback_ib = _integer(feature.get("parentUserId")) or _integer(feature.get("topIbId"))
                detail_ibs = {fallback_ib} if fallback_ib else set()
            for ib_id in detail_ibs:
                ib_accounts[ib_id].append(self._attach_ib_rebate(feature, ib_id))
        ib_names = self._ib_names(environment, set(ib_accounts) | rebate_ib_ids)
        results = []
        for ib_id, accounts in ib_accounts.items():
            scored = score_ib(accounts, ib_id=ib_id, environment=environment, thresholds=threshold_base)
            name_row = ib_names.get(ib_id, {})
            scored["ibName"] = _full_name(name_row) or f"IB {ib_id}"
            scored["ibLevel"] = name_row.get("ib_level")
            scored["period"] = {"start": period["startText"], "end": period["endText"]}
            scored.pop("accounts", None)
            results.append(scored)
        return results

    def _fetch_tree(self, environment: str, ib_id: int) -> tuple[dict[int, dict], list[dict]]:
        source = self._environment_source(environment)
        schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        fields = "id,supper_id,top_ib_id,user_type,customer_type,ib_level,status,full_name,first_name,middle_name,last_name"
        users = {}
        with self.connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(f"select {fields} from `{schema}`.`sys_user_view` where id=%s", (ib_id,))
                root = cur.fetchone()
                if not root:
                    raise ValueError("IB不存在")
                if _integer(root.get("user_type")) != 1:
                    raise ValueError("指定CRM用户不是IB")
                users[ib_id] = {**root, "depth": 0}
                frontier = [ib_id]
                depth = 0
                while frontier:
                    depth += 1
                    next_frontier = []
                    for batch in _batches(frontier):
                        placeholders = ",".join(["%s"] * len(batch))
                        cur.execute(f"select {fields} from `{schema}`.`sys_user_view` where supper_id in ({placeholders})", batch)
                        for row in cur.fetchall():
                            user_id = _integer(row.get("id"))
                            if user_id and user_id not in users:
                                users[user_id] = {**row, "depth": depth}
                                next_frontier.append(user_id)
                                if len(users) > MAX_USERS:
                                    raise ValueError(f"IB树超过{MAX_USERS}个用户安全上限")
                    frontier = next_frontier
                accounts = []
                verified_codes = tuple(sorted({
                    _source_route_code(item, schema)
                    for item in self.sources
                    if _source_route_code(item, schema)
                }))
                if not verified_codes:
                    raise ValueError("IB所属环境没有经过验证的交易数据源")
                server_placeholders = ",".join(["%s"] * len(verified_codes))
                for batch in _batches(users):
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"select user_id,mt_login,mt_server_code,mt_type_name,status,create_time from `{schema}`.`mt_users_account` where user_id in ({placeholders}) and mt_server_code in ({server_placeholders})",
                        [*batch, *verified_codes],
                    )
                    accounts.extend(cur.fetchall())
                    if len(accounts) > MAX_ACCOUNTS:
                        raise ValueError(f"IB树超过{MAX_ACCOUNTS}个账户安全上限")
        return users, accounts

    def ib_detail(self, environment: str, ib_id: object, start: object = "", end: object = "") -> dict:
        environment = _text(environment).lower()
        if environment not in SCAN_ENVIRONMENTS:
            raise ValueError("环境无效")
        ib_id = _integer(ib_id)
        if not ib_id:
            raise ValueError("IB ID无效")
        period = parse_period(start, end)
        cache_key = (environment, ib_id, period["startText"], period["endText"])
        if cache_key in self.detail_cache:
            return copy.deepcopy(self.detail_cache[cache_key])
        users, raw_accounts = self._fetch_tree(environment, ib_id)
        account_keys = {(_text(row.get("mt_server_code")), _integer(row.get("mt_login"))) for row in raw_accounts}
        tree_rebates = self._rebate_details(environment, account_keys, period)
        totals = {}
        current_keys = set()
        for key, details in tree_rebates.items():
            if any(_integer(row.get("rebate_ib_id")) == ib_id for row in details):
                current_keys.add(key)
            by_owner = defaultdict(list)
            for row in details:
                by_owner[_integer(row.get("trade_user_id"))].append(row)
            for user_id, owner_rows in by_owner.items():
                totals[(user_id, key[1], key[0])] = {
                    "HierarchyRebate": sum(_rebate_amount(row) for row in owner_rows),
                    "HierarchyRebateRows": len(owner_rows),
                }
        aggregate_rows = self._trade_aggregates_for_accounts(environment, raw_accounts, period)
        aggregate_map = {(row["serverCode"], row["login"]): row for row in aggregate_rows}
        candidate_keys = set(current_keys)
        thresholds = cohort_thresholds([{**row, "lotsPerDeposit": row.get("lots", 0)} for row in aggregate_rows])
        candidate_keys.update(
            (row["serverCode"], row["login"]) for row in aggregate_rows
            if row["ordersPerActiveDay"] >= thresholds["ordersPerDayP95"] > 0 or row["orders"] >= thresholds["ordersP95"] > 0
        )
        feature_rows = self._feature_rows(environment, candidate_keys, aggregate_map, [], totals, period)
        feature_by_key = {(row["serverCode"], row["account"]): self._attach_ib_rebate(row, ib_id) for row in feature_rows}
        account_nodes = []
        for raw in raw_accounts:
            key = (_text(raw.get("mt_server_code")), _integer(raw.get("mt_login")))
            aggregate = aggregate_map.get(key, {})
            node = feature_by_key.get(key, {
                "account": key[1], "serverCode": key[0], "orders": _integer(aggregate.get("orders")),
                "lots": _round(aggregate.get("lots"), 4), "tradeProfit": _round(aggregate.get("tradeProfit")),
                "activeDays": _integer(aggregate.get("activeDays")), "ordersPerActiveDay": _round(aggregate.get("ordersPerActiveDay"), 2),
                "currentIbRebate": 0.0, "currentIbRebateRows": 0, "hierarchyRebate": 0.0,
                "pairCoverage": 0.0, "sameSecondCoverage": 0.0, "bothLossCoverage": 0.0, "short10Coverage": 0.0,
                "externalNetDeposit": 0.0, "evidenceTags": [],
            })
            source = _source_for(self.sources, SCAN_ENVIRONMENTS[environment]["crm_schema"], key[0]) or {}
            node.update({
                "userId": _integer(raw.get("user_id")), "platform": source.get("platform", ""), "server": source.get("server", ""),
                "typeName": _text(raw.get("mt_type_name")), "isCent": bool(CENT_RE.search(_text(raw.get("mt_type_name")))),
            })
            account_nodes.append(node)
        scored_accounts = [row for row in account_nodes if row.get("orders") or row.get("currentIbRebate")]
        score = score_ib(scored_accounts, ib_id=ib_id, environment=environment, thresholds=thresholds)
        scored_by_key = {
            (_text(row.get("serverCode")), _integer(row.get("account"))): row
            for row in score.get("accounts", [])
        }
        for index, row in enumerate(account_nodes):
            account_nodes[index] = {
                **row,
                **scored_by_key.get((_text(row.get("serverCode")), _integer(row.get("account"))), {}),
            }
        tree = self._tree_payload(users, account_nodes, ib_id)
        root = users[ib_id]
        payload = {
            "ok": True, "ib": {"id": ib_id, "name": _full_name(root), "environment": environment, "ibLevel": root.get("ib_level")},
            "period": {"start": period["startText"], "end": period["endText"]},
            "risk": {key: value for key, value in score.items() if key != "accounts"},
            "tree": tree, "accounts": account_nodes, "refreshedAt": self.now_text(),
            "limitations": ["当前IB实收返佣用于评分；账户层级总返佣仅展示，不跨父子IB重复计分", "订单少不封顶，仅降低置信度"],
        }
        if len(self.detail_cache) >= 32:
            self.detail_cache.pop(next(iter(self.detail_cache)))
        self.detail_cache[cache_key] = copy.deepcopy(payload)
        return payload

    def _trade_aggregates_for_accounts(self, environment: str, accounts: list[dict], period: dict) -> list[dict]:
        crm_schema = SCAN_ENVIRONMENTS[environment]["crm_schema"]
        by_source = defaultdict(list)
        for row in accounts:
            source = _source_for(self.sources, crm_schema, row.get("mt_server_code"))
            if source:
                by_source[source.get("name")].append((_integer(row.get("mt_login")), source))
        output = []
        for rows in by_source.values():
            source = rows[0][1]
            for batch in _batches(rows):
                logins = [login for login, _ in batch]
                placeholders = ",".join(["%s"] * len(logins))
                with self.connect(source) as conn:
                    with conn.cursor() as cur:
                        if source.get("kind") == "mt5_deals":
                            cur.execute(
                                f"select Login,count(*) Orders,count(distinct date(Time)) ActiveDays,sum(coalesce(nullif(VolumeClosed,0),Volume))/10000.0 Lots,sum(coalesce(Profit,0)+coalesce(Commission,0)+coalesce(Storage,0)+coalesce(Fee,0)) TradeProfit from `{source['schema']}`.`{source['table']}` where Login in ({placeholders}) and Action in (0,1) and Entry in (1,2,3) and Time >= %s and Time < %s group by Login",
                                [*logins, period["startText"], period["endText"]],
                            )
                            rows_out, login_key = cur.fetchall(), "Login"
                        else:
                            cur.execute(
                                f"select LOGIN,count(*) Orders,count(distinct date(CLOSE_TIME)) ActiveDays,sum(VOLUME)/100.0 Lots,sum(coalesce(PROFIT,0)+coalesce(COMMISSION,0)+coalesce(SWAPS,0)+coalesce(TAXES,0)) TradeProfit from `{source['schema']}`.`{source['table']}` where LOGIN in ({placeholders}) and CMD in (0,1) and CLOSE_TIME >= %s and CLOSE_TIME < %s group by LOGIN",
                                [*logins, period["startText"], period["endText"]],
                            )
                            rows_out, login_key = cur.fetchall(), "LOGIN"
                for row in rows_out:
                    orders, days = _integer(row.get("Orders")), max(_integer(row.get("ActiveDays")), 1)
                    output.append({"login": _integer(row.get(login_key)), "serverCode": _source_route_code(source, crm_schema), "source": source, "orders": orders, "activeDays": days, "ordersPerActiveDay": orders / days, "lots": _number(row.get("Lots")), "tradeProfit": _number(row.get("TradeProfit"))})
        return output

    @staticmethod
    def _tree_payload(users: dict[int, dict], accounts: list[dict], root_id: int) -> dict:
        children = defaultdict(list)
        for user_id, row in users.items():
            parent_id = _integer(row.get("supper_id"))
            if parent_id in users:
                children[parent_id].append(user_id)
        accounts_by_user = defaultdict(list)
        for row in accounts:
            accounts_by_user[_integer(row.get("userId"))].append(row)

        def build(user_id: int) -> dict:
            row = users[user_id]
            role = "ib" if _integer(row.get("user_type")) == 1 else "customer"
            return {
                "type": role, "userId": user_id, "name": _full_name(row), "ibLevel": row.get("ib_level"),
                "children": [build(child_id) for child_id in sorted(children[user_id])],
                "accounts": sorted(accounts_by_user[user_id], key=lambda item: (item.get("server", ""), item.get("account", 0))),
            }
        return build(root_id)


LEGACY_PAGE_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IB刷返佣审计</title><style>
:root{--bg:#eef1f1;--paper:#fff;--ink:#182126;--muted:#667278;--line:#dce2e4;--accent:#087f78;--danger:#b42318;--warn:#a15c00;--good:#177245}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","Segoe UI",sans-serif;letter-spacing:0}button,input,select{font:inherit;letter-spacing:0}.topbar{height:58px;background:#172226;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 28px}.topbar a{color:#e9f0f1;text-decoration:none}.brand{font-size:18px;font-weight:700}main{width:min(1540px,calc(100% - 32px));margin:18px auto 40px}.band{background:#fff;border:1px solid var(--line);border-top:3px solid var(--accent)}.head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 18px;border-bottom:1px solid var(--line)}h1,h2{margin:0;font-size:18px}.filters{display:grid;grid-template-columns:180px 180px 150px 150px 130px 1fr;gap:9px;align-items:end;padding:14px 18px}.filters label{display:grid;gap:5px;color:var(--muted);font-size:12px}.envs{display:flex;gap:12px;min-height:38px;align-items:center}.envs label{display:flex;align-items:center;gap:5px}.envs input{width:auto}input,select,button{min-height:38px;border:1px solid #bbc5c8;border-radius:5px;background:#fff;padding:8px 10px;color:var(--ink)}button{cursor:pointer}button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}button:disabled{opacity:.55;cursor:not-allowed}.status{padding:10px 18px;color:var(--muted);border-top:1px solid var(--line);min-height:42px}.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border-top:1px solid var(--line)}.metric{padding:13px 16px;border-right:1px solid var(--line)}.metric:last-child{border-right:0}.metric span{display:block;color:var(--muted);font-size:11px}.metric b{display:block;margin-top:4px;font-size:20px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:1250px}th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;vertical-align:top}th{background:#f3f5f5;color:#526066;font-size:12px;position:sticky;top:0}.link{color:#075e59;font-weight:700;text-decoration:none}.score{font-size:19px;font-weight:800}.level{display:inline-block;border-radius:4px;padding:3px 7px;background:#edf2f2}.level.severe{background:#fde8e7;color:var(--danger)}.level.high{background:#fff0dc;color:#8b4d00}.level.warning{background:#fff8df;color:var(--warn)}.tags{display:flex;flex-wrap:wrap;gap:5px}.tag{padding:2px 6px;border-radius:4px;background:#e8f2f1;color:#075e59;font-size:11px}.detail{margin-top:16px;background:#fff;border:1px solid var(--line)}.detail[hidden]{display:none}.detail-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));border-bottom:1px solid var(--line)}.tree{padding:10px 16px}.node{margin:5px 0 5px 18px;border-left:1px solid #cad4d6;padding-left:12px}.node>summary{cursor:pointer;list-style:none;padding:7px 0}.node>summary::-webkit-details-marker{display:none}.node>summary:before{content:'▸';display:inline-block;width:18px;color:var(--muted)}.node[open]>summary:before{content:'▾'}.account-table{margin:5px 0 10px}.account-table table{min-width:1450px}.muted{color:var(--muted);font-size:12px;overflow-wrap:anywhere}.negative{color:var(--danger)}.positive{color:var(--good)}.empty{padding:35px;text-align:center;color:var(--muted)}@media(max-width:900px){.topbar{padding:0 12px;gap:10px}.topbar a{font-size:13px;white-space:nowrap}.brand{max-width:145px;font-size:15px;line-height:1.2;text-align:right}.filters{grid-template-columns:1fr 1fr}.filters button,.envs{grid-column:1/-1}.metrics,.detail-grid{grid-template-columns:1fr 1fr}.metric{border-bottom:1px solid var(--line)}}
</style></head><body><header class="topbar"><a href="/">← 返回账号工作台</a><div class="brand">刷返佣检测</div><span></span></header><main>
<section class="band"><div class="head"><div><h1>IB风险榜</h1><div class="muted">当前IB实收返佣计分，账户层级总返佣仅展示</div></div></div>
<form class="filters" id="scanForm"><label>开始时间<input id="start" type="datetime-local"></label><label>结束时间<input id="end" type="datetime-local"></label><label>环境<span class="envs"><label><input type="checkbox" value="gb" checked>AC GB</label><label><input type="checkbox" value="cn" checked>AC CN</label></span></label><label>风险等级<select id="level"><option value="">全部</option><option>严重</option><option>高危</option><option>预警</option><option>低风险</option></select></label><label>阶段<select id="stage"><option value="">全部</option><option>返佣确认</option><option>交易结构预警</option></select></label><button class="primary" id="scanBtn">开始扫描</button></form><div class="status" id="status">等待扫描</div><div class="metrics" id="metrics"></div>
<div class="table-wrap"><table><thead><tr><th>环境 / IB</th><th>评分</th><th>等级 / 阶段</th><th>可疑账户</th><th>订单 / 手数</th><th>交易盈亏</th><th>当前IB实收</th><th>层级总返佣</th><th>返佣/亏损</th><th>证据</th><th></th></tr></thead><tbody id="ranking"><tr><td colspan="11" class="empty">尚未运行扫描</td></tr></tbody></table></div></section>
<section class="detail" id="detail" hidden><div class="head"><div><h2 id="detailTitle">IB树形审计</h2><div class="muted" id="detailMeta"></div></div><button id="closeDetail">关闭</button></div><div class="detail-grid" id="detailMetrics"></div><div class="tree" id="tree"></div></section>
</main><script>
const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=(v,d=1)=>Number(v||0).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}),money=v=>num(v,2),pct=v=>v===null||v===undefined?'-':num(Number(v)*100,1)+'%',state={rows:[],job:null,timer:null};
function localValue(d){const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`};function init(){const end=new Date(),start=new Date(end.getTime()-7*86400000);$('end').value=localValue(end);$('start').value=localValue(start)}
async function json(url,opt){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...opt}),data=await r.json();if(!r.ok||data.ok===false)throw new Error(data.error||'请求失败');return data}
function badge(level){const c=level==='严重'?'severe':level==='高危'?'high':level==='预警'?'warning':'';return `<span class="level ${c}">${esc(level)}</span>`}function render(){const level=$('level').value,stage=$('stage').value,rows=state.rows.filter(r=>(!level||r.level===level)&&(!stage||r.stage===stage));$('ranking').innerHTML=rows.length?rows.map(r=>{const s=r.summary||{},p=r.period||{};return `<tr><td><b>${esc((r.environment||'').toUpperCase())} · ${esc(r.ibName||'IB')}</b><br><span class="muted">CRM ${esc(r.ibId)}</span></td><td class="score">${num(r.score,1)}</td><td>${badge(r.level)}<br><span class="muted">${esc(r.stage)} · 置信度${esc(r.confidence)}</span></td><td>${num(s.suspiciousAccounts,0)} / ${num(s.accounts,0)}</td><td>${num(s.orders,0)} / ${num(s.lots,2)}</td><td class="${Number(s.tradeProfit)<0?'negative':'positive'}">${money(s.tradeProfit)}</td><td>${money(s.currentIbRebate)}</td><td>${money(s.hierarchyRebate)}</td><td>${pct(s.rebateLossCoverage)}</td><td><div class="tags">${(r.evidenceTags||[]).slice(0,4).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></td><td><button data-env="${esc(r.environment)}" data-ib="${esc(r.ibId)}" data-start="${esc(p.start||$('start').value)}" data-end="${esc(p.end||$('end').value)}">展开树</button></td></tr>`}).join(''):'<tr><td colspan="11" class="empty">没有匹配的IB</td></tr>';document.querySelectorAll('#ranking button[data-ib]').forEach(b=>b.onclick=()=>loadDetail(b.dataset.env,b.dataset.ib,b.dataset.start,b.dataset.end))}
function summaryMetrics(s){return [['IB数',s.ibs||0],['预警及以上',s.warnings||0],['高危及以上',s.highRisk||0],['严重',s.severe||0],['耗时',`${num(s.elapsedSeconds||0,1)}秒`]].map(x=>`<div class="metric"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('')}
async function poll(id){clearTimeout(state.timer);const d=await json(`/api/rebate-churning/scans/${encodeURIComponent(id)}`),j=d.job||{};state.job=j;$('status').textContent=`${j.message||j.status} · ${num(j.percent||0,0)}%`;if(j.status==='done'||j.status==='failed'){$('scanBtn').disabled=false;state.rows=j.results||[];$('metrics').innerHTML=summaryMetrics(j.summary||{});render();return}state.timer=setTimeout(()=>poll(id),1200)}
$('scanForm').onsubmit=async e=>{e.preventDefault();const environments=[...document.querySelectorAll('.envs input:checked')].map(x=>x.value);$('scanBtn').disabled=true;$('status').textContent='正在提交扫描';try{const d=await json('/api/rebate-churning/scans',{method:'POST',body:JSON.stringify({start:$('start').value,end:$('end').value,environments})});poll(d.job.id)}catch(e){$('status').textContent=e.message;$('scanBtn').disabled=false}};$('level').onchange=render;$('stage').onchange=render;
function metric(label,value){return `<div class="metric"><span>${esc(label)}</span><b>${value}</b></div>`}function accountTable(rows){return `<div class="account-table table-wrap"><table><thead><tr><th>账户</th><th>服务器</th><th>订单 / 手数</th><th>交易盈亏</th><th>当前IB实收</th><th>层级总返佣</th><th>返佣明细</th><th>配对覆盖</th><th>10秒覆盖</th><th>订单/活跃日</th><th>净入金</th><th>风险贡献</th><th>证据</th></tr></thead><tbody>${rows.map(a=>`<tr><td><a class="link" target="_blank" href="/account/${encodeURIComponent(a.account)}?platform=${encodeURIComponent(a.platform||'')}&server=${encodeURIComponent(a.server||'')}">${esc(a.account)}</a></td><td>${esc(a.server||'-')}<br><span class="muted">${esc(a.typeName||'')}</span></td><td>${num(a.orders,0)} / ${num(a.lots,2)}</td><td class="${Number(a.tradeProfit)<0?'negative':'positive'}">${money(a.tradeProfit)}</td><td>${money(a.currentIbRebate)}</td><td>${money(a.hierarchyRebate)}</td><td>${num(a.currentIbRebateRows,0)}</td><td>${pct(a.pairCoverage)}</td><td>${pct(a.short10Coverage)}</td><td>${num(a.ordersPerActiveDay,1)}</td><td>${money(a.externalNetDeposit)}</td><td>${num(a.riskContribution,1)}</td><td><div class="tags">${(a.evidenceTags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></td></tr>`).join('')}</tbody></table></div>`}function treeNode(n,depth=0){const own=accountTable(n.accounts||[]),children=(n.children||[]).map(x=>treeNode(x,depth+1)).join('');return `<details class="node" ${depth<2?'open':''}><summary><b>${n.type==='ib'?'IB':'客户'} · ${esc(n.name||'-')}</b> <span class="muted">CRM ${esc(n.userId)} · ${(n.accounts||[]).length}个账户</span></summary>${own}${children}</details>`}
async function loadDetail(env,ib,start,end){$('detail').hidden=false;$('detailTitle').textContent=`IB ${ib} 树形审计`;$('detailMeta').textContent='正在读取完整证据';$('tree').innerHTML='';$('detail').scrollIntoView({behavior:'smooth'});try{const q=new URLSearchParams({start,end}),d=await json(`/api/rebate-churning/ibs/${encodeURIComponent(env)}/${encodeURIComponent(ib)}?${q}`),r=d.risk||{},s=r.summary||{};$('detailTitle').textContent=`${d.ib.name||'IB'} · ${num(r.score,1)}分 · ${r.level}`;$('detailMeta').textContent=`${d.period.start} 至 ${d.period.end} · ${r.stage} · 置信度${r.confidence}`;$('detailMetrics').innerHTML=[metric('可疑账户',`${num(s.suspiciousAccounts,0)} / ${num(s.accounts,0)}`),metric('订单 / 手数',`${num(s.orders,0)} / ${num(s.lots,2)}`),metric('交易盈亏',money(s.tradeProfit)),metric('当前IB实收',money(s.currentIbRebate)),metric('账户层级总返佣',money(s.hierarchyRebate)),metric('返佣 / 亏损',pct(s.rebateLossCoverage))].join('');$('tree').innerHTML=treeNode(d.tree)}catch(e){$('detailMeta').textContent=e.message}}
$('closeDetail').onclick=()=>{$('detail').hidden=true};init();
</script></body></html>"""


PAGE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>账户刷返佣树形审计</title>
  <style>
    :root{--bg:#eef1f1;--paper:#fff;--ink:#172126;--muted:#68757a;--line:#d8e0e2;--line2:#e8edef;--accent:#087f78;--accent2:#075e59;--warn:#9a5800;--danger:#b42318;--good:#177245;--soft:#f5f8f8}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","Segoe UI",sans-serif;letter-spacing:0}button,input,select{font:inherit;letter-spacing:0}.topbar{height:58px;padding:0 26px;background:#172226;color:#fff;display:flex;align-items:center;justify-content:space-between;gap:14px}.topbar a{color:#eaf0f1;text-decoration:none;font-size:13px}.brand{font-size:17px;font-weight:750}main{width:min(1480px,calc(100% - 32px));margin:18px auto 42px}.panel{background:var(--paper);border:1px solid var(--line);border-top:3px solid var(--accent)}.panel-head{padding:17px 20px;border-bottom:1px solid var(--line)}h1,h2{margin:0;font-size:19px}.query-form{display:grid;grid-template-columns:minmax(180px,1fr) 190px 190px 150px 120px;gap:9px;align-items:end;padding:16px 20px}.query-form label{display:grid;gap:6px;color:var(--muted);font-size:12px}input,select,button{min-height:39px;border:1px solid #b8c4c7;border-radius:5px;background:#fff;color:var(--ink);padding:8px 10px}button{cursor:pointer}button:hover:not(:disabled){border-color:var(--accent);background:#edf8f7}button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}button.primary:hover{background:var(--accent2)}button:disabled{opacity:.55;cursor:not-allowed}.status{min-height:43px;padding:11px 20px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}.candidate-panel{display:grid;grid-template-columns:1fr 110px;gap:9px;padding:14px 20px;border-top:1px solid var(--line);background:var(--soft)}.result{margin-top:16px;background:#fff;border:1px solid var(--line)}.result[hidden],.candidate-panel[hidden]{display:none}.result-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:16px 20px;border-bottom:1px solid var(--line)}.result-meta{margin-top:4px;color:var(--muted);font-size:12px}.tools{display:flex;gap:7px;flex-wrap:wrap}.tools button{min-height:34px;padding:6px 10px}.summary{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));border-bottom:1px solid var(--line)}.metric{min-height:76px;padding:13px 15px;border-right:1px solid var(--line)}.metric:last-child{border-right:0}.metric span{display:block;color:var(--muted);font-size:11px;margin-bottom:5px}.metric b{display:block;font-size:18px;overflow-wrap:anywhere}.negative{color:var(--danger)!important}.positive{color:var(--good)!important}.risk-pill,.relation,.target-flag{display:inline-flex;align-items:center;min-height:23px;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:700}.risk-pill{background:#edf2f2;color:#425156}.risk-pill.warning{background:#fff4d8;color:var(--warn)}.risk-pill.high{background:#ffead5;color:#8b4600}.risk-pill.severe{background:#fde7e5;color:var(--danger)}.relation{background:#e6f2f1;color:var(--accent2)}.target-flag{background:#172226;color:#fff}.breadcrumbs{display:flex;align-items:center;flex-wrap:wrap;gap:5px;padding:11px 20px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}.breadcrumbs b{color:var(--ink)}.tree{padding:12px 20px 22px}.tree-node{margin:6px 0 6px 18px;border-left:2px solid #cbd5d7;padding-left:13px}.tree-node.root{margin-left:0}.tree-node>summary,.account-node>summary{list-style:none;cursor:pointer}.tree-node>summary::-webkit-details-marker,.account-node>summary::-webkit-details-marker{display:none}.node-summary{min-height:48px;display:flex;align-items:center;gap:9px;padding:8px 10px;border:1px solid var(--line);background:#fafcfc}.node-summary:before{content:'▸';width:14px;color:var(--muted)}details[open]>.node-summary:before{content:'▾'}.node-main{min-width:160px;flex:1}.node-main b{font-size:14px}.node-sub{display:block;color:var(--muted);font-size:11px;margin-top:2px}.node-score{font-size:18px;font-weight:800}.node-body{padding:0 0 4px 12px}.risk-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));border:1px solid var(--line2);border-top:0}.risk-item{padding:9px 10px;border-right:1px solid var(--line2)}.risk-item:last-child{border-right:0}.risk-item span{display:block;color:var(--muted);font-size:10px}.risk-item b{display:block;margin-top:3px;font-size:13px}.tags{display:flex;gap:5px;flex-wrap:wrap;padding:8px 0}.tag{padding:2px 6px;border-radius:4px;background:#e9f3f2;color:var(--accent2);font-size:11px}.account-list{margin:7px 0}.account-node{border:1px solid var(--line);border-left:3px solid #9aa8ac;margin:6px 0;background:#fff}.account-node.target{border-left-color:var(--accent)}.account-summary{min-height:45px;display:flex;align-items:center;gap:9px;padding:8px 10px}.account-summary:before{content:'▸';width:14px;color:var(--muted)}.account-node[open]>.account-summary:before{content:'▾'}.account-link{color:var(--accent2);font-weight:800;text-decoration:none}.account-facts{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:11px}.account-detail{display:grid;grid-template-columns:repeat(8,minmax(100px,1fr));border-top:1px solid var(--line);overflow:auto}.account-detail div{padding:9px 10px;border-right:1px solid var(--line2)}.account-detail span{display:block;color:var(--muted);font-size:10px}.account-detail b{display:block;margin-top:3px;font-size:12px}.empty{padding:30px;text-align:center;color:var(--muted)}
    .finance-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));border:1px solid var(--line2);border-top:0;background:#f3f8f7}.finance-grid .risk-item:last-child{border-right:0}
    .account-detail{grid-template-columns:repeat(9,minmax(100px,1fr))}
    @media(max-width:1000px){.query-form{grid-template-columns:1fr 1fr}.query-form button{grid-column:1/-1}.summary{grid-template-columns:repeat(3,1fr)}.metric:nth-child(3n){border-right:0}.risk-grid{grid-template-columns:repeat(3,1fr)}.account-detail{grid-template-columns:repeat(4,minmax(120px,1fr))}}
    @media(max-width:560px){.topbar{padding:0 12px}.brand{font-size:14px}.query-form{grid-template-columns:1fr;padding:13px}.query-form button{grid-column:auto}.panel-head,.status{padding-left:13px;padding-right:13px}.result-head{display:block;padding:13px}.tools{margin-top:10px}.summary{grid-template-columns:1fr 1fr}.metric:nth-child(3n){border-right:1px solid var(--line)}.metric:nth-child(2n){border-right:0}.breadcrumbs{padding:10px 13px}.tree{padding:10px 10px 18px}.tree-node{margin-left:8px;padding-left:7px}.node-summary{align-items:flex-start;flex-wrap:wrap}.node-score{font-size:15px}.risk-grid{grid-template-columns:1fr 1fr}.account-detail{grid-template-columns:repeat(2,minmax(125px,1fr))}}
  </style>
</head>
<body>
  <header class="topbar"><a href="/">← 返回账号工作台</a><div class="brand">刷返佣树形审计</div><span></span></header>
  <main>
    <section class="panel">
      <div class="panel-head"><h1>按交易账户审计</h1></div>
      <form class="query-form" id="accountAuditForm">
        <label>交易账户<input id="auditAccount" inputmode="numeric" autocomplete="off" placeholder="输入MT4 / MT5账户"></label>
        <label>开始时间<input id="auditStart" type="datetime-local"></label>
        <label>结束时间<input id="auditEnd" type="datetime-local"></label>
          <label>环境<select id="auditEnvironment"><option value="">自动识别</option><option value="gb">AC GB</option><option value="cn">AC CN</option><option value="dbg_cn">DBG CN</option><option value="dbg_vn">DBG VN</option></select></label>
        <button class="primary" id="auditBtn">查询并判断</button>
      </form>
      <div class="candidate-panel" id="candidatePanel" hidden><select id="candidateSelect"></select><button id="candidateBtn">使用此账户</button></div>
      <div class="status" id="auditStatus">请输入交易账户</div>
    </section>

    <section class="result" id="auditResult" hidden>
      <div class="result-head"><div><h2 id="resultTitle">审计结果</h2><div class="result-meta" id="resultMeta"></div></div><div class="tools"><button id="expandAllBtn">全部展开</button><button id="collapseAllBtn">全部收起</button></div></div>
      <div class="summary" id="assessmentSummary"></div>
      <div class="breadcrumbs" id="lineagePath"></div>
      <div class="tree" id="auditTree"></div>
    </section>
  </main>
  <script>
    const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const number=(v,d=1)=>Number(v||0).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}),money=v=>number(v,2),pct=v=>number(Number(v||0)*100,1)+'%';
    const state={candidates:[],lastQuery:null};
    function localValue(d){const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`}
    function initDates(){const end=new Date(),start=new Date(end.getTime()-365*86400000);$('auditEnd').value=localValue(end);$('auditStart').value=localValue(start)}
    async function requestJson(url){const response=await fetch(url),data=await response.json();if(!response.ok||data.ok===false){const error=new Error(data.error||'请求失败');error.data=data;error.status=response.status;throw error}return data}
    function levelClass(level){return level==='严重'?'severe':level==='高危'?'high':level==='预警'?'warning':''}
    function metric(label,value,cls=''){return `<div class="metric"><span>${esc(label)}</span><b class="${cls}">${value}</b></div>`}
    function riskItem(label,value,cls=''){return `<div class="risk-item"><span>${esc(label)}</span><b class="${cls}">${value}</b></div>`}
    function renderCandidates(candidates){state.candidates=candidates||[];$('candidatePanel').hidden=!state.candidates.length;$('candidateSelect').innerHTML=state.candidates.map((row,index)=>`<option value="${index}">${esc(row.environmentLabel)} · ${esc(row.server||`服务器${row.serverCode}`)} · ${esc(row.ownerName||'CRM '+row.userId)}</option>`).join('')}
    function renderAccount(account){const combined=Number(account.tradeProfit||0)+Number(account.currentIbRebate||0),profitClass=Number(account.tradeProfit)<0?'negative':'positive',combinedClass=combined<0?'negative':'positive',href=`/account/${encodeURIComponent(account.account)}?platform=${encodeURIComponent(account.platform||'')}&server=${encodeURIComponent(account.server||'')}`;return `<details class="account-node ${account.isTarget?'target':''}" ${account.isTarget?'open':''}><summary class="account-summary"><span>${account.isTarget?'<span class="target-flag">目标账户</span>':''}${account.isHistorical?'<span class="relation">历史账户</span>':''}</span><div class="node-main"><a class="account-link" href="${esc(href)}" target="_blank">${esc(account.account)}</a><span class="node-sub">${esc(account.server||account.platform||'-')} · ${esc(account.typeName||'-')}</span></div><div class="account-facts"><span>${number(account.orders,0)}单</span><span>${number(account.lots,2)}手</span><span>贡献 ${number(account.riskContribution,1)}分</span></div></summary><div class="account-detail"><div><span>区间交易盈亏</span><b class="${profitClass}">${money(account.tradeProfit)}</b></div><div><span>贡献当前IB返佣</span><b>${money(account.currentIbRebate)}</b></div><div><span>IB口径综合收益</span><b class="${combinedClass}">${money(combined)}</b></div><div><span>产生层级返佣</span><b>${money(account.hierarchyRebate)}</b></div><div><span>配对覆盖</span><b>${pct(account.pairCoverage)}</b></div><div><span>同秒覆盖</span><b>${pct(account.sameSecondCoverage)}</b></div><div><span>10秒覆盖</span><b>${pct(account.short10Coverage)}</b></div><div><span>订单/活跃日</span><b>${number(account.ordersPerActiveDay,1)}</b></div><div><span>外部净入金</span><b>${money(account.externalNetDeposit)}</b></div></div><div class="tags">${(account.evidenceTags||[]).map(tag=>`<span class="tag">${esc(tag)}</span>`).join('')}</div></details>`}
    function renderFinancials(node){const f=node.financials||{},tradeClass=Number(f.tradeProfit)<0?'negative':'positive',depositClass=Number(f.externalNetDeposit)<0?'negative':'positive';const items=node.type==='ib'?[['下属账户',number(f.accounts,0)],['区间订单',number(f.orders,0)],['区间手数',number(f.lots,2)],['下属交易盈亏',money(f.tradeProfit),tradeClass],['IB实收返佣',money(f.currentIbRebate)],['IB口径综合收益',money(f.combinedProfit),Number(f.combinedProfit)<0?'negative':'positive'],['下属产生层级返佣',money(f.hierarchyRebate)]]:[['账户数',number(f.accounts,0)],['区间订单',number(f.orders,0)],['区间手数',number(f.lots,2)],['客户交易盈亏',money(f.tradeProfit),tradeClass],['产生层级返佣',money(f.hierarchyRebate)],['外部净入金',money(f.externalNetDeposit),depositClass]];return `<div class="finance-grid">${items.map(item=>riskItem(item[0],item[1],item[2]||'')).join('')}</div>`}
    function renderNode(node,depth=0){const risk=node.risk||null,summary=risk?.summary||{},components=risk?.components||{},riskClass=risk?levelClass(risk.level):'';const financialGrid=renderFinancials(node);const riskGrid=risk?`<div class="risk-grid">${riskItem('结构分',number(components.structure,1))}${riskItem('返佣经济性',number(components.rebateEconomics,1))}${riskItem('IB协同',number(components.ibCoordination,1))}${riskItem('资金闭环',number(components.fundingCycle,1))}${riskItem('反证扣分',number(components.counterevidence,1))}${riskItem('可疑账户',`${number(summary.suspiciousAccounts,0)} / ${number(summary.accounts,0)}`)}</div><div class="tags">${(risk.evidenceTags||[]).map(tag=>`<span class="tag">${esc(tag)}</span>`).join('')}</div>`:'';const accounts=(node.accounts||[]).length?`<div class="account-list">${node.accounts.map(renderAccount).join('')}</div>`:'';const children=(node.children||[]).map(child=>renderNode(child,depth+1)).join('');return `<details class="tree-node ${depth===0?'root':''}" open><summary class="node-summary"><span class="relation">${esc(node.relationship||node.type)}</span><div class="node-main"><b>${esc(node.name||'-')}</b><span class="node-sub">CRM ${esc(node.userId)}${node.ibLevel!==null&&node.ibLevel!==undefined?` · IB L${esc(node.ibLevel)}`:''}</span></div>${risk?`<span class="risk-pill ${riskClass}">${esc(risk.level)}</span><span class="node-score">${number(risk.score,1)}分</span>`:''}</summary><div class="node-body">${financialGrid}${riskGrid}${accounts}${children}</div></details>`}
    function renderAudit(data){const a=data.assessment||{},account=data.account||{},lineage=data.lineage||[],scope=data.scope||{};$('auditResult').hidden=false;$('resultTitle').textContent=`账户 ${account.account} · ${a.level}`;$('resultMeta').textContent=`${account.environmentLabel} · ${account.server||'-'} · ${data.query.start} 至 ${data.query.end} · ${a.stage} · 置信度${a.confidence}`;$('assessmentSummary').innerHTML=[metric('总体评分',`${number(a.score,1)}分`),metric('总体等级',esc(a.level)),metric('直属IB',`CRM ${esc(a.directIbId)}`),metric('直属IB评分',`${number(a.directIbScore,1)}分`),metric('最高风险IB',`${esc(a.highestRiskIbName||'-')} · ${esc(a.highestRiskIbId)}`),metric('所属客户',esc(account.ownerName||account.userId))].join('');$('lineagePath').innerHTML=lineage.map((node,index)=>`${index?'<span>›</span>':''}<b>${node.type==='ib'?'IB':'客户'} ${esc(node.name||node.userId)}</b>`).join('');$('auditTree').innerHTML=renderNode(data.tree);$('auditStatus').textContent=`查询完成 · ${number(scope.customers,0)}位客户 / ${number(scope.accounts,0)}个账户${Number(scope.historicalAccounts||0)?`（含${number(scope.historicalAccounts,0)}个历史账户）`:''} · 评估${data.ibRisks?.length||0}级IB`;renderCandidates([]);$('auditResult').scrollIntoView({behavior:'smooth',block:'start'})}
    async function runAudit(candidate=null){const account=$('auditAccount').value.trim(),start=$('auditStart').value,end=$('auditEnd').value,environment=candidate?.environment??$('auditEnvironment').value,serverCode=candidate?.serverCode??'';if(!account){$('auditStatus').textContent='请输入交易账户';return}if(!start||!end){$('auditStatus').textContent='请选择查询时间';return}$('auditBtn').disabled=true;$('auditStatus').textContent='正在解析账户、IB层级和交易证据...';$('auditResult').hidden=true;renderCandidates([]);const query=new URLSearchParams({start,end});if(environment)query.set('environment',environment);if(serverCode)query.set('serverCode',serverCode);state.lastQuery={account,start,end};try{renderAudit(await requestJson(`/api/rebate-churning/accounts/${encodeURIComponent(account)}?${query}`))}catch(error){$('auditStatus').textContent=error.message;if(error.status===409)renderCandidates(error.data?.candidates||[])}finally{$('auditBtn').disabled=false}}
    $('accountAuditForm').addEventListener('submit',event=>{event.preventDefault();runAudit()});$('candidateBtn').addEventListener('click',()=>{const candidate=state.candidates[Number($('candidateSelect').value||0)];if(candidate)runAudit(candidate)});$('expandAllBtn').addEventListener('click',()=>document.querySelectorAll('#auditTree details').forEach(node=>node.open=true));$('collapseAllBtn').addEventListener('click',()=>document.querySelectorAll('#auditTree details').forEach(node=>node.open=false));initDates();
  </script>
</body>
</html>"""
