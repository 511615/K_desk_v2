from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

from kdesk.domain.position_risk import trade_exposure

MIN_BONUS_TO_CASH_RATIO = 0.20
HEAVY_MARGIN_LEVEL_PERCENT = 200.0
EXTREME_MARGIN_LEVEL_PERCENT = 100.0


class BonusAnalysisCancelled(RuntimeError):
    pass


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise BonusAnalysisCancelled("赠金套利分析已取消")


def number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    for pattern, size in (
        ("%Y-%m-%d %H:%M:%S.%f", 26),
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(text[:size], pattern)
        except ValueError:
            continue
    return None


def _rounded(value: object, digits: int = 2) -> float:
    return round(number(value), digits)


def _ramp(value: object, low: float, high: float, maximum: float) -> float:
    value = number(value)
    if high <= low:
        return maximum if value >= high else 0.0
    return max(0.0, min(maximum, (value - low) / (high - low) * maximum))


def _ratio(numerator: object, denominator: object) -> float:
    return number(numerator) / max(abs(number(denominator)), 1e-9)


def _symbol(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    return text[:6] if len(text) >= 6 else text


def _trade_net(row: dict) -> float:
    if "netProfit" in row:
        return number(row.get("netProfit"))
    return sum(number(row.get(key)) for key in ("profit", "commission", "swap", "fee", "taxes"))


def _event_time(row: dict) -> datetime | None:
    return parse_datetime(row.get("time"))


def _trade_open(row: dict) -> datetime | None:
    cached = row.get("_bonusOpenTime")
    if isinstance(cached, datetime):
        return cached
    opened = parse_datetime(row.get("openTime") or row.get("open_time"))
    if opened is not None:
        row["_bonusOpenTime"] = opened
    return opened


def _trade_close(row: dict) -> datetime | None:
    cached = row.get("_bonusCloseTime")
    if isinstance(cached, datetime):
        return cached
    closed = parse_datetime(row.get("closeTime") or row.get("close_time"))
    if closed is not None:
        row["_bonusCloseTime"] = closed
    return closed


def _format_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def _group_grants(events: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    active_credit = 0.0
    for row in sorted(events, key=lambda item: _event_time(item) or datetime.min):
        kind = row.get("kind")
        amount = number(row.get("amount"))
        if kind == "bonus_grant" and amount > 0:
            if not groups or active_credit <= 1e-6:
                groups.append([])
            groups[-1].append(row)
            active_credit += amount
        elif groups and kind in {"bonus_remove", "bonus_restore"}:
            active_credit = max(active_credit + amount, 0.0)
    return groups


def _paired_deposits(events: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [
        row for row in events
        if row.get("kind") == "deposit"
        and number(row.get("amount")) > 0
        and (when := _event_time(row)) is not None
        and start - timedelta(minutes=5) <= when <= end + timedelta(minutes=5)
    ]


def _cycle_trades(trades: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [
        row for row in trades
        if (opened := _trade_open(row)) is not None
        and opened < end
        and ((_trade_close(row) or end) >= start)
    ]


def _balance_event(row: dict) -> bool:
    if "affectsBalance" in row:
        return bool(row.get("affectsBalance"))
    return row.get("kind") in {"deposit", "withdrawal", "cash_reversal", "transfer", "reset"}


def _credit_event(row: dict) -> bool:
    return row.get("kind") in {"bonus_grant", "bonus_remove", "bonus_restore"}


def _historical_equity(
    profile: dict,
    events: list[dict],
    trades: list[dict],
    point: datetime,
    *,
    after_events: bool,
) -> tuple[float, str, bool]:
    later = (lambda value: value > point) if after_events else (lambda value: value >= point)
    if "balance" in profile:
        balance = number(profile.get("balance"))
        balance -= sum(
            _trade_net(row) for row in trades
            if (closed := _trade_close(row)) is not None and later(closed)
        )
        balance -= sum(
            number(row.get("amount")) for row in events
            if _balance_event(row) and (when := _event_time(row)) is not None and later(when)
        )
        reliable = True
        basis = "按当前余额倒推历史现金权益"
    else:
        balance = sum(
            number(row.get("amount")) for row in events
            if _balance_event(row)
            and (when := _event_time(row)) is not None
            and (when <= point if after_events else when < point)
        )
        reliable = False
        basis = "当前余额缺失，按可见资金流水估算"

    if "credit" in profile:
        credit = number(profile.get("credit")) - sum(
            number(row.get("amount")) for row in events
            if _credit_event(row) and (when := _event_time(row)) is not None and later(when)
        )
    else:
        credit = sum(
            number(row.get("amount")) for row in events
            if _credit_event(row)
            and (when := _event_time(row)) is not None
            and (when <= point if after_events else when < point)
        )
        reliable = False
        basis += "，Credit 按可见流水估算"
    return balance + credit, basis, reliable


def _margin_risk_label(margin_level: float | None) -> str:
    if margin_level is None:
        return "无持仓"
    if margin_level <= EXTREME_MARGIN_LEVEL_PERCENT:
        return "极高爆仓压力"
    if margin_level <= 150.0:
        return "高爆仓压力"
    if margin_level <= HEAVY_MARGIN_LEVEL_PERCENT:
        return "重仓"
    return "未达到重仓线"


def _cycle_margin_pressure(
    profile: dict,
    events: list[dict],
    trades: list[dict],
    start: datetime,
    end: datetime,
    history_trades: list[dict] | None = None,
) -> dict:
    now = datetime.now()
    evaluation_end = min(end, now)
    leverage = max(number(profile.get("leverage")), 1.0)
    active: set[int] = set()
    opens: dict[datetime, list[tuple[int, dict]]] = defaultdict(list)
    closes: dict[datetime, list[tuple[int, dict]]] = defaultdict(list)
    margin_by_index: dict[int, float] = {}
    lots_by_index: dict[int, float] = {}
    unpriced: set[int] = set()
    for row_index, row in enumerate(trades):
        opened = _trade_open(row)
        closed = _trade_close(row)
        if opened is None or opened > evaluation_end or (closed is not None and closed < start):
            continue
        margin_by_index[row_index] = trade_exposure(row) / leverage
        lots_by_index[row_index] = max(number(row.get("volume")), number(row.get("remainingVolume")))
        if number(row.get("openPrice") or row.get("open_price")) <= 0:
            unpriced.add(row_index)
        if opened < start and (closed is None or closed >= start):
            active.add(row_index)
        elif start <= opened <= evaluation_end:
            opens[opened].append((row_index, row))
        if closed is not None and start <= closed <= evaluation_end:
            closes[closed].append((row_index, row))

    equity, equity_basis, equity_reliable = _historical_equity(
        profile, events, history_trades or trades, start, after_events=True,
    )
    equity_changes: dict[datetime, float] = defaultdict(float)
    for row in history_trades or trades:
        closed = _trade_close(row)
        if closed is not None and start < closed <= evaluation_end:
            equity_changes[closed] += _trade_net(row)
    for row in events:
        when = _event_time(row)
        if when is None or not start < when <= evaluation_end:
            continue
        if _balance_event(row) or _credit_event(row):
            equity_changes[when] += number(row.get("amount"))

    used_margin = sum(margin_by_index[index] for index in active)
    concurrent_lots = sum(lots_by_index[index] for index in active)
    active_unpriced = sum(index in unpriced for index in active)
    lowest: dict | None = None

    def record(point: datetime, phase: str, *, allow_current: bool = False) -> None:
        nonlocal lowest
        if not active or used_margin <= 0:
            return
        current_margin = number(profile.get("margin"))
        current_equity = number(profile.get("equity"))
        use_current = allow_current and current_margin > 0 and current_equity != 0
        if use_current:
            state_margin = current_margin
            state_equity = current_equity
            basis = "当前账户实际净值和已用保证金"
            reliable = True
        else:
            state_margin = used_margin
            state_equity = equity
            basis = f"{equity_basis}；按开仓价、合约规模和杠杆估算已用保证金"
            reliable = equity_reliable and active_unpriced == 0
        state = {
            "at": point,
            "phase": phase,
            "equity": state_equity,
            "usedMargin": state_margin,
            "marginLevel": state_equity / state_margin * 100.0,
            "lots": concurrent_lots,
            "orderCount": len(active),
            "basis": basis,
            "reliable": reliable,
        }
        if lowest is None or state["marginLevel"] < lowest["marginLevel"]:
            lowest = state

    points = sorted(set(opens) | set(closes) | set(equity_changes))
    if start not in points:
        record(start, "after")
    for point in points:
        if point < start or point > evaluation_end:
            continue
        if point > start and (closes.get(point) or equity_changes.get(point)):
            record(point, "before")
        for row_index, _row in closes.get(point, []):
            if row_index not in active:
                continue
            active.remove(row_index)
            used_margin -= margin_by_index[row_index]
            concurrent_lots -= lots_by_index[row_index]
            active_unpriced -= int(row_index in unpriced)
        if point > start:
            equity += equity_changes.get(point, 0.0)
        for row_index, _row in opens.get(point, []):
            active.add(row_index)
            used_margin += margin_by_index[row_index]
            concurrent_lots += lots_by_index[row_index]
            active_unpriced += int(row_index in unpriced)
        if opens.get(point) or equity_changes.get(point) or point == start:
            record(point, "after")
    if start <= now <= end:
        record(now, "current", allow_current=True)

    first_open = min((_trade_open(row) for row in trades if _trade_open(row) and _trade_open(row) >= start), default=None)
    if not lowest:
        return {
            "cycleTradeCount": len(trades), "openTradeCount": sum(bool(row.get("isOpen")) for row in trades),
            "firstPostGrantTradeHours": (first_open - start).total_seconds() / 3600.0 if first_open else None,
            "minimumMarginLevel": None, "minimumMarginAt": "", "minimumEquity": None,
            "minimumUsedMargin": None, "minimumConcurrentLots": 0.0, "minimumOrderCount": 0,
            "minimumMarginOrders": [], "minimumMarginOrdersTruncated": False,
            "minimumMarginBasis": "周期内没有可计算保证金水平的持仓", "minimumMarginReliable": False,
            "heavyMarginLevelThreshold": HEAVY_MARGIN_LEVEL_PERCENT, "marginRisk": "无持仓",
        }
    lowest_at = lowest["at"]
    if lowest["phase"] == "before":
        lowest_orders = [
            row for row in trades
            if (opened := _trade_open(row)) is not None and opened < lowest_at
            and ((_trade_close(row) is None) or _trade_close(row) >= lowest_at)
        ]
    else:
        lowest_orders = [
            row for row in trades
            if (opened := _trade_open(row)) is not None and opened <= lowest_at
            and ((_trade_close(row) is None) or _trade_close(row) > lowest_at)
        ]
    order_details = [
        {
            "tradeId": str(row.get("id") or row.get("ticket") or ""),
            "symbol": str(row.get("symbol") or ""),
            "direction": str(row.get("direction") or row.get("type") or "").lower(),
            "volume": _rounded(max(number(row.get("volume")), number(row.get("remainingVolume"))), 4),
            "openPrice": _rounded(row.get("openPrice") or row.get("open_price"), 6),
            "estimatedMargin": _rounded(trade_exposure(row) / leverage),
            "openTime": _format_time(_trade_open(row)),
            "closeTime": _format_time(_trade_close(row)),
            "isOpen": bool(row.get("isOpen")),
            "netProfit": _rounded(_trade_net(row)),
        }
        for row in lowest_orders[:50]
    ]
    return {
        "cycleTradeCount": len(trades),
        "openTradeCount": sum(bool(row.get("isOpen")) for row in trades),
        "firstPostGrantTradeHours": (first_open - start).total_seconds() / 3600.0 if first_open else None,
        "minimumMarginLevel": lowest["marginLevel"],
        "minimumMarginAt": _format_time(lowest["at"]),
        "minimumEquity": lowest["equity"],
        "minimumUsedMargin": lowest["usedMargin"],
        "minimumConcurrentLots": lowest["lots"],
        "minimumOrderCount": lowest["orderCount"],
        "minimumMarginOrders": order_details,
        "minimumMarginOrdersTruncated": lowest["orderCount"] > len(order_details),
        "minimumMarginBasis": lowest["basis"],
        "minimumMarginReliable": lowest["reliable"],
        "heavyMarginLevelThreshold": HEAVY_MARGIN_LEVEL_PERCENT,
        "marginRisk": _margin_risk_label(lowest["marginLevel"]),
    }


def _worst_cumulative_trade_loss(trades: list[dict]) -> tuple[float, datetime | None]:
    settled_by_time: dict[datetime, float] = defaultdict(float)
    for row in trades:
        closed = _trade_close(row)
        if closed is not None:
            settled_by_time[closed] += _trade_net(row)

    running_profit = 0.0
    worst_profit = 0.0
    worst_at = None
    for closed in sorted(settled_by_time):
        running_profit += settled_by_time[closed]
        if running_profit < worst_profit:
            worst_profit = running_profit
            worst_at = closed
    return max(-worst_profit, 0.0), worst_at


def _cycle_peer_matches(
    cycle_trades: list[dict],
    peers: list[dict],
    start: datetime,
    end: datetime,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    subject_lots = sum(max(number(row.get("volume")), 0.0) for row in cycle_trades)
    matched_subject: set[int] = set()
    matched_lots = 0.0
    matches = []
    peer_profit = 0.0
    peer_accounts: set[str] = set()
    for peer in peers:
        _check_cancelled(cancelled)
        account = str(peer.get("account") or "")
        peer_rows = _cycle_trades(peer.get("trades") or [], start, end)
        peer_profit += sum(_trade_net(row) for row in peer_rows)
        used_peer: set[int] = set()
        peer_index: dict[tuple[str, str], list[tuple[datetime, int, dict]]] = defaultdict(list)
        for peer_row_index, peer_trade in enumerate(peer_rows):
            peer_opened = _trade_open(peer_trade)
            peer_direction = str(peer_trade.get("direction") or peer_trade.get("type") or "").lower()
            peer_symbol = _symbol(peer_trade.get("symbol"))
            if peer_opened is None or peer_direction not in {"buy", "sell"} or not peer_symbol:
                continue
            peer_index[(peer_symbol, peer_direction)].append((peer_opened, peer_row_index, peer_trade))
        peer_times: dict[tuple[str, str], list[datetime]] = {}
        for key, values in peer_index.items():
            values.sort(key=lambda value: (value[0], value[1]))
            peer_times[key] = [value[0] for value in values]
        for subject_index, subject in enumerate(cycle_trades):
            if subject_index % 256 == 0:
                _check_cancelled(cancelled)
            opened = _trade_open(subject)
            if subject_index in matched_subject or opened is None:
                continue
            direction = str(subject.get("direction") or subject.get("type") or "").lower()
            opposite = "sell" if direction == "buy" else "buy" if direction == "sell" else ""
            key = (_symbol(subject.get("symbol")), opposite)
            indexed_rows = peer_index.get(key) or []
            indexed_times = peer_times.get(key) or []
            if not indexed_rows:
                continue
            subject_volume = max(number(subject.get("volume")), 0.0)
            candidates = []
            lower = bisect_left(indexed_times, opened - timedelta(seconds=5))
            upper = bisect_right(indexed_times, opened + timedelta(seconds=5))
            for peer_opened, peer_row_index, peer_trade in indexed_rows[lower:upper]:
                if peer_row_index in used_peer:
                    continue
                peer_volume = max(number(peer_trade.get("volume")), 0.0)
                delta = abs((peer_opened - opened).total_seconds())
                volume_match = min(subject_volume, peer_volume) / max(subject_volume, peer_volume, 1e-9)
                if volume_match >= 0.7:
                    candidates.append((delta, -volume_match, peer_row_index, peer_trade))
            if not candidates:
                continue
            delta, _, peer_row_index, peer_trade = min(candidates, key=lambda value: (value[0], value[1], value[2]))
            matched_subject.add(subject_index)
            used_peer.add(peer_row_index)
            matched_lots += subject_volume
            peer_accounts.add(account)
            matches.append({
                "account": account,
                "subjectTrade": str(subject.get("id") or subject.get("ticket") or ""),
                "peerTrade": str(peer_trade.get("id") or peer_trade.get("ticket") or ""),
                "symbol": str(subject.get("symbol") or ""),
                "openDeltaSeconds": _rounded(delta, 3),
                "subjectVolume": _rounded(subject_volume, 4),
                "peerVolume": _rounded(peer_trade.get("volume"), 4),
            })
    return {
        "matches": len(matches),
        "lotCoverage": matched_lots / subject_lots if subject_lots else 0.0,
        "peerProfit": peer_profit,
        "accounts": sorted(peer_accounts),
        "details": matches[:20],
    }


def build_bonus_cycles(
    events: list[dict],
    trades: list[dict],
    peers: list[dict] | None = None,
    cancelled: Callable[[], bool] | None = None,
    profile: dict | None = None,
) -> list[dict]:
    events = sorted((dict(row) for row in events if _event_time(row)), key=lambda row: _event_time(row) or datetime.min)
    trades = [dict(row) for row in trades]
    peers = [
        {**peer, "trades": [dict(row) for row in peer.get("trades") or []]}
        for peer in peers or []
    ]
    profile = dict(profile or {})
    groups = _group_grants(events)
    cycles = []
    for index, grants in enumerate(groups):
        _check_cancelled(cancelled)
        first_grant = _event_time(grants[0])
        last_grant = _event_time(grants[-1])
        if not first_grant or not last_grant:
            continue
        next_grant = _event_time(groups[index + 1][0]) if index + 1 < len(groups) else None
        hard_end = min(first_grant + timedelta(days=120), next_grant) if next_grant else first_grant + timedelta(days=120)
        removals = [
            row for row in events
            if row.get("kind") == "bonus_remove"
            and (when := _event_time(row)) is not None
            and last_grant <= when <= hard_end
        ]
        end = max((_event_time(row) for row in removals), default=None) or hard_end
        paired = _paired_deposits(events, first_grant, last_grant)
        cycle_events = [row for row in events if first_grant - timedelta(minutes=5) <= (_event_time(row) or datetime.min) <= end + timedelta(hours=24)]
        cycle_trades = _cycle_trades(trades, first_grant, end)
        grant_amount = sum(number(row.get("amount")) for row in grants)
        credit_after_grants = [
            row for row in cycle_events
            if row.get("kind") in {"bonus_remove", "bonus_restore"}
            and (_event_time(row) or datetime.min) > last_grant
        ]
        removed_amount = max(-sum(number(row.get("amount")) for row in credit_after_grants), 0.0)
        cash_deposit = sum(number(row.get("amount")) for row in paired)
        margin_pressure = _cycle_margin_pressure(
            profile,
            events,
            cycle_trades,
            first_grant,
            end,
            trades,
        )
        # Preserve old snapshot fields so completed jobs and older clients remain readable.
        compatibility_peak = {
            "earlyTradeCount": margin_pressure["cycleTradeCount"],
            "earlyPeakConcurrentLots": margin_pressure["minimumConcurrentLots"],
            "earlyPeakAt": margin_pressure["minimumMarginAt"],
            "earlyPeakOrderCount": margin_pressure["minimumOrderCount"],
            "earlyPeakOrders": margin_pressure["minimumMarginOrders"],
            "earlyPeakOrdersTruncated": margin_pressure["minimumMarginOrdersTruncated"],
            "earlyPeakLotsPerThousandFunded": _ratio(
                margin_pressure["minimumConcurrentLots"], cash_deposit + grant_amount,
            ) * 1000 if cash_deposit + grant_amount > 0 else 0.0,
        }
        later_cash = [
            row for row in cycle_events
            if row not in paired and row.get("kind") in {"deposit", "withdrawal", "cash_reversal"}
        ]
        net_later_cash = sum(number(row.get("amount")) for row in later_cash)
        transfer_out = sum(abs(min(number(row.get("amount")), 0.0)) for row in cycle_events if row.get("kind") == "transfer")
        transfer_in = sum(max(number(row.get("amount")), 0.0) for row in cycle_events if row.get("kind") == "transfer")
        extracted = max(-net_later_cash, 0.0) + max(transfer_out - transfer_in, 0.0)
        net_profit = sum(_trade_net(row) for row in cycle_trades)
        worst_trade_loss, worst_trade_loss_at = _worst_cumulative_trade_loss(cycle_trades)
        lots = sum(max(number(row.get("volume")), 0.0) for row in cycle_trades)
        wins = sum(_trade_net(row) > 0 for row in cycle_trades)
        losses = sum(_trade_net(row) < 0 for row in cycle_trades)
        close_times = [value for row in cycle_trades if (value := _trade_close(row))]
        open_times = [value for row in cycle_trades if (value := _trade_open(row))]
        last_trade = max(close_times, default=max(open_times, default=last_grant))
        extraction_events = [
            row for row in cycle_events
            if row.get("kind") in {"withdrawal", "transfer"} and number(row.get("amount")) < 0 and _event_time(row)
        ]
        first_extraction = min((_event_time(row) for row in extraction_events), default=None)
        expected_extraction = cash_deposit + max(net_profit, 0.0)
        running_outflow = 0.0
        outflow_candidates = []
        for row in sorted(later_cash + [item for item in cycle_events if item.get("kind") == "transfer"], key=lambda item: _event_time(item) or datetime.min):
            running_outflow += number(row.get("amount"))
            if running_outflow < 0:
                outflow_candidates.append(abs(running_outflow))
        attempted_extraction = max(outflow_candidates, default=0.0)
        matched_extraction = min(
            [value for value in [extracted, *outflow_candidates] if value > 0],
            key=lambda value: abs(value - expected_extraction),
            default=0.0,
        )
        extraction_match = max(0.0, 1.0 - abs(matched_extraction - expected_extraction) / max(expected_extraction, 1.0)) if matched_extraction else 0.0
        counterpart_accounts = sorted({
            str(row.get("counterparty")) for row in cycle_events
            if row.get("kind") == "transfer" and str(row.get("counterparty") or "").strip()
        })
        reset_events = [row for row in cycle_events if row.get("kind") == "reset"]
        peer_match = _cycle_peer_matches(cycle_trades, peers, first_grant, end, cancelled)
        first_trade = min(open_times, default=last_grant)
        cycle_finish = max([last_trade, *[_event_time(row) for row in removals if _event_time(row)], *[_event_time(row) for row in extraction_events if _event_time(row)]])
        cycles.append({
            "started": _format_time(first_grant),
            "ended": _format_time(cycle_finish),
            "durationHours": max((cycle_finish - first_grant).total_seconds() / 3600.0, 0.0),
            "riskEpisodeHours": max((last_trade - min(first_grant, first_trade)).total_seconds() / 3600.0, 0.0),
            "grantAmount": grant_amount,
            "grantCount": len(grants),
            "cashDeposit": cash_deposit,
            "bonusToCash": _ratio(grant_amount, cash_deposit) if cash_deposit else 0.0,
            "removedAmount": removed_amount,
            "bonusRemovalRatio": min(_ratio(removed_amount, grant_amount), 1.5) if grant_amount else 0.0,
            "trades": len(cycle_trades),
            "wins": wins,
            "losses": losses,
            "winRate": wins / len(cycle_trades) if cycle_trades else 0.0,
            "netProfit": net_profit,
            "totalLots": lots,
            "maxLot": max((number(row.get("volume")) for row in cycle_trades), default=0.0),
            **margin_pressure,
            **compatibility_peak,
            "profitToCash": _ratio(max(net_profit, 0.0), cash_deposit) if cash_deposit else 0.0,
            "depletionRatio": _ratio(max(-net_profit, 0.0), cash_deposit + grant_amount) if cash_deposit + grant_amount else 0.0,
            "worstTradeLoss": worst_trade_loss,
            "worstTradeLossAt": _format_time(worst_trade_loss_at),
            "worstDepletionRatio": _ratio(worst_trade_loss, cash_deposit + grant_amount) if cash_deposit + grant_amount else 0.0,
            "resetCount": len(reset_events),
            "resetAmount": sum(abs(number(row.get("amount"))) for row in reset_events),
            "resetEventIds": [str(row.get("id") or "") for row in reset_events if row.get("id")][:20],
            "resetEvents": [
                {
                    "id": str(row.get("id") or ""),
                    "time": _format_time(_event_time(row)),
                    "amount": _rounded(row.get("amount")),
                    "comment": str(row.get("comment") or ""),
                }
                for row in reset_events[:10]
            ],
            "extracted": extracted,
            "attemptedExtraction": attempted_extraction,
            "matchedExtraction": matched_extraction,
            "extractionBasis": "actual" if matched_extraction == extracted else "attempted",
            "extractionMatch": extraction_match,
            "cashoutLatencyHours": (first_extraction - last_trade).total_seconds() / 3600.0 if first_extraction and last_trade else None,
            "transferIn": transfer_in,
            "transferOut": transfer_out,
            "counterpartAccounts": counterpart_accounts,
            "peerMatch": peer_match,
            "eventIds": [str(row.get("id") or "") for row in cycle_events if row.get("id")][:30],
            "tradeIds": [str(row.get("id") or row.get("ticket") or "") for row in cycle_trades[:30]],
        })
    return cycles


def _score_cycle(cycle: dict) -> dict:
    paired = number(cycle.get("cashDeposit")) > 0
    bonus_ratio = number(cycle.get("bonusToCash"))
    bonus_ratio_eligible = paired and bonus_ratio + 1e-9 >= MIN_BONUS_TO_CASH_RATIO
    profit_ratio = number(cycle.get("profitToCash"))
    removal_ratio = number(cycle.get("bonusRemovalRatio"))
    extraction_match = number(cycle.get("extractionMatch"))
    duration_hours = number(cycle.get("riskEpisodeHours") or cycle.get("durationHours"))
    trades = int(number(cycle.get("trades")))
    win_rate = number(cycle.get("winRate"))
    depletion = number(cycle.get("depletionRatio"))
    worst_depletion = number(cycle.get("worstDepletionRatio"))
    peer_coverage = number((cycle.get("peerMatch") or {}).get("lotCoverage"))
    counterparts = cycle.get("counterpartAccounts") or []
    minimum_margin_level = cycle.get("minimumMarginLevel")
    high_bonus_heavy_position = (
        bonus_ratio_eligible
        and minimum_margin_level is not None
        and number(minimum_margin_level, float("inf")) <= HEAVY_MARGIN_LEVEL_PERCENT
    )
    coordinated_heavy_position = high_bonus_heavy_position and peer_coverage >= 0.4
    ever_funding_breach = bonus_ratio_eligible and (
        int(number(cycle.get("resetCount"))) > 0
        or worst_depletion >= 1.0
        or bool(cycle.get("currentNegativeAccount"))
    )
    near_funding_breach = bonus_ratio_eligible and not ever_funding_breach and worst_depletion >= 0.75
    breach_evidence = []
    if int(number(cycle.get("resetCount"))) > 0:
        breach_evidence.append("历史记录出现负余额清零或重置")
    if worst_depletion >= 1.0:
        breach_evidence.append("历史累计交易亏损一度超过本轮本金与赠金")
    if cycle.get("currentNegativeAccount"):
        breach_evidence.append("当前余额或净值仍为负数")

    funding = 5.0 + (5.0 if paired else 0.0)
    closure = _ramp(removal_ratio, 0.25, 1.0, 8.0)
    closure += _ramp(extraction_match, 0.35, 0.95, 14.0)
    closure += _ramp(14 * 24 - duration_hours, 0, 13 * 24, 8.0)
    economics = _ramp(profit_ratio, 0.15, 1.0, 17.0)
    economics += _ramp(win_rate if trades >= 3 else 0.0, 0.55, 0.95, 8.0)
    lots_per_thousand = _ratio(cycle.get("totalLots"), max(number(cycle.get("cashDeposit")), 50.0)) * 1000
    economics += _ramp(lots_per_thousand, 1.0, 12.0, 7.0)
    economics += _ramp(depletion, 0.45, 1.0, 15.0)
    peer_coordination = _ramp(peer_coverage, 0.2, 0.8, 10.0)
    coordination = peer_coordination + (5.0 if counterparts else 0.0)
    score = funding + closure + min(economics, 35.0) + coordination

    extractor = bonus_ratio_eligible and trades >= 1 and profit_ratio >= 0.2 and extraction_match >= 0.65 and (removal_ratio >= 0.5 or bool(counterparts))
    sacrifice = bonus_ratio_eligible and trades >= 1 and worst_depletion >= 0.75 and duration_hours <= 7 * 24
    coordinated_sacrifice = sacrifice and peer_coverage >= 0.4
    profit_locked = (
        bonus_ratio_eligible
        and bonus_ratio >= 0.5
        and trades >= 3
        and profit_ratio >= 0.5
        and win_rate >= 0.85
        and removal_ratio >= 0.8
        and duration_hours <= 14 * 24
    )
    if extractor:
        score = max(score, 75.0)
    if extractor and extraction_match >= 0.85 and (profit_ratio >= 1.0 or duration_hours <= 24):
        score = max(score, 90.0)
    if sacrifice and not coordinated_sacrifice and not extractor:
        score = min(score, 59.0)
    elif coordinated_sacrifice:
        score = max(score, 75.0)
    if profit_locked and not extractor:
        score = max(score, 60.0)
    if near_funding_breach:
        score = max(score, 60.0)
    if high_bonus_heavy_position:
        # A visible opposite account strengthens confidence, but does not control this path's score.
        score = max(score - peer_coordination, 75.0)
    if ever_funding_breach:
        score = max(score, 90.0)
    if (
        not extractor
        and not sacrifice
        and not profit_locked
        and not high_bonus_heavy_position
        and not near_funding_breach
        and not ever_funding_breach
        and extraction_match < 0.35
    ):
        score = min(score, 59.0)
    if not bonus_ratio_eligible:
        score = min(score, 39.0)
    return {
        "score": min(max(score, 0.0), 100.0),
        "bonusRatioEligible": bonus_ratio_eligible,
        "requiredBonusToCash": MIN_BONUS_TO_CASH_RATIO,
        "highBonusHeavyPosition": high_bonus_heavy_position,
        "coordinatedHeavyPosition": coordinated_heavy_position,
        "everFundingBreach": ever_funding_breach,
        "nearFundingBreach": near_funding_breach,
        "breachEvidence": breach_evidence,
        "extractor": extractor,
        "sacrifice": sacrifice,
        "coordinatedSacrifice": coordinated_sacrifice,
        "profitLocked": profit_locked,
        "lotsPerThousand": lots_per_thousand,
    }


def _level(score: float) -> str:
    if score >= 90:
        return "严重形态"
    if score >= 75:
        return "高危形态"
    if score >= 60:
        return "预警"
    if score >= 40:
        return "关注"
    return "无明显风险"


def detect_bonus_arbitrage(
    profile: dict,
    events: list[dict],
    trades: list[dict],
    peers: list[dict] | None = None,
    *,
    stage: str = "deep",
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    cycles = build_bonus_cycles(events, trades, peers, cancelled, profile)
    if cycles and (number(profile.get("balance")) < 0 or number(profile.get("equity")) < 0):
        latest_cycle = max(cycles, key=lambda cycle: parse_datetime(cycle.get("started")) or datetime.min)
        latest_cycle["currentNegativeAccount"] = True
        latest_cycle["currentBalance"] = number(profile.get("balance"))
        latest_cycle["currentEquity"] = number(profile.get("equity"))
    scored = [{**cycle, **_score_cycle(cycle)} for cycle in cycles]
    strong_cycles = [cycle for cycle in scored if number(cycle.get("score")) >= 75]
    best = max(scored, key=lambda cycle: number(cycle.get("score")), default=None)
    score = number(best.get("score")) if best else 0.0
    repeated_extractors = sum(bool(cycle.get("extractor")) for cycle in scored)
    if repeated_extractors >= 3:
        score = max(score, 92.0)
    elif repeated_extractors >= 2:
        score = max(score, 85.0)
    if not cycles:
        score = 0.0

    triggers = []
    if best:
        if best.get("everFundingBreach"):
            details = "；".join(best.get("breachEvidence") or [])
            triggers.append(f"赠金周期内曾经出现穿仓或负余额证据：{details}")
        elif best.get("nearFundingBreach"):
            triggers.append("历史累计亏损一度消耗本轮本金与赠金的75%以上，已经接近穿仓")
        if best.get("highBonusHeavyPosition"):
            triggers.append(
                f"赠金有效周期内最低保证金水平 {_rounded(best.get('minimumMarginLevel'), 1)}%，"
                f"低于或等于 {HEAVY_MARGIN_LEVEL_PERCENT:.0f}% 重仓线，直接进入重点风险"
            )
            if best.get("coordinatedHeavyPosition"):
                triggers.append("可见关联账户存在同步反向订单，进一步提高判断确信度")
        if best.get("extractor"):
            triggers.append("赠金、交易盈利、资金提取与 Credit 撤销形成完整闭环")
        if best.get("coordinatedSacrifice"):
            triggers.append("本账户快速消耗本金和赠金，并与关联账户出现反向同步交易")
        elif best.get("sacrifice"):
            triggers.append("本账户快速消耗本金和赠金，但尚未找到对应盈利腿")
        if best.get("profitLocked") and not best.get("extractor"):
            triggers.append("高赠金占比下短期稳定获利且 Credit 已撤销，但尚未发生资金提取")
        if best.get("counterpartAccounts"):
            triggers.append("资金通过内部转账流向或来自可识别关联账户")
        if repeated_extractors >= 2:
            triggers.append(f"发现 {repeated_extractors} 个重复套利资金周期")

    limitations = ["未读取具体活动条款和赠金适用规则，命中表示行为高度可疑，不等同于已确认违规。"]
    if best and not best.get("bonusRatioEligible"):
        limitations.append(
            f"最强周期赠金 / 入金仅 {_rounded(number(best.get('bonusToCash')) * 100, 1)}%，"
            f"未达到 {_rounded(MIN_BONUS_TO_CASH_RATIO * 100, 1)}% 硬门槛，不进入赠金套利风险等级。"
        )
    if best and best.get("sacrifice") and not best.get("coordinatedSacrifice"):
        if best.get("highBonusHeavyPosition"):
            limitations.append("尚未找到同步盈利账户，但赠金周期重仓本身已进入重点风险，仍需人工确认是否存在外部对锁。")
        elif best.get("nearFundingBreach"):
            limitations.append("尚未找到同步盈利账户，但历史上曾接近穿仓，仍保留预警并要求人工复核。")
        else:
            limitations.append("牺牲账户尚未找到同步盈利账户，按规则不进入预警或高危结论。")
    if best and best.get("highBonusHeavyPosition") and not best.get("coordinatedHeavyPosition"):
        limitations.append("未在可见关联账户中找到同步反向订单；跨平台对锁可能不可见，因此风险不降级并要求人工确认。")
    if best and best.get("profitLocked") and not best.get("extractor"):
        limitations.append("收益尚未提款或转出，因此只进入预警，不进入高危结论。")
    if not cycles:
        limitations.append("检测范围内没有识别到明确的历史赠金发放记录。")
    if profile.get("sourceAmbiguous"):
        limitations.append("同一账号存在多个服务器归属，本次结果没有唯一数据源。")
    if not peers:
        limitations.append("没有可查询的同客户或资金关联账户，无法验证外部对冲腿。")

    if not best:
        summary = "检测范围内未形成可分析的赠金资金周期"
    elif not best.get("bonusRatioEligible"):
        summary = (
            f"{best['started']} 起：赠金 / 入金 {_rounded(number(best['bonusToCash']) * 100, 1)}%，"
            f"低于 {_rounded(MIN_BONUS_TO_CASH_RATIO * 100, 1)}% 硬门槛，不认定为赠金套利周期"
        )
    elif best.get("everFundingBreach"):
        breach_details = "；".join(best.get("breachEvidence") or [])
        summary = (
            f"{best['started']} 起：本轮本金与赠金合计 "
            f"{_rounded(number(best['cashDeposit']) + number(best['grantAmount']))}，"
            f"历史最大累计亏损 {_rounded(best.get('worstTradeLoss'))}，"
            f"消耗比例 {_rounded(number(best.get('worstDepletionRatio')) * 100, 1)}%；"
            f"{breach_details}"
        )
    elif best.get("highBonusHeavyPosition"):
        summary = (
            f"{best['started']} 起：赠金 / 入金 {_rounded(number(best['bonusToCash']) * 100, 1)}%，"
            f"赠金周期内最低保证金水平 {_rounded(best.get('minimumMarginLevel'), 1)}%，"
            f"当时净值 {_rounded(best.get('minimumEquity'))}、已用保证金 {_rounded(best.get('minimumUsedMargin'))}，"
            f"并发 {_rounded(best.get('minimumConcurrentLots'), 2)} 手，已进入重点风险"
        )
    elif best.get("extractor"):
        summary = (
            f"{best['started']} 起：入金 {_rounded(best['cashDeposit'])}、赠金 {_rounded(best['grantAmount'])}，"
            f"交易净利 {_rounded(best['netProfit'])}，随后提取或申请提取 {_rounded(best['matchedExtraction'])}，"
            f"资金闭环匹配度 {_rounded(number(best['extractionMatch']) * 100, 1)}%"
        )
    elif best.get("nearFundingBreach"):
        summary = (
            f"{best['started']} 起：本轮本金与赠金合计 "
            f"{_rounded(number(best['cashDeposit']) + number(best['grantAmount']))}，"
            f"历史最大累计亏损 {_rounded(best.get('worstTradeLoss'))}，"
            f"一度消耗 {_rounded(number(best.get('worstDepletionRatio')) * 100, 1)}%，接近穿仓"
        )
    elif best.get("sacrifice"):
        summary = (
            f"{best['started']} 起：本金与赠金合计 {_rounded(number(best['cashDeposit']) + number(best['grantAmount']))}，"
            f"短期交易亏损 {_rounded(abs(number(best['netProfit'])))}，消耗比例 {_rounded(number(best['depletionRatio']) * 100, 1)}%"
        )
    elif best.get("profitLocked"):
        summary = (
            f"{best['started']} 起：赠金 / 入金 {_rounded(number(best['bonusToCash']) * 100, 1)}%，"
            f"{best['trades']} 笔交易胜率 {_rounded(number(best['winRate']) * 100, 1)}%，"
            f"净利 {_rounded(best['netProfit'])} 后 Credit 已撤销，但未发现提款"
        )
    else:
        summary = (
            f"识别到 {len(cycles)} 个赠金周期，但最强周期尚未同时满足盈利提取、赠金撤销或关联对冲证据"
        )

    evidence_cycles = []
    for cycle in sorted(scored, key=lambda item: number(item.get("score")), reverse=True)[:10]:
        evidence_cycles.append({
            key: cycle.get(key) for key in (
                "started", "ended", "durationHours", "cashDeposit", "grantAmount", "bonusToCash",
                "bonusRatioEligible", "requiredBonusToCash",
                "cycleTradeCount", "openTradeCount", "firstPostGrantTradeHours",
                "minimumMarginLevel", "minimumMarginAt", "minimumEquity", "minimumUsedMargin",
                "minimumConcurrentLots", "minimumOrderCount", "minimumMarginOrders",
                "minimumMarginOrdersTruncated", "minimumMarginBasis", "minimumMarginReliable",
                "heavyMarginLevelThreshold", "marginRisk",
                "earlyTradeCount",
                "earlyPeakConcurrentLots", "earlyPeakAt", "earlyPeakOrderCount", "earlyPeakOrders",
                "earlyPeakOrdersTruncated", "earlyPeakLotsPerThousandFunded", "maxLot",
                "removedAmount", "bonusRemovalRatio", "trades", "wins", "losses", "netProfit", "riskEpisodeHours",
                "totalLots", "profitToCash", "depletionRatio", "worstTradeLoss", "worstTradeLossAt",
                "worstDepletionRatio", "resetCount", "resetAmount", "resetEventIds", "resetEvents", "currentNegativeAccount",
                "currentBalance", "currentEquity", "everFundingBreach", "nearFundingBreach", "breachEvidence",
                "extracted", "extractionMatch",
                "attemptedExtraction", "matchedExtraction", "extractionBasis",
                "cashoutLatencyHours", "counterpartAccounts", "peerMatch", "score", "extractor",
                "sacrifice", "coordinatedSacrifice", "profitLocked",
                "highBonusHeavyPosition", "coordinatedHeavyPosition", "eventIds", "tradeIds",
            )
        })
    best_metrics = best or {}
    confidence = 90 if best and best.get("everFundingBreach") else 82 if best and (
        best.get("extractor") or best.get("coordinatedSacrifice") or best.get("coordinatedHeavyPosition")
    ) else 75 if best and best.get("highBonusHeavyPosition") else 70 if best and (
        best.get("profitLocked") or best.get("nearFundingBreach")
    ) else 62 if cycles else 35
    final_score = _rounded(score, 1)
    return {
        "type": "bonus_arbitrage",
        "label": "赠金套利",
        "score": final_score,
        "level": _level(final_score),
        "stage": stage,
        "confidence": confidence,
        "summary": summary,
        "metrics": [
            {"label": "历史赠金周期", "value": len(cycles)},
            {"label": "高危周期", "value": len(strong_cycles)},
            {"label": "最强周期赠金 / 入金", "value": f"{_rounded(number(best_metrics.get('bonusToCash')) * 100, 1)}%"},
            {"label": "周期最低保证金水平", "value": f"{_rounded(best_metrics.get('minimumMarginLevel'), 1)}%" if best_metrics.get("minimumMarginLevel") is not None else "无持仓"},
            {"label": "最低点并发手数", "value": _rounded(best_metrics.get("minimumConcurrentLots"), 2)},
            {"label": "最低点已用保证金", "value": _rounded(best_metrics.get("minimumUsedMargin"), 2)},
            {"label": "历史最大亏损 / 本轮资金", "value": f"{_rounded(number(best_metrics.get('worstDepletionRatio')) * 100, 1)}%"},
            {"label": "历史负余额处理", "value": int(number(best_metrics.get("resetCount")))},
            {"label": "最强周期盈利 / 入金", "value": f"{_rounded(number(best_metrics.get('profitToCash')) * 100, 1)}%"},
            {"label": "最强周期资金闭环", "value": f"{_rounded(number(best_metrics.get('extractionMatch')) * 100, 1)}%"},
        ],
        "triggeredRules": triggers,
        "evidenceOrders": list(best_metrics.get("tradeIds") or []),
        "evidence": {"cycles": evidence_cycles},
        "limitations": limitations,
        "requiresTick": False,
        "analysis": [{"title": "资金周期证据", "detail": trigger} for trigger in triggers],
        "source": {
            "platform": str(profile.get("platform") or ""),
            "server": str(profile.get("server") or ""),
            "currency": str(profile.get("currency") or ""),
            "moneyScale": number(profile.get("moneyScale"), 1.0),
        },
    }
