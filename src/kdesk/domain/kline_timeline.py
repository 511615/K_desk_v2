"""Pure preparation of a historical funds replay for a standalone K-line artifact."""

from typing import Any

_ORDER_KINDS = {"trade_open", "trade_close"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 8)
    except (TypeError, ValueError):
        return None


def _in_window(timestamp: str, start: str, end: str) -> bool:
    return (not start or timestamp >= start) and (not end or timestamp <= end)


def _state_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    balance = _number_or_none(row.get("balance"))
    credit = _number_or_none(row.get("credit"))
    return {
        "timestamp": _text(row.get("timestamp")),
        "balance": balance,
        "credit": credit,
        "known": balance is not None and credit is not None,
    }


def _event_category(kind: str) -> str:
    return "order" if kind in _ORDER_KINDS else "funds"


def _sum_numbers(events: list[dict[str, Any]], field: str) -> float:
    return round(sum(_number_or_none(event.get(field)) or 0.0 for event in events), 8)


def _unique_text(events: list[dict[str, Any]], field: str) -> str:
    values = [_text(event.get(field)) for event in events]
    return " / ".join(dict.fromkeys(value for value in values if value))


def _position_key(event: dict[str, Any], fallback: int) -> str:
    return _text(event.get("positionId")) or _text(event.get("orderId")) or _text(event.get("id")) or f"event-{fallback}"


def _public_position_event(events: list[dict[str, Any]], fallback: int) -> dict[str, Any]:
    """Represent all ledger entries of one market position as one factual table event.

    The Balance/Credit curve always retains every source event.  Only the human-facing table folds
    a position's opening, partial closes and final close into one row, anchored at its final known
    lifecycle timestamp.
    """

    items = sorted(events, key=lambda item: (_text(item.get("timestamp")), int(item.get("eventIndex") or 0)))
    openings = [item for item in items if _text(item.get("kind")) == "trade_open"]
    closings = [item for item in items if _text(item.get("kind")) == "trade_close"]
    opening = openings[0] if openings else items[0]
    closing = closings[-1] if closings else items[-1]
    position_id = _position_key(opening, fallback)
    closed = bool(closings)
    source_ids = [_text(item.get("orderId")) or _text(item.get("id")) for item in items]
    return {
        "eventIndex": closing.get("eventIndex"),
        "eventIndexes": [item.get("eventIndex") for item in items],
        "id": _text(closing.get("id")) or position_id,
        "timestamp": _text(closing.get("timestamp")),
        "kind": "trade_position",
        "category": "position",
        "orderId": _text(closing.get("orderId")) or position_id,
        "positionId": position_id,
        "positionOpenTime": _text(opening.get("timestamp")),
        "positionCloseTime": _text(closing.get("timestamp")) if closed else "",
        "positionState": "closed" if closed else "open",
        "sourceOrderEventCount": len(items),
        "sourceOrderIds": list(dict.fromkeys(value for value in source_ids if value)),
        "symbol": _unique_text(items, "symbol"),
        "comment": _unique_text(items, "comment"),
        "deltaBalance": _sum_numbers(items, "deltaBalance"),
        "deltaCredit": _sum_numbers(items, "deltaCredit"),
        "realizedPnl": _sum_numbers(items, "realizedPnl"),
        "balance": _number_or_none(closing.get("balance")),
        "credit": _number_or_none(closing.get("credit")),
        "equity": _number_or_none(closing.get("equity")),
        "equityStatus": _text(closing.get("equityStatus")),
        "liquidation": next((item.get("liquidation") for item in reversed(items) if item.get("liquidation")), None),
    }


def _position_events(raw_events: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fallback, event in enumerate(raw_events):
        if _text(event.get("kind")) not in _ORDER_KINDS:
            continue
        grouped.setdefault(_position_key(event, fallback), []).append(event)
    positions = [_public_position_event(events, fallback) for fallback, events in enumerate(grouped.values())]
    return [event for event in positions if _in_window(_text(event.get("timestamp")), start, end)]


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    kind = _text(event.get("kind")) or "other"
    return {
        "eventIndex": event.get("eventIndex"),
        "id": _text(event.get("id")),
        "timestamp": _text(event.get("timestamp")),
        "kind": kind,
        "category": _event_category(kind),
        "orderId": _text(event.get("orderId")),
        "positionId": _text(event.get("positionId")),
        "symbol": _text(event.get("symbol")),
        "comment": _text(event.get("comment")),
        "deltaBalance": _number_or_none(event.get("deltaBalance")) or 0.0,
        "deltaCredit": _number_or_none(event.get("deltaCredit")) or 0.0,
        "realizedPnl": _number_or_none(event.get("realizedPnl")) or 0.0,
        "balance": _number_or_none(event.get("balance")),
        "credit": _number_or_none(event.get("credit")),
        "equity": _number_or_none(event.get("equity")),
        "equityStatus": _text(event.get("equityStatus")),
        "liquidation": event.get("liquidation"),
    }


def _public_curve(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": _text(row.get("timestamp")),
        "kind": _text(row.get("kind")),
        "balance": _number_or_none(row.get("balance")),
        "credit": _number_or_none(row.get("credit")),
        "equity": _number_or_none(row.get("equity")),
        "equityStatus": _text(row.get("equityStatus")),
    }


def build_kline_timeline(replay: dict[str, Any], *, start: str = "", end: str = "") -> dict[str, Any]:
    """Trim a factual account replay to a chart window without inventing an opening state.

    The standalone chart gets an explicit carry-in state so a filtered K-line does not restart its
    Balance/Credit lines at zero.  Missing pre-anchor values remain ``None`` by design.
    """

    start = _text(start)
    end = _text(end)
    raw_events = sorted((dict(item) for item in replay.get("events", []) if _text(item.get("timestamp"))), key=lambda item: (str(item.get("timestamp")), int(item.get("eventIndex") or 0)))
    raw_curve = sorted((dict(item) for item in replay.get("curve", []) if _text(item.get("timestamp"))), key=lambda item: str(item.get("timestamp")))

    prior_states = [item for item in raw_curve if not start or _text(item.get("timestamp")) < start]
    opening_state = _state_from_row(prior_states[-1] if prior_states else None)

    selected_funds = [
        _public_event(item)
        for item in raw_events
        if _text(item.get("kind")) not in _ORDER_KINDS and _in_window(_text(item.get("timestamp")), start, end)
    ]
    selected_events = sorted(
        selected_funds + _position_events(raw_events, start, end),
        key=lambda item: (_text(item.get("timestamp")), int(item.get("eventIndex") or 0)),
    )
    selected_curve = [_public_curve(item) for item in raw_curve if _in_window(_text(item.get("timestamp")), start, end)]
    if opening_state["timestamp"]:
        carry_in = {
            "timestamp": opening_state["timestamp"],
            "kind": "opening_state",
            "balance": opening_state["balance"],
            "credit": opening_state["credit"],
            "equity": None,
            "equityStatus": "carry_in" if opening_state["known"] else "unknown",
        }
        if not selected_curve or selected_curve[0]["timestamp"] != carry_in["timestamp"]:
            selected_curve.insert(0, carry_in)

    selected_liquidations = [
        dict(item)
        for item in replay.get("liquidationPoints", [])
        if _in_window(_text(item.get("timestamp")), start, end)
    ]
    summary = dict(replay.get("summary") or {})
    summary.update(
        {
            "eventCount": len(selected_events),
            "allEventCount": len(raw_events),
            "fundsEventCount": len(selected_funds),
            "positionEventCount": sum(item.get("kind") == "trade_position" for item in selected_events),
            "sourceOrderEventCount": sum(_text(item.get("kind")) in _ORDER_KINDS for item in raw_events),
            "curvePointCount": len(selected_curve),
            "knownStateEventCount": sum(item["balance"] is not None and item["credit"] is not None for item in selected_events),
            "liquidationCount": len(selected_liquidations),
        }
    )
    return {
        "version": 2,
        "window": {"start": start, "end": end},
        "openingState": opening_state,
        "summary": summary,
        "events": selected_events,
        "curve": selected_curve,
        "liquidationPoints": selected_liquidations,
    }
