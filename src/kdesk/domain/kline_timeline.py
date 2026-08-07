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

    selected_events = [_public_event(item) for item in raw_events if _in_window(_text(item.get("timestamp")), start, end)]
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
            "curvePointCount": len(selected_curve),
            "knownStateEventCount": sum(item["balance"] is not None and item["credit"] is not None for item in selected_events),
            "liquidationCount": len(selected_liquidations),
        }
    )
    return {
        "version": 1,
        "window": {"start": start, "end": end},
        "openingState": opening_state,
        "summary": summary,
        "events": selected_events,
        "curve": selected_curve,
        "liquidationPoints": selected_liquidations,
    }
