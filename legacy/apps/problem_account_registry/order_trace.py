from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable, Mapping


MT5_INVALID_STOPS_RETCODE = 10016


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _text(value).replace("T", " ")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _identifier(value: object) -> str:
    text = _text(value)
    if not re.fullmatch(r"[A-Za-z0-9_]+", text):
        raise ValueError(f"Unsafe SQL identifier: {text!r}")
    return text


def mt5_lots(row: Mapping[str, object]) -> float:
    volume_ext = _float(row.get("VolumeExt"))
    if volume_ext:
        return round(volume_ext / 100_000_000, 8)
    return round(_float(row.get("Volume")) / 10_000, 8)


@dataclass(frozen=True)
class OrderTraceRequest:
    login: int
    ticket: int
    event_time: datetime
    symbol: str = ""
    lots: float = 0.0
    price: float = 0.0
    dealer_id: int = 0
    order_kind: str = ""
    command: str = ""

    @classmethod
    def from_mapping(cls, row: Mapping[str, object]) -> "OrderTraceRequest":
        event_time = _datetime(row.get("event_time") or row.get("monitorTime"))
        if event_time is None:
            raise ValueError("event_time is required")
        login = _int(row.get("login"))
        ticket = _int(row.get("ticket"))
        if login <= 0 or ticket <= 0:
            raise ValueError("login and ticket must be positive integers")
        return cls(
            login=login,
            ticket=ticket,
            event_time=event_time,
            symbol=_text(row.get("symbol")),
            lots=_float(row.get("lots")),
            price=_float(row.get("price")),
            dealer_id=_int(row.get("dealer_id") or row.get("dealerId")),
            order_kind=_text(row.get("order_kind") or row.get("type")),
            command=_text(row.get("command")),
        )


def _event_time(row: Mapping[str, object]) -> datetime | None:
    return _datetime(row.get("TimeMsc") or row.get("Time"))


def _candidate_details(request: OrderTraceRequest, row: Mapping[str, object]) -> dict:
    event_time = _event_time(row)
    delta = (event_time - request.event_time).total_seconds() if event_time else None
    symbol_match = not request.symbol or _text(row.get("Symbol")).upper() == request.symbol.upper()
    volume = mt5_lots(row)
    volume_match = request.lots <= 0 or abs(volume - request.lots) <= 0.0000001
    dealer = _int(row.get("Dealer"))
    dealer_match = request.dealer_id <= 0 or dealer == request.dealer_id
    score = sum((4 if symbol_match else 0, 4 if volume_match else 0, 2 if dealer_match else 0))
    if delta is not None:
        score += 3 if abs(delta) <= 5 else 1 if abs(delta) <= 30 else 0
    return {
        "row": dict(row),
        "deal": _int(row.get("Deal")),
        "order": _int(row.get("Order")),
        "position": _int(row.get("PositionID")),
        "time": event_time,
        "deltaSeconds": round(delta, 3) if delta is not None else None,
        "symbol": _text(row.get("Symbol")),
        "lots": volume,
        "dealerId": dealer,
        "action": _int(row.get("Action"), -1),
        "symbolMatch": symbol_match,
        "volumeMatch": volume_match,
        "dealerMatch": dealer_match,
        "score": score,
    }


def _best_linked_candidate(
    request: OrderTraceRequest,
    rows: Iterable[Mapping[str, object]],
    window_seconds: int,
) -> dict | None:
    candidates = [_candidate_details(request, row) for row in rows]
    candidates = [
        item
        for item in candidates
        if item["symbolMatch"]
        and item["volumeMatch"]
        and item["deltaSeconds"] is not None
        and abs(item["deltaSeconds"]) <= window_seconds
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item["score"], abs(item["deltaSeconds"]), item["deal"]))
    return candidates[0]


def infer_pending_price_constraint(
    request: OrderTraceRequest,
    linked: Mapping[str, object] | None,
    symbol: Mapping[str, object] | None,
) -> dict | None:
    if "pending" not in request.order_kind.lower() or not linked or not symbol or request.price <= 0:
        return None
    row = linked.get("row") or {}
    if not isinstance(row, Mapping):
        return None
    action = _int(linked.get("action"), -1)
    bid = _float(row.get("MarketBid"))
    ask = _float(row.get("MarketAsk"))
    point = _float(symbol.get("Point"))
    stops_level = _int(symbol.get("StopsLevel"))
    minimum = stops_level * point
    if action == 0 and ask > 0:
        inferred_type = "buy_stop" if request.price >= ask else "buy_limit"
        distance = abs(request.price - ask)
        reference_name = "ask"
        reference_price = ask
    elif action == 1 and bid > 0:
        inferred_type = "sell_stop" if request.price <= bid else "sell_limit"
        distance = abs(request.price - bid)
        reference_name = "bid"
        reference_price = bid
    else:
        return None
    violation = minimum > 0 and distance + max(point / 10, 1e-9) < minimum
    return {
        "inferredPendingType": inferred_type,
        "reference": reference_name,
        "referencePrice": reference_price,
        "requestPrice": request.price,
        "actualDistance": round(distance, 10),
        "minimumDistance": round(minimum, 10),
        "stopsLevel": stops_level,
        "point": point,
        "violated": violation,
        "likelyRetcode": MT5_INVALID_STOPS_RETCODE if violation else None,
        "likelyReason": "invalid_stops" if violation else None,
        "source": "constraint_inference",
    }


def _matched_rejection_log(
    request: OrderTraceRequest,
    logs: Iterable[Mapping[str, object]],
    window_seconds: int,
) -> dict | None:
    matches = []
    for row in logs:
        ticket = _int(row.get("ticket") or row.get("order") or row.get("request_id"))
        login = _int(row.get("login"))
        time_value = _datetime(row.get("time") or row.get("event_time") or row.get("monitorTime"))
        delta = abs((time_value - request.event_time).total_seconds()) if time_value else None
        if ticket == request.ticket or (login == request.login and delta is not None and delta <= window_seconds):
            matches.append((0 if ticket == request.ticket else 1, delta or 0, dict(row)))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]))
    return matches[0][2]


def build_trace_result(
    request: OrderTraceRequest,
    *,
    exact_rows: Iterable[Mapping[str, object]] = (),
    window_rows: Iterable[Mapping[str, object]] = (),
    account: Mapping[str, object] | None = None,
    symbol: Mapping[str, object] | None = None,
    positions: Iterable[Mapping[str, object]] = (),
    rejection_logs: Iterable[Mapping[str, object]] = (),
    window_seconds: int = 30,
    limitations: Iterable[str] = (),
) -> dict:
    exact = [dict(row) for row in exact_rows]
    window = [dict(row) for row in window_rows]
    logged_rejection = _matched_rejection_log(request, rejection_logs, window_seconds)
    linked = _best_linked_candidate(request, window, window_seconds)
    price_constraint = infer_pending_price_constraint(request, linked, symbol)

    if logged_rejection:
        status = "rejected_logged"
        confidence = "high"
        reason_source = "rejection_log"
    elif exact:
        status = "executed_exact"
        confidence = "high"
        reason_source = "mt5_deals"
    elif linked:
        status = "resubmitted_or_replaced"
        confidence = "high" if linked["dealerMatch"] and abs(linked["deltaSeconds"]) <= 5 else "medium"
        reason_source = "constraint_inference" if price_constraint and price_constraint["violated"] else "correlation"
    else:
        status = "not_found"
        confidence = "low"
        reason_source = "none"

    result_limitations = list(limitations)
    if not logged_rejection and not exact:
        result_limitations.append("No request/order journal row or MT5 retcode was available in the queried database.")
    if account:
        result_limitations.append("Account values are the current snapshot, not a historical snapshot at the request time.")
    if symbol:
        result_limitations.append("Symbol settings are current settings unless the export source provides history.")
    if price_constraint:
        result_limitations.append(
            "Pending-price inference uses Bid/Ask from the correlated fill, not an exact tick at the original request time."
        )

    return {
        "request": {
            "login": request.login,
            "ticket": request.ticket,
            "eventTime": request.event_time,
            "symbol": request.symbol,
            "lots": request.lots,
            "price": request.price,
            "dealerId": request.dealer_id,
            "orderKind": request.order_kind,
            "command": request.command,
        },
        "status": status,
        "confidence": confidence,
        "reasonSource": reason_source,
        "loggedRejection": logged_rejection,
        "exactMatches": exact,
        "linkedFinal": linked,
        "pendingPriceConstraint": price_constraint,
        "accountSnapshot": dict(account or {}),
        "symbolSnapshot": dict(symbol or {}),
        "positions": [dict(row) for row in positions],
        "windowDeals": window,
        "limitations": list(dict.fromkeys(result_limitations)),
    }


class MT5OrderTraceQuery:
    def __init__(self, source: Mapping[str, object], connect: Callable[[Mapping[str, object]], object]):
        if _text(source.get("kind")) != "mt5_deals":
            raise ValueError("MT5OrderTraceQuery requires an mt5_deals source")
        self.source = dict(source)
        self.connect = connect
        self.schema = _identifier(source.get("schema"))
        self.deals_table = _identifier(source.get("table") or "mt5_deals")

    @property
    def _deal_columns(self) -> str:
        return (
            "Deal, Login, `Order`, PositionID, Dealer, Action, Entry, Reason, "
            "Time, TimeMsc, Symbol, Price, Volume, VolumeExt, Comment, "
            "MarketBid, MarketAsk, PriceGateway, ApiData"
        )

    def run(
        self,
        request: OrderTraceRequest,
        *,
        window_seconds: int = 30,
        rejection_logs: Iterable[Mapping[str, object]] = (),
    ) -> dict:
        start = request.event_time - timedelta(seconds=window_seconds)
        end = request.event_time + timedelta(seconds=window_seconds)
        limitations = []
        with self.connect(self.source) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"select {self._deal_columns} from `{self.schema}`.`{self.deals_table}` where Deal = %s",
                    (request.ticket,),
                )
                exact_rows = list(cur.fetchall())
                if not exact_rows:
                    cur.execute(
                        f"""
                        select {self._deal_columns}
                        from `{self.schema}`.`{self.deals_table}`
                        where Login = %s and Time between %s and %s
                          and (`Order` = %s or PositionID = %s)
                        order by TimeMsc, Deal
                        """,
                        (request.login, start, end, request.ticket, request.ticket),
                    )
                    exact_rows = list(cur.fetchall())
                cur.execute(
                    f"""
                    select {self._deal_columns}
                    from `{self.schema}`.`{self.deals_table}`
                    where Login = %s and Time between %s and %s
                    order by TimeMsc, Deal
                    """,
                    (request.login, start, end),
                )
                window_rows = list(cur.fetchall())
                cur.execute(
                    f"""
                    select Login, Balance, Credit, Equity, Margin, MarginFree, MarginLevel
                    from `{self.schema}`.`mt5_accounts`
                    where Login = %s
                    """,
                    (request.login,),
                )
                account = cur.fetchone() or {}
                cur.execute(
                    f"""
                    select Symbol, TradeMode, OrderFlags, VolumeMin, VolumeStep, VolumeMax,
                           StopsLevel, Point, Digits
                    from `{self.schema}`.`mt5_symbols`
                    where Symbol = %s
                    """,
                    (request.symbol,),
                )
                symbol = cur.fetchone() or {}
                position_ids = sorted(
                    {
                        _int(row.get("PositionID"))
                        for row in [*exact_rows, *window_rows]
                        if _int(row.get("PositionID")) > 0
                    }
                )
                positions = []
                if position_ids:
                    placeholders = ",".join(["%s"] * len(position_ids))
                    cur.execute(
                        f"""
                        select Position, Login, Dealer, Symbol, Action, TimeCreate, TimeCreateMsc,
                               Volume, VolumeExt, PriceOpen, PriceCurrent, PriceSL, PriceTP, Comment
                        from `{self.schema}`.`mt5_positions`
                        where Login = %s and Position in ({placeholders})
                        order by Position
                        """,
                        (request.login, *position_ids),
                    )
                    positions = list(cur.fetchall())
        limitations.append(
            "The configured AC MT5 export exposes final deals/positions but no order request, dealer journal, or retcode table."
        )
        return build_trace_result(
            request,
            exact_rows=exact_rows,
            window_rows=window_rows,
            account=account,
            symbol=symbol,
            positions=positions,
            rejection_logs=rejection_logs,
            window_seconds=window_seconds,
            limitations=limitations,
        )
