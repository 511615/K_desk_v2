"""Pure reconstruction of an account's historical cash and credit timeline."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _time(row: dict[str, Any]) -> str:
    return _text(row.get("timestamp") or row.get("TimeMsc") or row.get("Time") or row.get("OPEN_TIME"))


def _sort_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (_time(row), _integer(row.get("sequence") or row.get("Deal") or row.get("TICKET"), 0), _text(row.get("id")))


def _mt4_amount(row: dict[str, Any], scale: float) -> float:
    return (
        _number(row.get("PROFIT"))
        + _number(row.get("COMMISSION"))
        + _number(row.get("SWAPS"))
        + _number(row.get("TAXES"))
    ) * scale


def _mt5_amount(row: dict[str, Any], scale: float) -> float:
    return (
        _number(row.get("Profit"))
        + _number(row.get("Commission"))
        + _number(row.get("Storage"))
        + _number(row.get("Fee"))
    ) * scale


def _has_prefix(comment: str, prefixes: tuple[str, ...]) -> bool:
    return comment.startswith(prefixes)


def _is_internal_transfer(comment: str) -> bool:
    return _has_prefix(comment, ("TFM-", "TFH-", "TRS-", "CRM-T")) or "INTERNAL TRANSFER" in comment


def _mt4_event_timestamp(source: dict[str, Any]) -> str:
    command = _integer(source.get("CMD"))
    explicit = _text(source.get("timestamp"))
    opened = _text(source.get("OPEN_TIME"))
    closed = _text(source.get("CLOSE_TIME"))
    if command in {0, 1} and opened and closed and closed > opened:
        return closed
    return explicit or opened


def _mt5_anchor_timestamp(source: dict[str, Any]) -> str:
    explicit = _text(source.get("timestamp"))
    if explicit:
        return explicit
    value = source.get("Timestamp", source.get("Datetime"))
    text = _text(value)
    if not text:
        return ""
    if text.isdigit() and len(text) >= 15:
        try:
            seconds = (int(text) - 116444736000000000) / 10_000_000
            local = datetime.fromtimestamp(seconds, tz=UTC).astimezone(timezone(timedelta(hours=8)))
            return local.strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return ""
    return text


def _liquidation_evidence(event: dict[str, Any]) -> dict[str, str] | None:
    if event["kind"] == "negative_balance_clear":
        return {
            "type": "negative_balance_clear",
            "label": "负余额清零",
            "source": "清零资金流水",
        }
    reason = _integer(event.get("reason"))
    platform = event["platform"]
    if event["kind"] == "trade_close" and ((platform == "MT4" and reason == 5) or (platform == "MT5" and reason == 6)):
        return {
            "type": "platform_stop_out",
            "label": "平台强平",
            "source": f"{platform} Reason={reason}",
        }
    return None


def _normalize_event(platform: str, source: dict[str, Any], scale: float) -> dict[str, Any] | None:
    comment = _text(source.get("COMMENT") if platform == "MT4" else source.get("Comment"))
    upper = comment.upper()
    timestamp = _mt4_event_timestamp(source) if platform == "MT4" else _time(source)
    if not timestamp:
        return None
    event_id = _text(source.get("id") or source.get("TICKET") or source.get("Deal"))
    event: dict[str, Any] = {
        "id": event_id,
        "timestamp": timestamp,
        "platform": platform,
        "orderId": _text(source.get("Order") or source.get("TICKET") or source.get("Deal")),
        "positionId": _text(source.get("PositionID") or source.get("Position")),
        "symbol": _text(source.get("SYMBOL") or source.get("Symbol")),
        "comment": comment,
        "kind": "other",
        "deltaBalance": 0.0,
        "deltaCredit": 0.0,
        "realizedPnl": 0.0,
        "externalCashflow": 0.0,
        "amount": 0.0,
        "reason": _integer(source.get("REASON") if platform == "MT4" else source.get("Reason")),
    }

    if platform == "MT4":
        command = _integer(source.get("CMD"))
        amount = _mt4_amount(source, scale)
        event["amount"] = round(amount, 8)
        if command in {0, 1}:
            opened = _text(source.get("OPEN_TIME"))
            closed = _text(source.get("CLOSE_TIME"))
            if not closed or not opened or closed <= opened:
                event["kind"] = "trade_open"
            else:
                event["kind"] = "trade_close"
                event["deltaBalance"] = amount
                event["realizedPnl"] = amount
        elif command == 7:
            event["kind"] = "internal_transfer" if _is_internal_transfer(upper) else (
                "bonus_grant" if amount >= 0 else "bonus_remove"
            )
            event["deltaCredit"] = amount
        elif command == 6:
            if upper.startswith(("RST-", "CCB-")) or "NEGATIVE BALANCE" in upper or "ZERO BALANCE" in upper:
                event["kind"] = "negative_balance_clear"
            elif upper.startswith(("CPS_", "COMP")):
                event["kind"] = "compensation"
            elif _is_internal_transfer(upper):
                event["kind"] = "internal_transfer"
            elif upper.startswith(("DEP-", "CRM-DP-")) and amount > 0:
                event["kind"] = "deposit"
                event["externalCashflow"] = amount
            elif upper.startswith(("WDR-", "CRM-CW", "IPD")) and amount < 0:
                event["kind"] = "withdrawal"
                event["externalCashflow"] = amount
            else:
                event["kind"] = "other_balance"
            event["deltaBalance"] = amount
        else:
            return None
    else:
        action = _integer(source.get("Action"))
        entry = _integer(source.get("Entry"))
        amount = _mt5_amount(source, scale)
        event["amount"] = round(amount, 8)
        if action in {0, 1}:
            event["kind"] = "trade_close" if entry in {1, 2, 3} else "trade_open"
            event["deltaBalance"] = amount
            if entry in {1, 2, 3}:
                event["realizedPnl"] = amount
        elif action == 2:
            if upper.startswith("DEP-RS"):
                event["kind"] = "cash_reversal"
            elif _is_internal_transfer(upper):
                event["kind"] = "internal_transfer"
            elif _has_prefix(upper, ("RST-", "CCB-")) or "NEGATIVE BALANCE" in upper or "ZERO BALANCE" in upper:
                event["kind"] = "negative_balance_clear"
            elif _has_prefix(upper, ("DEP-", "CRM-DP-")) and amount > 0:
                event["kind"] = "deposit"
                event["externalCashflow"] = amount
            elif _has_prefix(upper, ("WDR-", "CRM-CW", "IPD")) and amount < 0:
                event["kind"] = "withdrawal"
                event["externalCashflow"] = amount
            else:
                event["kind"] = "other_balance"
            event["deltaBalance"] = amount
        elif action == 3 or action == 6:
            event["kind"] = "internal_transfer" if _is_internal_transfer(upper) else (
                "bonus_grant" if amount >= 0 else "bonus_remove"
            )
            event["deltaCredit"] = amount
        elif action in {4, 5}:
            event["kind"] = "adjustment"
            event["deltaBalance"] = amount
        else:
            return None

    event["deltaBalance"] = round(event["deltaBalance"], 8)
    event["deltaCredit"] = round(event["deltaCredit"], 8)
    event["realizedPnl"] = round(event["realizedPnl"], 8)
    event["externalCashflow"] = round(event["externalCashflow"], 8)
    return event


def _normalize_anchor(row: dict[str, Any], platform: str, scale: float) -> dict[str, Any] | None:
    timestamp = _mt5_anchor_timestamp(row) if platform == "MT5" else _text(row.get("timestamp") or row.get("TIME"))
    if not timestamp:
        return None
    if platform == "MT5":
        balance = _number(row.get("Balance", row.get("balance"))) * scale
        credit = _number(row.get("Credit", row.get("credit"))) * scale
        equity = _number(row.get("ProfitEquity", row.get("equity"))) * scale
    else:
        balance = _number(row.get("BALANCE", row.get("balance"))) * scale
        credit = _number(row.get("CREDIT", row.get("credit"))) * scale
        equity = _number(row.get("EQUITY", row.get("equity"))) * scale
    return {
        "timestamp": timestamp,
        "kind": "daily_anchor",
        "balance": round(balance, 8),
        "credit": round(credit, 8),
        "equity": round(equity, 8),
        "equityStatus": "authoritative_daily",
    }


def _normalize_current_anchor(row: dict[str, Any], scale: float) -> dict[str, Any] | None:
    timestamp = _text(row.get("timestamp"))
    if not timestamp:
        return None
    return {
        "timestamp": timestamp,
        "kind": "current_anchor",
        "balance": round(_number(row.get("balance", row.get("Balance"))) * scale, 8),
        "credit": round(_number(row.get("credit", row.get("Credit"))) * scale, 8),
        "equity": round(_number(row.get("equity", row.get("Equity"))) * scale, 8),
        "equityStatus": "authoritative_current",
    }


def build_historical_funds(
    *,
    platform: str,
    currency: str,
    events: Iterable[dict[str, Any]],
    anchors: Iterable[dict[str, Any]] = (),
    current_anchor: dict[str, Any] | None = None,
    money_scale: float = 1.0,
) -> dict[str, Any]:
    platform = _text(platform).upper() or "MT4"
    scale = money_scale or 1.0
    normalized = sorted(
        (item for item in (_normalize_event(platform, dict(row), scale) for row in events) if item),
        key=_sort_key,
    )
    normalized_anchors = sorted(
        (item for item in (_normalize_anchor(dict(row), platform, scale) for row in anchors) if item),
        key=lambda item: item["timestamp"],
    )
    normalized_current_anchor = _normalize_current_anchor(current_anchor or {}, scale)
    reconstruct_from_current = not normalized_anchors and normalized_current_anchor is not None
    curve: list[dict[str, Any]] = []
    replayed_events: list[dict[str, Any]] = []
    balance: float | None = None
    credit: float | None = None
    if reconstruct_from_current:
        balance = normalized_current_anchor["balance"] - sum(item["deltaBalance"] for item in normalized)
        credit = normalized_current_anchor["credit"] - sum(item["deltaCredit"] for item in normalized)
    anchor_index = -1
    for event_index, event in enumerate(normalized):
        while anchor_index + 1 < len(normalized_anchors) and normalized_anchors[anchor_index + 1]["timestamp"] <= event["timestamp"]:
            anchor_index += 1
            anchor = normalized_anchors[anchor_index]
            balance, credit = anchor["balance"], anchor["credit"]
            curve.append(dict(anchor))
        row = dict(event)
        if balance is None or credit is None:
            row.update({"balance": None, "credit": None, "equity": None, "equityStatus": "before_first_anchor"})
        else:
            balance += event["deltaBalance"]
            credit += event["deltaCredit"]
            # Daily account rows and position snapshots are the only authoritative equity observations.
            row.update({
                "balance": round(balance, 8),
                "credit": round(credit, 8),
                "equity": None,
                "equityStatus": "missing_intraday_snapshot",
            })
        row["eventIndex"] = event_index
        row["liquidation"] = _liquidation_evidence(row)
        replayed_events.append(row)
        curve.append(row)
    for anchor in normalized_anchors[anchor_index + 1:]:
        if not curve or curve[-1]["timestamp"] != anchor["timestamp"]:
            curve.append(dict(anchor))
    if reconstruct_from_current and (not curve or curve[-1]["timestamp"] != normalized_current_anchor["timestamp"]):
        curve.append(dict(normalized_current_anchor))

    liquidation_points = [
        {
            "eventIndex": item["eventIndex"],
            "id": item["id"],
            "timestamp": item["timestamp"],
            "orderId": item["orderId"],
            "symbol": item["symbol"],
            **item["liquidation"],
        }
        for item in replayed_events
        if item["liquidation"] is not None
    ]
    summary = {
        "eventCount": len(normalized),
        "curvePointCount": len(curve),
        "anchorCount": len(normalized_anchors),
        "externalDeposit": round(sum(max(item["externalCashflow"], 0) for item in normalized if item["kind"] == "deposit"), 8),
        "externalWithdrawal": round(sum(abs(item["externalCashflow"]) for item in normalized if item["kind"] == "withdrawal"), 8),
        "internalTransfer": round(sum(item["deltaBalance"] for item in normalized if item["kind"] == "internal_transfer"), 8),
        "internalCreditTransfer": round(sum(item["deltaCredit"] for item in normalized if item["kind"] == "internal_transfer"), 8),
        "bonusGranted": round(sum(max(item["deltaCredit"], 0) for item in normalized if item["kind"] == "bonus_grant"), 8),
        "bonusRemoved": round(sum(abs(item["deltaCredit"]) for item in normalized if item["kind"] == "bonus_remove"), 8),
        "negativeBalanceCleared": round(sum(abs(item["deltaBalance"]) for item in normalized if item["kind"] == "negative_balance_clear"), 8),
        "liquidationCount": len(liquidation_points),
        "externalNetDeposit": round(
            sum(item["externalCashflow"] for item in normalized if item["kind"] in {"deposit", "withdrawal"}), 8
        ),
        "currency": _text(currency) or "USD",
        "moneyScale": scale,
        "equityCoverage": "daily_anchors_only" if normalized_anchors else (
            "current_anchor_only" if normalized_current_anchor else "cash_credit_only"
        ),
        "reconstructionMode": "daily_anchors" if normalized_anchors else (
            "current_account_anchor" if normalized_current_anchor else "unanchored"
        ),
        "dataStatus": "complete" if normalized else "empty",
    }
    if curve:
        summary.update({
            "firstTimestamp": curve[0]["timestamp"],
            "lastTimestamp": curve[-1]["timestamp"],
            "balanceAtEnd": curve[-1].get("balance"),
            "creditAtEnd": curve[-1].get("credit"),
            "equityAtEnd": curve[-1].get("equity"),
        })
    return {
        "summary": summary,
        "events": replayed_events,
        "curve": curve,
        "liquidationPoints": liquidation_points,
    }
