"""Compact, read-only all-product position replay for an inline K-line window."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

_FIELDS = ["openTime", "closeTime", "ticket", "symbol", "type", "volume", "openPrice", "isOpen"]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    open_time = _text(row.get("Open Time"))
    if not open_time:
        return None
    is_open = bool(row.get("Is Open"))
    close_time = "" if is_open else _text(row.get("Close Time"))
    if not is_open and not close_time:
        return None
    direction = _text(row.get("Type")).lower()
    if direction not in {"buy", "sell"}:
        return None
    return {
        "openTime": open_time,
        "closeTime": close_time,
        "ticket": _text(row.get("Ticket")),
        "symbol": _text(row.get("Item")),
        "type": direction,
        "volume": _number(row.get("Volume")),
        "openPrice": _number(row.get("Open Price")),
        "isOpen": is_open,
    }


def build_account_position_replay(
    trades: Iterable[Mapping[str, Any]],
    *,
    start: str,
    end: str,
    chart_times_by_symbol: Mapping[str, Iterable[str]],
) -> dict[str, Any]:
    """Build all-product position rows only for the direct chart's time window.

    The browser receives a compact, overlap-filtered row array and a pre-swept
    count/lot series for every displayed chart symbol.  It therefore never
    recalculates a whole account history for a pan or zoom operation.
    """

    start = _text(start)
    end = _text(end)
    source_rows = [normalized for raw in trades if (normalized := _row(raw)) is not None]
    included = [
        row
        for row in source_rows
        if (not end or row["openTime"] <= end)
        and (row["isOpen"] or not start or row["closeTime"] > start)
    ]
    included.sort(key=lambda row: (row["openTime"], row["ticket"], row["symbol"]))

    events: list[tuple[str, int, float]] = []
    for row in included:
        events.append((row["openTime"], 1, row["volume"]))
        if not row["isOpen"]:
            events.append((row["closeTime"], -1, -row["volume"]))
    # A close at an exact chart timestamp is no longer an active position.
    events.sort(key=lambda item: (item[0], item[1]))

    series_by_symbol: dict[str, list[list[Any]]] = {}
    for symbol, raw_times in chart_times_by_symbol.items():
        event_index = 0
        count = 0
        volume = 0.0
        points: list[list[Any]] = []
        for timestamp in sorted({_text(value) for value in raw_times if _text(value)}):
            while event_index < len(events) and events[event_index][0] <= timestamp:
                _, delta_count, delta_volume = events[event_index]
                count += delta_count
                volume += delta_volume
                event_index += 1
            points.append([timestamp, count, round(volume, 8)])
        series_by_symbol[_text(symbol)] = points

    return {
        "version": 1,
        "fields": list(_FIELDS),
        "rows": [[row[field] for field in _FIELDS] for row in included],
        "seriesBySymbol": series_by_symbol,
        "coverage": {
            "scope": "all_products_in_chart_window",
            "sourceTradeCount": len(source_rows),
            "includedTradeCount": len(included),
            "symbolCount": len({row["symbol"] for row in included if row["symbol"]}),
            "start": start,
            "end": end,
        },
    }
