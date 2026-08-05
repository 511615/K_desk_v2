"""Pure adapters from read-only MT4/MT5 rows to copy-pool factor evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Callable, Iterable, Mapping, Sequence

from copy_delay_replay_domain import (
    ACTION_BUY,
    ACTION_SELL,
    ENTRY_IN,
    ENTRY_OUT,
    PositionExecutionEvent,
    PositionLifecycle,
)
from copy_pool_factor_domain import AdjustedEquityPoint, TradeHoldingObservation
from copy_trading_live_core import filetime_to_datetime


ProductResolver = Callable[[object], str | None]


@dataclass(frozen=True)
class HistoryCoverage:
    lifecycle_complete: bool
    daily_equity_complete: bool
    intraday_equity_complete: bool
    holding_path_complete: bool
    tick_complete: bool
    reasons: tuple[str, ...]

    @property
    def factor_ready(self) -> bool:
        return (
            self.lifecycle_complete
            and self.daily_equity_complete
            and self.intraday_equity_complete
            and self.holding_path_complete
            and self.tick_complete
            and not self.reasons
        )


def _value(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _aware(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("History datetime values must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _number(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if isfinite(result) else default


def _mt5_lots(row: Mapping[str, Any]) -> float:
    volume_ext = _number(_value(row, "VolumeExt", "volume_ext"))
    if volume_ext > 0:
        return volume_ext / 100_000_000.0
    return _number(_value(row, "Volume", "volume")) / 10_000.0


def build_mt5_lifecycles(
    rows: Iterable[Mapping[str, Any]],
    *,
    account_key: str,
    product_resolver: ProductResolver,
    money_scale: float = 1.0,
) -> tuple[PositionLifecycle, ...]:
    """Build completed source Position lifecycles without dropping losing Positions."""
    grouped: dict[tuple[str, str], list[PositionExecutionEvent]] = {}
    contracts: dict[tuple[str, str], float] = {}
    rates: dict[tuple[str, str], float] = {}
    signed_lots: dict[tuple[str, str], float] = {}
    for input_index, row in enumerate(rows):
        action = int(_value(row, "Action", "action", default=-1))
        entry = int(_value(row, "Entry", "entry", default=-1))
        if action not in (ACTION_BUY, ACTION_SELL) or entry not in (0, 1, 2, 3):
            continue
        product = product_resolver(_value(row, "Symbol", "symbol", default=""))
        if product is None:
            continue
        position_id = str(_value(row, "PositionID", "position_id", default=""))
        if not position_id:
            continue
        lots = _mt5_lots(row)
        if lots <= 0:
            continue
        key = (position_id, product)
        event = PositionExecutionEvent(
            event_id=str(_value(row, "Deal", "deal", default=input_index)),
            time_msc=int(_value(row, "TimeMscEpoch", "time_msc", "TimeMsc", default=0)),
            entry=entry,
            action=action,
            lots=lots,
            commission=_number(_value(row, "Commission", "commission")) * money_scale,
            fee=_number(_value(row, "Fee", "fee")) * money_scale,
            swap=_number(_value(row, "Storage", "storage", "swap")) * money_scale,
            source_profit=_number(_value(row, "Profit", "profit")) * money_scale,
            source_sequence=int(_value(row, "Deal", "deal", default=input_index)),
            source_price=_number(_value(row, "Price", "price")),
        )
        grouped.setdefault(key, []).append(event)
        contracts[key] = max(
            contracts.get(key, 0.0),
            _number(_value(row, "ContractSize", "contract_size")),
        )
        rates[key] = max(
            rates.get(key, 0.0),
            _number(_value(row, "RateProfit", "rate_profit"), default=1.0),
        )
        signed_lots[key] = signed_lots.get(key, 0.0) + (lots if action == ACTION_BUY else -lots)

    output: list[PositionLifecycle] = []
    for key, events in grouped.items():
        if abs(signed_lots.get(key, 0.0)) > 1e-8:
            continue
        position_id, product = key
        output.append(
            PositionLifecycle(
                account_key=account_key,
                product=product,
                position_id=position_id,
                contract_size=max(contracts.get(key, 0.0), 1e-12),
                profit_rate=max(rates.get(key, 0.0), 1e-12),
                events=tuple(sorted(events, key=lambda item: (item.time_msc, item.source_sequence))),
            )
        )
    return tuple(sorted(output, key=lambda item: (item.product, str(item.position_id))))


def build_mt4_lifecycles(
    rows: Iterable[Mapping[str, Any]],
    *,
    account_key: str,
    product_resolver: ProductResolver,
    contract_size_resolver: Callable[[str], float],
    money_scale: float = 1.0,
) -> tuple[PositionLifecycle, ...]:
    output: list[PositionLifecycle] = []
    for input_index, row in enumerate(rows):
        command = int(_value(row, "CMD", "cmd", default=-1))
        if command not in (0, 1):
            continue
        opened = _aware(_value(row, "OPEN_TIME", "open_time"))
        closed = _aware(_value(row, "CLOSE_TIME", "close_time"))
        if closed <= opened:
            continue
        product = product_resolver(_value(row, "SYMBOL", "symbol", default=""))
        if product is None:
            continue
        lots = _number(_value(row, "VOLUME", "volume")) / 100.0
        if lots <= 0:
            continue
        ticket = str(_value(row, "TICKET", "ticket", default=input_index))
        entry_action = ACTION_BUY if command == 0 else ACTION_SELL
        exit_action = ACTION_SELL if command == 0 else ACTION_BUY
        output.append(
            PositionLifecycle(
                account_key=account_key,
                product=product,
                position_id=ticket,
                contract_size=max(float(contract_size_resolver(product)), 1e-12),
                profit_rate=1.0,
                events=(
                    PositionExecutionEvent(
                        event_id=f"{ticket}:open",
                        time_msc=int(opened.timestamp() * 1000),
                        entry=ENTRY_IN,
                        action=entry_action,
                        lots=lots,
                        source_sequence=input_index * 2,
                        source_price=_number(_value(row, "OPEN_PRICE", "open_price")),
                    ),
                    PositionExecutionEvent(
                        event_id=f"{ticket}:close",
                        time_msc=int(closed.timestamp() * 1000),
                        entry=ENTRY_OUT,
                        action=exit_action,
                        lots=lots,
                        commission=_number(_value(row, "COMMISSION", "commission")) * money_scale,
                        fee=_number(_value(row, "TAXES", "taxes")) * money_scale,
                        swap=_number(_value(row, "SWAPS", "swaps")) * money_scale,
                        source_profit=_number(_value(row, "PROFIT", "profit")) * money_scale,
                        source_sequence=input_index * 2 + 1,
                        source_price=_number(_value(row, "CLOSE_PRICE", "close_price")),
                    ),
                ),
            )
        )
    return tuple(sorted(output, key=lambda item: (item.product, str(item.position_id))))


def build_mt5_equity_points(
    rows: Iterable[Mapping[str, Any]],
    *,
    money_scale: float = 1.0,
) -> tuple[AdjustedEquityPoint, ...]:
    """Use ProfitEquity and remove only external/agent/SO ledger movements."""
    fields = (
        "DailyBalance",
        "DailyCredit",
        "DailyCharge",
        "DailyCorrection",
        "DailyBonus",
        "DailyAgent",
        "DailySOCompensation",
        "DailySOCompensationCredit",
    )
    points: list[AdjustedEquityPoint] = []
    for row in rows:
        timestamp_raw = _value(row, "Timestamp", "timestamp")
        timestamp = filetime_to_datetime(int(timestamp_raw))
        points.append(
            AdjustedEquityPoint(
                timestamp=timestamp,
                equity_usd=_number(_value(row, "ProfitEquity", "profit_equity")) * money_scale,
                external_cashflow_usd=sum(_number(_value(row, field)) for field in fields) * money_scale,
            )
        )
    return tuple(sorted(points, key=lambda item: item.timestamp))


def build_mt4_equity_points(
    rows: Iterable[Mapping[str, Any]],
    *,
    money_scale: float = 1.0,
) -> tuple[AdjustedEquityPoint, ...]:
    ordered = sorted(rows, key=lambda row: _aware(_value(row, "TIME", "time")))
    points: list[AdjustedEquityPoint] = []
    previous_credit: float | None = None
    for row in ordered:
        credit = _number(_value(row, "CREDIT", "credit"))
        credit_change = 0.0 if previous_credit is None else credit - previous_credit
        points.append(
            AdjustedEquityPoint(
                timestamp=_aware(_value(row, "TIME", "time")),
                equity_usd=_number(_value(row, "EQUITY", "equity")) * money_scale,
                external_cashflow_usd=(
                    _number(_value(row, "DEPOSIT", "deposit")) + credit_change
                ) * money_scale,
            )
        )
        previous_credit = credit
    return tuple(points)


def holding_observations_from_lifecycles(
    lifecycles: Iterable[PositionLifecycle],
) -> tuple[TradeHoldingObservation, ...]:
    """Build time/swap observations; MAE and loss-addition coverage remains caller-owned."""
    output: list[TradeHoldingObservation] = []
    for lifecycle in lifecycles:
        events = sorted(lifecycle.events, key=lambda item: (item.time_msc, item.source_sequence))
        if len(events) < 2:
            continue
        output.append(
            TradeHoldingObservation(
                opened_at=datetime.fromtimestamp(events[0].time_msc / 1000.0, tz=timezone.utc),
                closed_at=datetime.fromtimestamp(events[-1].time_msc / 1000.0, tz=timezone.utc),
                swap_usd=sum(event.swap for event in events),
                gross_profit_usd=sum(event.source_profit for event in events),
            )
        )
    return tuple(output)


def holding_observations_from_snapshot_paths(
    lifecycles: Iterable[PositionLifecycle],
    snapshots_by_position: Mapping[str, Sequence[tuple[datetime, float]]],
) -> tuple[tuple[TradeHoldingObservation, ...], bool]:
    """Calculate loss duration and loss-time additions from complete Position paths."""
    output: list[TradeHoldingObservation] = []
    complete = True
    for lifecycle in lifecycles:
        events = sorted(lifecycle.events, key=lambda item: (item.time_msc, item.source_sequence))
        if len(events) < 2:
            complete = False
            continue
        opened = datetime.fromtimestamp(events[0].time_msc / 1000.0, tz=timezone.utc)
        closed = datetime.fromtimestamp(events[-1].time_msc / 1000.0, tz=timezone.utc)
        path = sorted(
            (
                (_aware(timestamp), float(floating))
                for timestamp, floating in snapshots_by_position.get(str(lifecycle.position_id), ())
                if opened <= _aware(timestamp) <= closed
            ),
            key=lambda item: item[0],
        )
        if not path:
            complete = False
            output.append(TradeHoldingObservation(
                opened, closed, sum(item.swap for item in events),
                sum(item.source_profit for item in events),
            ))
            continue
        long_loss = 0.0
        for index, (timestamp, floating) in enumerate(path):
            next_timestamp = path[index + 1][0] if index + 1 < len(path) else closed
            if floating < 0:
                long_loss += max(0.0, (next_timestamp - timestamp).total_seconds())
        additions_while_loss = False
        entry_events = [item for item in events if item.entry in (ENTRY_IN, 2)]
        for event in entry_events[1:]:
            event_time = datetime.fromtimestamp(event.time_msc / 1000.0, tz=timezone.utc)
            prior = [floating for timestamp, floating in path if timestamp <= event_time]
            if prior and prior[-1] < 0:
                additions_while_loss = True
                break
        output.append(TradeHoldingObservation(
            opened_at=opened,
            closed_at=closed,
            swap_usd=sum(item.swap for item in events),
            gross_profit_usd=sum(item.source_profit for item in events),
            long_loss_seconds=min(long_loss, max(0.0, (closed - opened).total_seconds())),
            additions_while_loss=additions_while_loss,
        ))
    return tuple(output), complete


def max_simultaneous_losing_positions(
    lifecycles: Iterable[PositionLifecycle],
    snapshots_by_position: Mapping[str, Sequence[tuple[datetime, float]]],
    *,
    as_of: datetime,
    window_days: int = 30,
) -> int:
    """Return the maximum negative Position count in observed minute snapshots."""
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    end = _aware(as_of)
    start = end - timedelta(days=window_days)
    selected_ids = {str(item.position_id) for item in lifecycles}
    latest: dict[tuple[datetime, str], tuple[datetime, float]] = {}
    for position_id in selected_ids:
        for timestamp, floating in snapshots_by_position.get(position_id, ()):
            observed_at = _aware(timestamp)
            if not start <= observed_at <= end:
                continue
            bucket = observed_at.replace(second=0, microsecond=0)
            key = (bucket, position_id)
            prior = latest.get(key)
            if prior is None or observed_at >= prior[0]:
                latest[key] = (observed_at, float(floating))
    counts: dict[datetime, int] = {}
    for (bucket, _position_id), (_timestamp, floating) in latest.items():
        if floating < 0:
            counts[bucket] = counts.get(bucket, 0) + 1
    return max(counts.values(), default=0)


def coverage_from_flags(
    *,
    lifecycle_complete: bool,
    daily_equity_complete: bool,
    intraday_equity_complete: bool,
    holding_path_complete: bool,
    tick_complete: bool,
) -> HistoryCoverage:
    flags = {
        "lifecycle_complete": lifecycle_complete,
        "daily_equity_complete": daily_equity_complete,
        "intraday_equity_complete": intraday_equity_complete,
        "holding_path_complete": holding_path_complete,
        "tick_complete": tick_complete,
    }
    reasons = tuple(f"missing_{name}" for name, present in flags.items() if not present)
    return HistoryCoverage(**flags, reasons=reasons)
