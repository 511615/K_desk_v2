from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

TARGET_TYPES = ("weekend_gap_trading", "open_betting")
OPPOSITE_LOT_SIMILARITY_THRESHOLD = 0.8
TYPE_LABELS = {
    "weekend_gap_trading": "周末跳空交易",
    "open_betting": "赌开盘",
}


def number(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip().replace("T", " ").removesuffix("Z")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def canonical_symbol(value: object) -> str:
    normalized = "".join(character for character in str(value or "").upper() if character.isalnum())
    known_bases = (
        "XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
        "EURJPY", "EURGBP", "EURCHF", "EURAUD", "EURCAD", "EURNZD", "GBPJPY", "GBPCHF", "GBPAUD",
        "GBPCAD", "GBPNZD", "AUDJPY", "AUDCAD", "AUDCHF", "AUDNZD", "NZDJPY", "NZDCAD", "NZDCHF",
        "CADJPY", "CADCHF", "CHFJPY",
    )
    return next((base for base in known_bases if normalized.startswith(base)), normalized)


def match_synchronized_peer_orders(
    target_orders: list[dict], peer_orders: list[dict], *, tolerance_seconds: int = 5,
    opposite_lot_similarity: float = OPPOSITE_LOT_SIMILARITY_THRESHOLD,
) -> dict:
    """Match fully closed synchronized peers; opposite legs must also have similar lots."""
    same_matches: list[dict] = []
    opposite_matches: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    peer_index: dict[tuple[str, int], list[tuple[dict, datetime, datetime]]] = defaultdict(list)
    for peer in peer_orders:
        peer_open = parse_datetime(peer.get("openTime"))
        peer_close = parse_datetime(peer.get("closeTime"))
        if peer_open and peer_close and peer.get("fullyClosed", True):
            peer_index[(canonical_symbol(peer.get("symbol")), int(peer_open.timestamp()))].append(
                (peer, peer_open, peer_close)
            )
    for target in target_orders:
        target_open = parse_datetime(target.get("openTime"))
        target_close = parse_datetime(target.get("closeTime"))
        if not target_open or not target_close:
            continue
        target_direction = str(target.get("direction") or "").lower()
        target_symbol = canonical_symbol(target.get("symbol"))
        nearby_peers = (
            item
            for second in range(int(target_open.timestamp()) - tolerance_seconds, int(target_open.timestamp()) + tolerance_seconds + 1)
            for item in peer_index.get((target_symbol, second), [])
        )
        for peer, peer_open, peer_close in nearby_peers:
            open_delta = abs((peer_open - target_open).total_seconds())
            close_delta = abs((peer_close - target_close).total_seconds())
            if open_delta > tolerance_seconds or close_delta > tolerance_seconds:
                continue
            peer_direction = str(peer.get("direction") or "").lower()
            relation = "same" if peer_direction == target_direction else "opposite"
            target_volume = number(target.get("volume"))
            peer_volume = number(peer.get("volume"))
            lot_similarity = min(target_volume, peer_volume) / max(target_volume, peer_volume, 1e-9)
            if relation == "opposite" and lot_similarity < opposite_lot_similarity:
                continue
            key = (
                str(target.get("orderId") or ""), str(peer.get("physicalSource") or ""),
                str(peer.get("account") or ""), str(peer.get("orderId") or ""),
                str(peer.get("dealId") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            match = {
                "relation": relation,
                "account": str(peer.get("account") or ""),
                "platform": str(peer.get("platform") or ""),
                "server": str(peer.get("server") or ""),
                "database": str(peer.get("database") or ""),
                "physicalSource": str(peer.get("physicalSource") or ""),
                "orderId": str(peer.get("orderId") or ""),
                "positionId": str(peer.get("positionId") or ""),
                "dealId": str(peer.get("dealId") or ""),
                "targetOrderId": str(target.get("orderId") or ""),
                "targetPositionId": str(target.get("positionId") or ""),
                "symbol": str(peer.get("symbol") or target.get("symbol") or ""),
                "direction": peer_direction,
                "targetDirection": target_direction,
                "volume": _round(peer_volume),
                "targetVolume": _round(target_volume),
                "lotSimilarity": _round(lot_similarity, 4),
                "lotSimilarityPct": _round(lot_similarity * 100, 1),
                "openTime": peer_open.strftime("%Y-%m-%d %H:%M:%S"),
                "closeTime": peer_close.strftime("%Y-%m-%d %H:%M:%S"),
                "targetOpenTime": target_open.strftime("%Y-%m-%d %H:%M:%S"),
                "targetCloseTime": target_close.strftime("%Y-%m-%d %H:%M:%S"),
                "openDeltaSeconds": _round(open_delta, 3),
                "closeDeltaSeconds": _round(close_delta, 3),
            }
            (same_matches if relation == "same" else opposite_matches).append(match)

    def account_key(row: dict) -> tuple[str, str, str]:
        return row["platform"], row["server"], row["account"]
    same_matches.sort(key=account_key)
    opposite_matches.sort(key=account_key)
    same_accounts = sorted({row["account"] for row in same_matches})
    opposite_accounts = sorted({row["account"] for row in opposite_matches})
    same_total = len(same_matches)
    opposite_total = len(opposite_matches)
    detail_limit = 500
    return {
        "sameDirectionAccounts": same_accounts,
        "oppositeDirectionAccounts": opposite_accounts,
        "peerAccounts": same_accounts,
        "sameDirectionMatchTotal": same_total,
        "oppositeDirectionMatchTotal": opposite_total,
        "peerMatchDetailLimit": detail_limit,
        "peerMatchesTruncated": same_total > detail_limit or opposite_total > detail_limit,
        "oppositeLotSimilarityThreshold": opposite_lot_similarity,
        "sameDirectionMatches": same_matches[:detail_limit],
        "oppositeDirectionMatches": opposite_matches[:detail_limit],
    }


def _round(value: float, digits: int = 2) -> float:
    return round(number(value), digits)


def _level(score: float) -> str:
    if score >= 90:
        return "严重形态"
    if score >= 75:
        return "高风险"
    if score >= 60:
        return "预警"
    if score >= 40:
        return "关注"
    return "未见明显"


def _symbol_contract(symbol: str) -> float:
    normalized = "".join(character for character in str(symbol or "").upper() if character.isalnum())
    if normalized.startswith("XAU"):
        return 100.0
    if normalized.startswith("XAG"):
        return 5_000.0
    if any(token in normalized for token in ("OIL", "WTI", "BRENT", "XTI", "XBR")):
        return 1_000.0
    if len(normalized) >= 6 and normalized[:6].isalpha():
        return 100_000.0
    return 1.0


def trade_exposure(trade: dict) -> float:
    """Estimate account-currency notional from realized sensitivity, then contract metadata."""
    open_price = abs(number(trade.get("openPrice") or trade.get("open_price")))
    close_price = abs(number(trade.get("closePrice") or trade.get("close_price")))
    profit = abs(number(trade.get("profit")))
    if open_price > 0 and close_price > 0:
        price_return = abs(close_price - open_price) / open_price
        if price_return >= 0.00001 and profit >= 0.01:
            return profit / price_return
    volume = max(number(trade.get("volume")), number(trade.get("remainingVolume")))
    contract = number(trade.get("contractSize") or trade.get("contract_size")) or _symbol_contract(
        str(trade.get("symbol") or "")
    )
    return max(volume * contract * max(open_price, 1.0), 0.0)


def _net_profit(trade: dict) -> float:
    if trade.get("netProfit") is not None:
        return number(trade.get("netProfit"))
    return sum(number(trade.get(key)) for key in ("profit", "commission", "fee", "swap", "taxes"))


def _trade_times(trade: dict, *, now: datetime) -> tuple[datetime | None, datetime | None]:
    opened = parse_datetime(trade.get("openTime") or trade.get("open_time_msc") or trade.get("open_time"))
    closed = parse_datetime(trade.get("closeTime") or trade.get("close_time_msc") or trade.get("close_time"))
    if opened and (not closed or closed <= opened) and trade.get("isOpen"):
        closed = now
    return opened, closed


def _entry_orders(trade: dict) -> list[dict]:
    rows = list(trade.get("entryOrders") or [])
    if rows:
        return rows
    return [{
        "orderId": str(trade.get("ticket") or trade.get("id") or ""),
        "dealId": "",
        "time": trade.get("openTime") or trade.get("open_time_msc") or trade.get("open_time"),
        "volume": number(trade.get("volume")),
        "price": number(trade.get("openPrice") or trade.get("open_price")),
    }]


def _is_negative_balance_adjustment(item: dict) -> bool:
    comment = str(item.get("comment") or "").strip().upper()
    return any(token in comment for token in (
        "NEGATIVE BALANCE", "ZERO BALANCE", "NEGATIVE BALANCE PROTECTION", "NBP", "RST-",
    ))


def _is_open_window(value: datetime) -> bool:
    minute = value.hour * 60 + value.minute
    return 21 * 60 + 45 <= minute <= 22 * 60 + 30


def _is_weekend_trade(opened: datetime, closed: datetime | None) -> bool:
    return bool(
        closed
        and opened.weekday() == 4
        and opened.hour >= 18
        and closed - opened >= timedelta(hours=30)
        and closed.weekday() in {6, 0}
    )


def _cluster_ratio(values: list[tuple[datetime, float]], seconds: int = 300) -> float:
    total = sum(weight for _, weight in values)
    if total <= 0 or not values:
        return 0.0
    values = sorted(values)
    left = 0
    running = 0.0
    maximum = 0.0
    for _right, (when, weight) in enumerate(values):
        running += weight
        while when - values[left][0] > timedelta(seconds=seconds):
            running -= values[left][1]
            left += 1
        maximum = max(maximum, running)
    return maximum / total


def _event_equity(context: dict, start: datetime) -> tuple[float, str, bool]:
    profile = context.get("profile") or {}
    balance = number(profile.get("balance"))
    later_change = 0.0
    for trade in context.get("trades") or []:
        closed = parse_datetime(trade.get("closeTime") or trade.get("close_time_msc") or trade.get("close_time"))
        if closed and closed >= start:
            later_change += _net_profit(trade)
    for item in context.get("cashflows") or []:
        when = parse_datetime(item.get("time"))
        if when and when >= start and item.get("affectsBalance", True):
            later_change += number(item.get("amount"))
    historical = balance - later_change
    if historical > 50:
        return historical, "按当前余额倒推事件前现金权益", True
    fallback = max(abs(number(profile.get("equity"))), abs(balance), 50.0)
    return fallback, "历史现金权益不足，使用当前权益保守回退", False


def _baseline_exposure(trades: list[dict], now: datetime) -> float:
    clusters: list[list[dict]] = []
    ordered = sorted(
        ((opened, trade) for trade in trades if (opened := _trade_times(trade, now=now)[0])),
        key=lambda item: item[0],
    )
    for opened, trade in ordered:
        if not clusters:
            clusters.append([trade])
            continue
        previous = _trade_times(clusters[-1][-1], now=now)[0]
        if previous and opened - previous <= timedelta(minutes=10):
            clusters[-1].append(trade)
        else:
            clusters.append([trade])
    exposures = [sum(trade_exposure(trade) for trade in cluster) for cluster in clusters]
    return statistics.median(exposures) if len(exposures) >= 3 else 0.0


def _merge_events(trades: list[dict], now: datetime) -> list[dict]:
    weekend: dict[tuple[int, int], list[dict]] = defaultdict(list)
    opening: dict[datetime.date, list[dict]] = defaultdict(list)
    for trade in trades:
        opened, closed = _trade_times(trade, now=now)
        if not opened:
            continue
        if _is_weekend_trade(opened, closed):
            iso = opened.isocalendar()
            weekend[(iso.year, iso.week)].append(trade)
        if _is_open_window(opened):
            opening[opened.date()].append(trade)

    events: list[dict] = []
    consumed_open_dates: set[datetime.date] = set()
    for key, rows in weekend.items():
        close_dates = {
            closed.date()
            for row in rows
            if (closed := _trade_times(row, now=now)[1]) and closed.weekday() in {6, 0}
        }
        added = [trade for date in close_dates for trade in opening.get(date, []) if trade not in rows]
        kind = "combined" if added else "weekend"
        consumed_open_dates.update(close_dates if added else set())
        unique = {str(row.get("id") or row.get("ticket") or id(row)): row for row in [*rows, *added]}
        events.append({"kind": kind, "trades": list(unique.values()), "week": key})
    for date, rows in opening.items():
        if date not in consumed_open_dates:
            events.append({"kind": "open", "trades": rows, "date": date.isoformat()})
    return events


def _event_metrics(context: dict, event: dict, baseline: float, now: datetime) -> dict:
    rows = event["trades"]
    timed = []
    for trade in rows:
        opened, closed = _trade_times(trade, now=now)
        if opened:
            timed.append((trade, opened, closed or now, trade_exposure(trade)))
    start = min(opened for _, opened, _, _ in timed)
    end = max(closed for _, _, closed, _ in timed)
    peak_rows: list[tuple[dict, datetime, datetime, float]] = []
    peak_gross = 0.0
    for point in sorted({opened for _, opened, _, _ in timed}):
        active = [item for item in timed if item[1] <= point < item[2]]
        gross = sum(item[3] for item in active)
        if gross > peak_gross:
            peak_gross, peak_rows = gross, active
    if not peak_rows:
        peak_rows = timed
        peak_gross = sum(item[3] for item in timed)

    by_symbol: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    observed_moves = []
    for trade, _opened, _closed, exposure in peak_rows:
        direction = str(trade.get("direction") or trade.get("type") or "").lower()
        by_symbol[str(trade.get("symbol") or "UNKNOWN")][0 if direction == "buy" else 1] += exposure
        open_price = abs(number(trade.get("openPrice") or trade.get("open_price")))
        close_price = abs(number(trade.get("closePrice") or trade.get("close_price")))
        if open_price and close_price:
            observed_moves.append(abs(close_price - open_price) / open_price)
    directional = sum(abs(buy - sell) for buy, sell in by_symbol.values())
    direction_ratio = directional / peak_gross if peak_gross else 0.0
    equity, equity_basis, equity_reliable = _event_equity(context, start)
    leverage = max(number((context.get("profile") or {}).get("leverage")), 1.0)
    gross_leverage = peak_gross / equity
    estimated_margin = peak_gross / leverage
    margin_ratio = estimated_margin / equity
    estimated_margin_level = equity / estimated_margin * 100 if estimated_margin > 0 else None
    base_stress = 0.01 if event["kind"] in {"weekend", "combined"} else 0.005
    stress_move = max(base_stress, min(max(observed_moves or [0.0]), 0.03))
    stress_ratio = peak_gross * stress_move / equity
    baseline_ratio = peak_gross / baseline if baseline > 0 else 0.0
    entries = [(opened, exposure) for _, opened, _, exposure in timed]
    exits = [(closed, exposure) for _, _, closed, exposure in timed]
    entry_batch_ratio = _cluster_ratio(entries)
    exit_batch_ratio = _cluster_ratio(exits)
    holding_hours = statistics.median((closed - opened).total_seconds() / 3600 for _, opened, closed, _ in timed)
    peak_lots = sum(max(number(trade.get("volume")), number(trade.get("remainingVolume"))) for trade, *_rest in peak_rows)
    peak_order_count = sum(max(len(_entry_orders(trade)), 1) for trade, *_rest in peak_rows)
    event_profit = sum(_net_profit(row) for row in rows)
    actual_loss = max(-event_profit, 0.0)
    reset_evidence = []
    for item in context.get("cashflows") or []:
        when = parse_datetime(item.get("time"))
        if (
            when
            and end <= when <= end + timedelta(days=7)
            and number(item.get("amount")) > 0
            and _is_negative_balance_adjustment(item)
        ):
            reset_evidence.append({
                "time": when.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": _round(number(item.get("amount"))),
                "comment": str(item.get("comment") or "").strip(),
            })
    event_closed = all(not trade.get("isOpen") and _trade_times(trade, now=now)[1] for trade in rows)
    penetration_data_gaps = []
    if not event_closed:
        penetration_data_gaps.append("事件仍有未平仓订单")
    if not equity_reliable:
        penetration_data_gaps.append("事件前权益无法从历史现金流水可靠倒推")
    if actual_loss > equity:
        penetration_status = "是"
        penetration_reason = f"事件实际净亏损 {actual_loss:.2f} 已超过事件前权益 {equity:.2f}。"
    elif reset_evidence:
        penetration_status = "疑似"
        penetration_reason = "事件结束后发现负余额清零/补正流水，但仅凭流水备注不能确认穿仓金额。"
    elif penetration_data_gaps:
        penetration_status = "数据不足"
        penetration_reason = "；".join(penetration_data_gaps) + "，暂不能排除穿仓。"
    else:
        penetration_status = "否"
        penetration_reason = "已平仓事件净亏损未超过事件前权益，且七天内未发现负余额清零/补正流水。"
    return {
        "start": start,
        "end": end,
        "orderCount": len(rows),
        "peakLots": peak_lots,
        "peakOrderCount": peak_order_count,
        "peakRows": peak_rows,
        "peakGrossExposure": peak_gross,
        "grossLeverage": gross_leverage,
        "estimatedMargin": estimated_margin,
        "marginRatio": margin_ratio,
        "estimatedMarginLevel": estimated_margin_level,
        "stressMove": stress_move,
        "stressRatio": stress_ratio,
        "baselineRatio": baseline_ratio,
        "baselineAvailable": baseline > 0,
        "directionRatio": direction_ratio,
        "entryBatchRatio": entry_batch_ratio,
        "exitBatchRatio": exit_batch_ratio,
        "holdingHours": holding_hours,
        "netProfit": event_profit,
        "actualLoss": actual_loss,
        "lossToEquity": actual_loss / equity if equity else 0.0,
        "penetrationStatus": penetration_status,
        "penetrationReason": penetration_reason,
        "penetrationDataGaps": penetration_data_gaps,
        "eventClosed": event_closed,
        "equityReliable": equity_reliable,
        "negativeBalanceEvidence": reset_evidence,
        "equityBefore": equity,
        "equityBasis": equity_basis,
        "leverage": leverage,
        "sameDirectionAccounts": list(event.get("sameDirectionAccounts") or event.get("peerAccounts") or []),
        "oppositeDirectionAccounts": list(event.get("oppositeDirectionAccounts") or []),
        "sameDirectionMatches": list(event.get("sameDirectionMatches") or []),
        "oppositeDirectionMatches": list(event.get("oppositeDirectionMatches") or []),
        "sameDirectionMatchTotal": int(number(event.get("sameDirectionMatchTotal"))),
        "oppositeDirectionMatchTotal": int(number(event.get("oppositeDirectionMatchTotal"))),
        "peerMatchDetailLimit": int(number(event.get("peerMatchDetailLimit"))),
        "peerMatchesTruncated": bool(event.get("peerMatchesTruncated")),
        "peerSearchCoverage": dict(event.get("peerSearchCoverage") or {}),
        "peerCount": len(event.get("sameDirectionAccounts") or event.get("peerAccounts") or []),
    }


def _threshold_points(value: float, thresholds: tuple[float, float, float]) -> float:
    candidate, high, severe = thresholds
    if value >= severe:
        return 45.0
    if value >= high:
        return 35.0 + (value - high) / max(severe - high, 1e-9) * 10.0
    if value >= candidate:
        return 25.0 + (value - candidate) / max(high - candidate, 1e-9) * 10.0
    return max(value / max(candidate, 1e-9) * 18.0, 0.0)


def _score(event: dict, metrics: dict) -> tuple[float, bool, dict]:
    margin_points = _threshold_points(metrics["marginRatio"], (0.30, 0.50, 0.70))
    stress_points = _threshold_points(metrics["stressRatio"], (0.10, 0.20, 0.35))
    economic = max(margin_points, stress_points) + min(margin_points, stress_points) * 0.35
    baseline_points = min(max((metrics["baselineRatio"] - 1) / 4, 0.0), 1.0) * 6 if metrics["baselineAvailable"] else 0.0
    timing = {"open": 16.0, "weekend": 18.0, "combined": 22.0}[event["kind"]]
    direction = min(max((metrics["directionRatio"] - 0.5) / 0.45, 0.0), 1.0) * 10
    batch = (metrics["entryBatchRatio"] * 0.6 + metrics["exitBatchRatio"] * 0.4) * 8
    duration = 4.0 if event["kind"] in {"weekend", "combined"} or metrics["holdingHours"] <= 2 else max(0.0, 4 - metrics["holdingHours"] / 2)
    peers = min(metrics["peerCount"] / 3, 1.0) * 5
    leverage = 3.0 if metrics["leverage"] >= 1000 else 2.0 if metrics["leverage"] >= 500 else 1.0 if metrics["leverage"] >= 200 else 0.0
    counter = 0.0
    if metrics["entryBatchRatio"] < 0.5:
        counter += 10.0
    if event["kind"] == "open" and metrics["holdingHours"] > 4:
        counter += 8.0
    heavy = metrics["marginRatio"] >= 0.30 or metrics["stressRatio"] >= 0.10
    total = economic + baseline_points + timing + direction + batch + duration + peers + leverage - counter
    if not heavy:
        total = min(total, 39.0)
    return min(max(total, 0.0), 100.0), heavy, {
        "economic": _round(economic, 1),
        "baseline": _round(baseline_points, 1),
        "timing": timing,
        "direction": _round(direction, 1),
        "batch": _round(batch, 1),
        "duration": _round(duration, 1),
        "coordination": _round(peers, 1),
        "leverage": leverage,
        "counterevidence": _round(counter, 1),
    }


def _empty_result(type_id: str, stage: str) -> dict:
    return {
        "type": type_id,
        "label": TYPE_LABELS[type_id],
        "score": 0.0,
        "level": "未见明显",
        "stage": stage,
        "confidence": 70,
        "summary": "没有找到符合该时点定义的持仓事件。",
        "metrics": [],
        "triggeredRules": [],
        "evidenceOrders": [],
        "limitations": ["开盘窗口按数据库时间 +08:00 的 21:45–22:30 识别。"],
        "requiresTick": False,
        "analysis": [{"title": "结论", "text": "没有先认定重仓，也没有因为单纯在特殊时段交易而加分。"}],
        "evidence": {"events": []},
    }


def _result(type_id: str, stage: str, event: dict, metrics: dict, score: float, heavy: bool, score_basis: dict) -> dict:
    kind_label = {"weekend": "周末持仓", "open": "开盘时段建仓", "combined": "周末持仓并在重开后继续加仓/反向建仓"}[event["kind"]]
    margin_pct = metrics["marginRatio"] * 100
    stress_pct = metrics["stressRatio"] * 100
    direction_pct = metrics["directionRatio"] * 100
    batch_pct = metrics["entryBatchRatio"] * 100
    if heavy:
        summary = (
            f"先确认经济重仓：峰值名义敞口约为事件前权益的 {metrics['grossLeverage']:.1f} 倍，"
            f"压力损失约占 {stress_pct:.1f}%；随后命中{kind_label}。"
        )
    else:
        summary = (
            f"虽然命中{kind_label}，但估算保证金占权益 {margin_pct:.1f}%、压力损失占权益 {stress_pct:.1f}%，"
            "未达到重仓门槛，因此不判为赌时点。"
        )
    triggers = []
    if metrics["marginRatio"] >= 0.30:
        triggers.append("估算峰值保证金占事件前权益至少30%")
    if metrics["stressRatio"] >= 0.10:
        triggers.append("历史时点压力损失占事件前权益至少10%")
    if metrics["baselineRatio"] >= 2:
        triggers.append("事件敞口至少是账户平时批次的2倍")
    if metrics["directionRatio"] >= 0.70:
        triggers.append("净方向集中度至少70%")
    if metrics["entryBatchRatio"] >= 0.70 and metrics["exitBatchRatio"] >= 0.70:
        triggers.append("大部分仓位在5分钟内成批开仓和平仓")
    if metrics["peerCount"]:
        triggers.append(f"全平台同品种5秒内另有{metrics['peerCount']}个账户同步同向开仓和平仓")
    if metrics["oppositeDirectionAccounts"]:
        triggers.append(f"全平台同品种5秒内另有{len(metrics['oppositeDirectionAccounts'])}个账户同步反向开仓和平仓，列为疑似对锁线索")
    limitations = [
        "开盘窗口按数据库时间 +08:00 的 21:45–22:30 识别。",
        "名义敞口优先由实际盈亏对价格变动的敏感度反推，缺失时使用合约规模估算。",
    ]
    if not metrics["baselineAvailable"]:
        limitations.append("历史普通批次不足3个，无法可靠计算相对平时敞口倍数。")
    heavy_orders = []
    for trade, _opened, closed, exposure in metrics["peakRows"]:
        display_closed = None if trade.get("isOpen") else closed
        for entry in _entry_orders(trade):
            opened = parse_datetime(entry.get("time")) or _opened
            order_id = str(entry.get("orderId") or trade.get("ticket") or trade.get("id") or "")
            heavy_orders.append({
                "orderId": order_id,
                "positionId": str(trade.get("id") or trade.get("ticket") or ""),
                "dealId": str(entry.get("dealId") or ""),
                "symbol": str(trade.get("symbol") or ""),
                "direction": str(trade.get("direction") or trade.get("type") or "").lower(),
                "volume": _round(number(entry.get("volume"))),
                "openTime": opened.strftime("%Y-%m-%d %H:%M:%S"),
                "openPrice": _round(number(entry.get("price")), 5),
                "closeTime": display_closed.strftime("%Y-%m-%d %H:%M:%S") if display_closed else "",
                "holdingMinutes": _round(max((closed - opened).total_seconds() / 60, 0.0), 1) if closed else None,
                "positionNetProfit": _round(_net_profit(trade)),
                "estimatedPositionNotional": _round(exposure),
                "reason": "该入场订单在事件峰值时仍构成重仓，属于本次特殊时点重仓事件。",
            })
    heavy_orders = heavy_orders[:100]
    evidence_orders = [row["orderId"] for row in heavy_orders if row["orderId"]]
    event_payload = {
        "classification": event["kind"],
        "start": metrics["start"].strftime("%Y-%m-%d %H:%M:%S"),
        "end": metrics["end"].strftime("%Y-%m-%d %H:%M:%S"),
        "orderCount": metrics["orderCount"],
        "peakLots": _round(metrics["peakLots"]),
        "peakOrderCount": metrics["peakOrderCount"],
        "symbols": sorted({str(row.get("symbol") or "") for row in event["trades"] if row.get("symbol")}),
        "entries": [
            {
                "time": (_trade_times(row, now=metrics["end"])[0] or datetime.min).strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": str(row.get("symbol") or ""),
                "direction": str(row.get("direction") or row.get("type") or "").lower(),
            }
            for row in event["trades"]
            if _trade_times(row, now=metrics["end"])[0]
        ],
        "equityBefore": _round(metrics["equityBefore"]),
        "leverage": _round(metrics["leverage"], 0),
        "peakGrossExposure": _round(metrics["peakGrossExposure"]),
        "grossLeverage": _round(metrics["grossLeverage"], 2),
        "estimatedMargin": _round(metrics["estimatedMargin"]),
        "marginRatio": _round(metrics["marginRatio"], 4),
        "estimatedMarginLevel": _round(metrics["estimatedMarginLevel"], 2) if metrics["estimatedMarginLevel"] is not None else None,
        "stressRatio": _round(metrics["stressRatio"], 4),
        "baselineRatio": _round(metrics["baselineRatio"], 2),
        "directionRatio": _round(metrics["directionRatio"], 4),
        "entryBatchRatio": _round(metrics["entryBatchRatio"], 4),
        "exitBatchRatio": _round(metrics["exitBatchRatio"], 4),
        "holdingHours": _round(metrics["holdingHours"], 2),
        "netProfit": _round(metrics["netProfit"]),
        "actualLoss": _round(metrics["actualLoss"]),
        "lossToEquity": _round(metrics["lossToEquity"], 4),
        "penetrationStatus": metrics["penetrationStatus"],
        "penetrationReason": metrics["penetrationReason"],
        "penetrationDataGaps": metrics["penetrationDataGaps"],
        "eventClosed": metrics["eventClosed"],
        "equityReliable": metrics["equityReliable"],
        "negativeBalanceEvidence": metrics["negativeBalanceEvidence"],
        "sameDirectionAccounts": metrics["sameDirectionAccounts"],
        "oppositeDirectionAccounts": metrics["oppositeDirectionAccounts"],
        "sameDirectionMatches": metrics["sameDirectionMatches"],
        "oppositeDirectionMatches": metrics["oppositeDirectionMatches"],
        "sameDirectionMatchTotal": metrics["sameDirectionMatchTotal"],
        "oppositeDirectionMatchTotal": metrics["oppositeDirectionMatchTotal"],
        "peerMatchDetailLimit": metrics["peerMatchDetailLimit"],
        "peerMatchesTruncated": metrics["peerMatchesTruncated"],
        "peerSearchCoverage": metrics["peerSearchCoverage"],
        "peerAccounts": metrics["sameDirectionAccounts"],
        "heavyOrders": heavy_orders,
        "scoreBasis": score_basis,
        "heavyPosition": heavy,
    }
    return {
        "type": type_id,
        "label": TYPE_LABELS[type_id],
        "score": _round(score, 1),
        "level": _level(score),
        "stage": stage,
        "confidence": 88 if stage == "deep" else 72,
        "summary": summary,
        "metrics": [
            {"label": "事件前现金权益", "value": f"{metrics['equityBefore']:.2f}"},
            {"label": "账户杠杆", "value": f"1:{metrics['leverage']:.0f}"},
            {"label": "峰值仓位", "value": f"{metrics['peakLots']:.2f} 手 / {metrics['peakOrderCount']} 笔入场订单"},
            {"label": "峰值名义敞口", "value": f"{metrics['peakGrossExposure']:.2f}"},
            {"label": "峰值名义敞口 / 权益", "value": f"{metrics['grossLeverage']:.2f} 倍"},
            {"label": "估算保证金 / 权益", "value": f"{margin_pct:.1f}%"},
            {"label": "估算保证金", "value": f"{metrics['estimatedMargin']:.2f}"},
            {"label": "估算保证金水平", "value": f"{metrics['estimatedMarginLevel']:.1f}%" if metrics["estimatedMarginLevel"] is not None else "数据不足"},
            {"label": "时点压力损失 / 权益", "value": f"{stress_pct:.1f}%"},
            {"label": "相对平时敞口", "value": f"{metrics['baselineRatio']:.2f} 倍" if metrics["baselineAvailable"] else "样本不足"},
            {"label": "净方向集中度", "value": f"{direction_pct:.1f}%"},
            {"label": "5分钟集中开仓", "value": f"{batch_pct:.1f}%"},
            {"label": "持仓中位时长", "value": f"{metrics['holdingHours']:.2f} 小时"},
            {"label": "事件最终盈亏", "value": f"{metrics['netProfit']:.2f}（仅描述，不作为准入条件）"},
            {"label": "是否穿仓", "value": f"{metrics['penetrationStatus']}：{metrics['penetrationReason']}"},
        ],
        "triggeredRules": triggers,
        "evidenceOrders": [value for value in evidence_orders if value],
        "limitations": limitations,
        "requiresTick": False,
        "analysis": [
            {"title": "先看仓位", "text": summary},
            {"title": "再看行为", "text": f"方向集中 {direction_pct:.1f}%，5分钟集中开仓 {batch_pct:.1f}%，不是只凭交易时间下结论。"},
            {"title": "杠杆解释", "text": f"账户杠杆为 1:{metrics['leverage']:.0f}；模型同时看名义敞口和保证金占用，避免高杠杆掩盖真实仓位。"},
            {"title": "同行与疑似对锁", "text": f"全平台同品种、开仓和平仓都在5秒内的同向账户 {len(metrics['sameDirectionAccounts'])} 个；反向账户 {len(metrics['oppositeDirectionAccounts'])} 个。反向账户只作为疑似对锁线索，不直接定性。"},
            {"title": "穿仓核对", "text": metrics["penetrationReason"]},
            {"title": "反向证据", "text": "分散加仓、长时间扛单或未达到经济重仓门槛会压低评分；最终盈利或亏损都不会单独决定结论。"},
        ],
        "evidence": {"events": [event_payload], "bestEvent": event_payload},
    }


def analyze_position_risk(context: dict, *, stage: str = "deep", type_ids: list[str] | None = None) -> dict:
    selected = [value for value in (type_ids or list(TARGET_TYPES)) if value in TARGET_TYPES]
    now = parse_datetime(context.get("now")) or datetime.now()
    trades = list(context.get("trades") or [])
    baseline = _baseline_exposure(trades, now)
    events = _merge_events(trades, now)
    analysis_start = parse_datetime(context.get("analysisStart"))
    analysis_end = parse_datetime(context.get("analysisEnd"))
    if analysis_start:
        events = [event for event in events if any((_trade_times(row, now=now)[0] or datetime.min) >= analysis_start for row in event["trades"])]
    if analysis_end:
        events = [event for event in events if any((_trade_times(row, now=now)[0] or datetime.max) < analysis_end for row in event["trades"])]
    peer_evidence = dict(context.get("peerEvidence") or {})
    for event in events:
        opened = min((_trade_times(row, now=now)[0] for row in event["trades"] if _trade_times(row, now=now)[0]), default=None)
        closed = max((_trade_times(row, now=now)[1] for row in event["trades"] if _trade_times(row, now=now)[1]), default=None)
        matches_peer_event = bool(
            peer_evidence and opened and closed
            and peer_evidence.get("eventStart") == opened.strftime("%Y-%m-%d %H:%M:%S")
            and peer_evidence.get("eventEnd") == closed.strftime("%Y-%m-%d %H:%M:%S")
        )
        evidence = peer_evidence if matches_peer_event else {}
        event["sameDirectionAccounts"] = list(evidence.get("sameDirectionAccounts") or [])
        event["oppositeDirectionAccounts"] = list(evidence.get("oppositeDirectionAccounts") or [])
        event["peerAccounts"] = event["sameDirectionAccounts"]
        event["sameDirectionMatches"] = list(evidence.get("sameDirectionMatches") or [])
        event["oppositeDirectionMatches"] = list(evidence.get("oppositeDirectionMatches") or [])
        event["sameDirectionMatchTotal"] = int(number(evidence.get("sameDirectionMatchTotal")))
        event["oppositeDirectionMatchTotal"] = int(number(evidence.get("oppositeDirectionMatchTotal")))
        event["peerMatchDetailLimit"] = int(number(evidence.get("peerMatchDetailLimit")))
        event["peerMatchesTruncated"] = bool(evidence.get("peerMatchesTruncated"))
        event["peerSearchCoverage"] = dict(evidence.get("peerSearchCoverage") or {})
        event["peerCount"] = len(event["sameDirectionAccounts"])
    peer_loader = context.get("peerLoader")
    if callable(peer_loader) and events:
        peer_loader(events)
    analyzed = []
    for event in events:
        metrics = _event_metrics(context, event, baseline, now)
        score, heavy, basis = _score(event, metrics)
        analyzed.append((event, metrics, score, heavy, basis))

    results = []
    for type_id in selected:
        accepted_kinds = {"weekend", "combined"} if type_id == "weekend_gap_trading" else {"open", "combined"}
        candidates = [item for item in analyzed if item[0]["kind"] in accepted_kinds]
        if not candidates:
            results.append(_empty_result(type_id, stage))
            continue
        best = max(candidates, key=lambda item: (item[2], item[1]["stressRatio"], item[1]["marginRatio"]))
        results.append(_result(type_id, stage, *best))
    best_event = max((row for row in results if row.get("evidence", {}).get("bestEvent")), key=lambda row: row["score"], default=None)
    return {
        "results": results,
        "events": [row[0] for row in analyzed],
        "bestResult": best_event,
    }
