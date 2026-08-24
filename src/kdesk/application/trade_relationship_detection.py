from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Protocol

from kdesk.domain.position_risk import canonical_symbol, number, parse_datetime


class TradeRelationshipRepository(Protocol):
    def load_account_context(self, account: str, filters: dict) -> dict: ...

    def load_peer_accounts(self, account: str, context: dict, event: dict) -> dict: ...


def _round(value: object, digits: int = 2) -> float:
    return round(number(value), digits)


def _time_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f").rstrip("0").rstrip(".")


def select_principal_orders(orders: list[dict]) -> tuple[list[dict], dict]:
    """Keep the orders that represent at least 95% of volume per symbol, with a five-order floor."""
    tradable = [
        row for row in orders
        if str(row.get("direction") or "").lower() in {"buy", "sell"}
        and parse_datetime(row.get("openTime"))
        and number(row.get("volume")) > 0
    ]
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in tradable:
        by_symbol[canonical_symbol(row.get("symbol")) or str(row.get("symbol") or "-")].append(row)

    selected_ids: set[int] = set()
    cutoffs: dict[str, float] = {}
    for symbol, rows in by_symbol.items():
        if len(rows) < 5:
            selected_ids.update(id(row) for row in rows)
            cutoffs[symbol] = 0.0
            continue
        ranked = sorted(rows, key=lambda row: number(row.get("volume")), reverse=True)
        target_volume = sum(number(row.get("volume")) for row in ranked) * 0.95
        running = 0.0
        cutoff = number(ranked[-1].get("volume"))
        for index, row in enumerate(ranked):
            running += number(row.get("volume"))
            cutoff = number(row.get("volume"))
            if running >= target_volume and index + 1 >= 5:
                break
        selected = [row for row in rows if number(row.get("volume")) >= cutoff]
        if len(selected) < 5:
            selected = ranked[:5]
            cutoff = number(selected[-1].get("volume"))
        selected_ids.update(id(row) for row in selected)
        cutoffs[symbol] = _round(cutoff, 4)

    selected = [row for row in tradable if id(row) in selected_ids]
    raw_volume = sum(number(row.get("volume")) for row in tradable)
    selected_volume = sum(number(row.get("volume")) for row in selected)
    volumes = sorted(number(row.get("volume")) for row in tradable)
    return selected, {
        "rawOrderCount": len(tradable),
        "principalOrderCount": len(selected),
        "excludedOrderCount": len(tradable) - len(selected),
        "rawVolume": _round(raw_volume, 4),
        "principalVolume": _round(selected_volume, 4),
        "excludedVolumeRatioPct": _round((raw_volume - selected_volume) / raw_volume * 100, 1) if raw_volume else 0.0,
        "medianVolume": _round(statistics.median(volumes), 4) if volumes else 0.0,
        "volumeCutoffs": cutoffs,
        "targetVolumeCoverage": 95.0,
    }


def _closed_entry_orders(context: dict, filters: dict) -> tuple[list[dict], dict]:
    requested_start = parse_datetime(context.get("analysisStart") or filters.get("start"))
    requested_end = parse_datetime(context.get("analysisEnd") or filters.get("end"))
    requested_symbol = canonical_symbol(filters.get("symbol"))
    orders: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    open_positions = 0
    filtered = 0

    for trade in context.get("trades") or []:
        closed = parse_datetime(trade.get("closeTime"))
        if bool(trade.get("isOpen")) or not closed:
            open_positions += 1
            continue
        symbol = str(trade.get("symbol") or "")
        if requested_symbol and canonical_symbol(symbol) != requested_symbol:
            filtered += 1
            continue
        entries = list(trade.get("entryOrders") or []) or [{
            "orderId": trade.get("ticket") or trade.get("id"),
            "dealId": "",
            "time": trade.get("openTime"),
            "volume": trade.get("volume"),
        }]
        for entry in entries:
            opened = parse_datetime(entry.get("time") or trade.get("openTime"))
            if not opened or (requested_start and opened < requested_start) or (requested_end and opened > requested_end):
                filtered += 1
                continue
            order_id = str(entry.get("orderId") or trade.get("ticket") or trade.get("id") or "")
            position_id = str(trade.get("id") or trade.get("ticket") or order_id)
            deal_id = str(entry.get("dealId") or "")
            opened_text = _time_text(opened)
            key = (order_id, position_id, deal_id, opened_text)
            if key in seen:
                continue
            seen.add(key)
            orders.append({
                "orderId": order_id,
                "positionId": position_id,
                "dealId": deal_id,
                "symbol": symbol,
                "direction": str(trade.get("direction") or "").lower(),
                "volume": number(entry.get("volume") or trade.get("volume")),
                "openTime": opened_text,
                "closeTime": _time_text(closed),
                "_oppositeOnly": False,
            })
    orders.sort(key=lambda row: (row["openTime"], row["orderId"]))
    return orders, {"openPositionCount": open_positions, "filteredOrderCount": filtered}


def _best_matches_by_target(rows: list[dict]) -> list[dict]:
    best: dict[str, tuple[tuple[float, float, float], dict]] = {}
    for row in rows:
        target = str(row.get("targetOrderId") or "")
        key = target or "|".join((str(row.get("orderId") or ""), str(row.get("openTime") or "")))
        quality = (
            abs(number(row.get("openDeltaSeconds"), float("inf"))),
            abs(number(row.get("closeDeltaSeconds"), float("inf"))),
            -number(row.get("lotSimilarity")),
        )
        current = best.get(key)
        if current is None or quality < current[0]:
            best[key] = (quality, row)
    return [item[1] for item in best.values()]


def _aggregate_matches(rows: list[dict], *, relation: str, principal_orders: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("platform") or ""), str(row.get("server") or ""), str(row.get("account") or ""))].append(row)

    principal_count = len(principal_orders)
    principal_volume = sum(number(row.get("volume")) for row in principal_orders)
    recurrence_floor = max(2, math.ceil(principal_count * 0.05))
    results: list[dict] = []
    for (platform, server, account), candidates in grouped.items():
        if not account:
            continue
        best = _best_matches_by_target(candidates)
        if relation == "same" and len(best) < recurrence_floor:
            continue
        matched_target_volume = sum(number(row.get("targetVolume")) for row in best)
        lot_values = [number(row.get("lotSimilarityPct")) for row in best if row.get("lotSimilarityPct") not in (None, "")]
        results.append({
            "relation": relation,
            "account": account,
            "platform": platform,
            "server": server,
            "matchCount": len(best),
            "principalOrderCount": principal_count,
            "matchRatioPct": _round(len(best) / principal_count * 100, 1) if principal_count else 0.0,
            "matchedVolumeRatioPct": _round(matched_target_volume / principal_volume * 100, 1) if principal_volume else 0.0,
            "maximumOpenDeltaSeconds": max((number(row.get("openDeltaSeconds")) for row in best), default=0.0),
            "maximumCloseDeltaSeconds": max((number(row.get("closeDeltaSeconds")) for row in best), default=0.0),
            "minimumLotSimilarityPct": min(lot_values) if lot_values else None,
            "recurrenceFloor": recurrence_floor if relation == "same" else 1,
            "orderPairs": best[:20],
            "orderPairsTruncated": len(best) > 20,
        })
    return sorted(results, key=lambda row: (-row["matchCount"], row["platform"], row["server"], row["account"]))


class TradeRelationshipDetectionService:
    """Detect full-platform synchronized trading and suspected opposite locking from principal orders."""

    def __init__(self, repository: TradeRelationshipRepository):
        self.repository = repository

    def analyze(self, account: str, filters: dict) -> dict:
        context = self.repository.load_account_context(str(account), filters)
        closed_orders, target_stats = _closed_entry_orders(context, filters)
        principal_orders, principal_stats = select_principal_orders(closed_orders)
        event = {
            "start": principal_orders[0]["openTime"] if principal_orders else "",
            "end": max((row["closeTime"] for row in principal_orders), default=""),
            "heavyOrders": principal_orders,
        }
        peer_evidence = self.repository.load_peer_accounts(str(account), context, event) if principal_orders else {
            "sameDirectionMatches": [], "oppositeDirectionMatches": [],
            "peerSearchCoverage": {"status": "数据不足", "reason": "没有完整开平仓主订单"},
        }
        same_raw = [
            row for row in peer_evidence.get("sameDirectionMatches") or []
            if number(row.get("openDeltaSeconds"), 999) <= 2 and number(row.get("closeDeltaSeconds"), 999) <= 2
        ]
        opposite_raw = [
            row for row in peer_evidence.get("oppositeDirectionMatches") or []
            if number(row.get("openDeltaSeconds"), 999) <= 5
            and number(row.get("closeDeltaSeconds"), 999) <= 5
            and number(row.get("lotSimilarity"), number(row.get("lotSimilarityPct")) / 100) >= 0.8
        ]
        same = _aggregate_matches(same_raw, relation="same", principal_orders=principal_orders)
        opposite = _aggregate_matches(opposite_raw, relation="opposite", principal_orders=principal_orders)
        coverage = dict(peer_evidence.get("peerSearchCoverage") or {})
        status = str(coverage.get("status") or "数据不足")
        return {
            "matches": [*same, *opposite],
            "summary": {
                **target_stats,
                **principal_stats,
                "sameDirectionAccountCount": len(same),
                "oppositeDirectionAccountCount": len(opposite),
                "sameDirectionMatchCount": sum(row["matchCount"] for row in same),
                "oppositeDirectionMatchCount": sum(row["matchCount"] for row in opposite),
            },
            "coverage": [{
                "source": "tradeRelationshipDetection",
                "status": "available" if status == "完成" else status,
                "reason": "" if status == "完成" else str(coverage.get("reason") or status),
                "scope": coverage.get("scope") or "AC/DBG 全平台 MT4 + MT5",
                "principalOrderCount": len(principal_orders),
                "sameDirectionAccountCount": len(same),
                "oppositeDirectionAccountCount": len(opposite),
                "physicalSourceTotal": coverage.get("physicalSourceTotal"),
                "scannedSourceCount": coverage.get("scannedSourceCount"),
            }],
        }
