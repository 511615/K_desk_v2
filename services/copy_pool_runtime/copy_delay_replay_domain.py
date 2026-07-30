"""Pure source-reconciled Tick replay domain for copy-delay eligibility."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Iterable, Sequence


ENTRY_IN = 0
ENTRY_OUT = 1
ENTRY_INOUT = 2
ENTRY_OUT_BY = 3
ACTION_BUY = 0
ACTION_SELL = 1


@dataclass(frozen=True)
class QuoteTick:
    time_msc: int
    bid: float
    ask: float


@dataclass(frozen=True)
class PositionExecutionEvent:
    event_id: str | int
    time_msc: int
    entry: int
    action: int
    lots: float
    commission: float = 0.0
    fee: float = 0.0
    swap: float = 0.0
    source_profit: float = 0.0
    source_sequence: int = 0
    source_price: float = 0.0
    volume_closed_lots: float | None = None


@dataclass(frozen=True)
class PositionLifecycle:
    account_key: str
    product: str
    position_id: str | int
    contract_size: float
    profit_rate: float
    events: tuple[PositionExecutionEvent, ...]


@dataclass(frozen=True)
class ReconstructedAction:
    action_id: str
    event_key: tuple[int, int, int]
    event: PositionExecutionEvent
    kind: str
    side: int
    lots: float
    cost: float
    signed_cost: float
    opening_action_id: str | None = None


@dataclass(frozen=True)
class ReconstructedLifecycle:
    actions: tuple[ReconstructedAction, ...]
    event_records: tuple[tuple[tuple[int, int, int], PositionExecutionEvent], ...]
    invalid_reasons: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.invalid_reasons


@dataclass(frozen=True)
class SourceReconciliation:
    reconciled: bool
    error_usd: float
    expected_net_usd: float
    reconstructed_net_usd: float
    reason: str | None


@dataclass(frozen=True)
class ExecutedTrade:
    opening_action_id: str
    closing_action_id: str
    lots: float
    net_profit: float
    entry_executable: bool
    exit_executable: bool


@dataclass(frozen=True)
class ReplayResult:
    valid: bool
    invalid_reasons: tuple[str, ...]
    entry_delay_ms: int
    exit_delay_ms: int
    net_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    win_rate: float
    entry_executable_ratio: float
    exit_executable_ratio: float
    combined_executable_ratio: float
    average_net_profit: float
    copy_cost_per_trade: float
    completed_trades: int
    executed_trades: int
    entry_signals: int
    exit_signals: int
    completed_source_events: int
    executed_source_events: int
    trades: tuple[ExecutedTrade, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BreakEvenDelay:
    delay_ms: float
    censored_lower_bound: bool


@dataclass(frozen=True)
class DelayScenario:
    delay_ms: int
    entry: ReplayResult
    exit: ReplayResult
    combined: ReplayResult
    retained_profit: float
    pf_retention: float


@dataclass(frozen=True)
class DelayEvaluation:
    baseline: ReplayResult
    scenarios: tuple[DelayScenario, ...]
    actual_entry_p95_ms: int
    actual_exit_p95_ms: int
    actual_entry: ReplayResult
    actual_exit: ReplayResult
    actual_combined: ReplayResult
    entry_break_even: BreakEvenDelay
    exit_break_even: BreakEvenDelay
    combined_break_even: BreakEvenDelay
    conservative_break_even: BreakEvenDelay
    delay_score: float
    reconciled: bool
    reconciliation_error: float
    reconciliation_reason: str | None
    hard_gate_passed: bool
    hard_gate_reasons: tuple[str, ...]


@dataclass
class _OpenLot:
    action: ReconstructedAction
    lots: float


def _event_key(event: PositionExecutionEvent, input_index: int) -> tuple[int, int, int]:
    return (int(event.time_msc), int(event.source_sequence), input_index)


def _side(action: int) -> int | None:
    if action == ACTION_BUY:
        return 1
    if action == ACTION_SELL:
        return -1
    return None


def _signed_cost(event: PositionExecutionEvent) -> float:
    return float(event.commission) + float(event.fee) + float(event.swap)


def _replay_cost(event: PositionExecutionEvent) -> float:
    return max(0.0, -_signed_cost(event))


def _valid_event(event: PositionExecutionEvent) -> str | None:
    if event.entry not in (ENTRY_IN, ENTRY_OUT, ENTRY_INOUT, ENTRY_OUT_BY):
        return f"{event.event_id}:invalid_entry"
    if _side(event.action) is None:
        return f"{event.event_id}:invalid_action"
    if not isfinite(event.lots) or event.lots <= 0:
        return f"{event.event_id}:invalid_lots"
    if not isinstance(event.time_msc, int) or not isinstance(event.source_sequence, int):
        return f"{event.event_id}:invalid_ordering"
    if not isfinite(event.source_price) or event.source_price <= 0:
        return f"{event.event_id}:invalid_source_price"
    if event.entry == ENTRY_IN and abs(event.source_profit) > 1e-9:
        return f"{event.event_id}:source_profit_on_entry"
    if event.volume_closed_lots is not None:
        value = float(event.volume_closed_lots)
        if not isfinite(value) or value < 0 or value > event.lots + 1e-10:
            return f"{event.event_id}:invalid_volume_closed_lots"
    return None


def reconstruct_lifecycle(lifecycle: PositionLifecycle) -> ReconstructedLifecycle:
    """FIFO reconstruct a single source position in source sequence order."""
    reasons: list[str] = []
    if not isfinite(lifecycle.contract_size) or lifecycle.contract_size <= 0:
        reasons.append("invalid_contract_size")
    if not isfinite(lifecycle.profit_rate) or lifecycle.profit_rate <= 0:
        reasons.append("invalid_profit_rate")
    records = [(_event_key(event, index), event) for index, event in enumerate(lifecycle.events)]
    records.sort(key=lambda item: item[0])
    actions: list[ReconstructedAction] = []
    open_lots: list[_OpenLot] = []

    def add_open(event_key: tuple[int, int, int], event: PositionExecutionEvent, side: int, lots: float, cost: float, signed_cost: float, suffix: str) -> None:
        action = ReconstructedAction(
            action_id=f"{event_key[0]}:{event_key[1]}:{event_key[2]}:{suffix}",
            event_key=event_key,
            event=event,
            kind="entry",
            side=side,
            lots=lots,
            cost=cost,
            signed_cost=signed_cost,
        )
        actions.append(action)
        open_lots.append(_OpenLot(action, lots))

    def close_lots(event_key: tuple[int, int, int], event: PositionExecutionEvent, action_side: int, lots: float, cost: float, signed_cost: float, suffix: str) -> bool:
        if not open_lots:
            reasons.append(f"{event.event_id}:close_without_open")
            return False
        open_side = open_lots[0].action.side
        if action_side == open_side:
            reasons.append(f"{event.event_id}:close_action_same_direction")
            return False
        if any(item.action.side != open_side for item in open_lots):
            reasons.append(f"{event.event_id}:mixed_open_direction")
            return False
        available = sum(item.lots for item in open_lots)
        if lots <= 0 or lots > available + 1e-10:
            reasons.append(f"{event.event_id}:close_exceeds_open")
            return False
        remaining = lots
        total = lots
        while remaining > 1e-10:
            item = open_lots[0]
            closed = min(item.lots, remaining)
            actions.append(
                ReconstructedAction(
                    action_id=f"{event_key[0]}:{event_key[1]}:{event_key[2]}:{suffix}:{len(actions)}",
                    event_key=event_key,
                    event=event,
                    kind="exit",
                    side=action_side,
                    lots=closed,
                    cost=cost * closed / total,
                    signed_cost=signed_cost * closed / total,
                    opening_action_id=item.action.action_id,
                )
            )
            item.lots -= closed
            remaining -= closed
            if item.lots <= 1e-10:
                open_lots.pop(0)
        return True

    for event_key, event in records:
        error = _valid_event(event)
        if error:
            reasons.append(error)
            continue
        side = _side(event.action)
        assert side is not None
        replay_cost = _replay_cost(event)
        signed_cost = _signed_cost(event)
        if event.entry == ENTRY_IN:
            if open_lots and open_lots[0].action.side != side:
                reasons.append(f"{event.event_id}:opposite_open_without_reversal")
                continue
            add_open(event_key, event, side, event.lots, replay_cost, signed_cost, "open")
        elif event.entry in (ENTRY_OUT, ENTRY_OUT_BY):
            if event.volume_closed_lots is not None and abs(event.volume_closed_lots - event.lots) > 1e-10:
                reasons.append(f"{event.event_id}:out_volume_closed_mismatch")
                continue
            close_lots(event_key, event, side, event.lots, replay_cost, signed_cost, "close")
        else:
            if not open_lots:
                reasons.append(f"{event.event_id}:reversal_without_open")
                continue
            available = sum(item.lots for item in open_lots)
            closed_lots = float(event.volume_closed_lots) if event.volume_closed_lots is not None else min(event.lots, available)
            if closed_lots > available + 1e-10:
                reasons.append(f"{event.event_id}:reversal_close_exceeds_open")
                continue
            remainder = event.lots - closed_lots
            if remainder > 1e-10 and abs(closed_lots - available) > 1e-10:
                reasons.append(f"{event.event_id}:reversal_leaves_old_direction")
                continue
            close_cost = replay_cost * closed_lots / event.lots
            close_signed = signed_cost * closed_lots / event.lots
            if closed_lots > 1e-10 and not close_lots(event_key, event, side, closed_lots, close_cost, close_signed, "reverse_close"):
                continue
            if remainder > 1e-10:
                add_open(event_key, event, side, remainder, replay_cost - close_cost, signed_cost - close_signed, "reverse_open")

    if open_lots:
        reasons.append("unclosed_position")
    return ReconstructedLifecycle(tuple(actions), tuple(records), tuple(reasons))


def reconcile_source_lifecycle(
    lifecycle: PositionLifecycle,
    reconstruction: ReconstructedLifecycle | None = None,
    absolute_tolerance: float = 0.01,
    relative_tolerance: float = 1e-6,
) -> SourceReconciliation:
    """Reconcile source prices and signed source costs before delay eligibility is scored."""
    rebuilt = reconstruction or reconstruct_lifecycle(lifecycle)
    if not rebuilt.valid:
        return SourceReconciliation(False, 0.0, 0.0, 0.0, "invalid_lifecycle")
    opening: dict[str, ReconstructedAction] = {}
    reconstructed = 0.0
    for action in rebuilt.actions:
        if action.kind == "entry":
            opening[action.action_id] = action
            continue
        assert action.opening_action_id is not None
        source_open = opening.get(action.opening_action_id)
        if source_open is None:
            return SourceReconciliation(False, 0.0, 0.0, 0.0, "missing_source_opening")
        direction = -action.side
        gross = (action.event.source_price - source_open.event.source_price) * direction * action.lots * lifecycle.contract_size * lifecycle.profit_rate
        reconstructed += gross
        reconstructed += source_open.signed_cost * action.lots / source_open.lots
        reconstructed += action.signed_cost
    expected = sum(event.source_profit + _signed_cost(event) for event in lifecycle.events)
    error = reconstructed - expected
    tolerance = absolute_tolerance + relative_tolerance * max(1.0, abs(reconstructed), abs(expected))
    return SourceReconciliation(abs(error) <= tolerance, error, expected, reconstructed, None if abs(error) <= tolerance else "source_profit_reconciliation_mismatch")


@dataclass(frozen=True)
class PreparedQuotes:
    """Validated, sorted quote columns used repeatedly by scenario replay."""

    times: Sequence[int]
    bids: Sequence[float]
    asks: Sequence[float]

    def __len__(self) -> int:
        return len(self.times)


def prepare_validated_quote_array(ticks: Any) -> PreparedQuotes:
    """Use a validated structured cache array without expanding Tick objects."""
    names = getattr(getattr(ticks, "dtype", None), "names", None)
    if not names or not {"time_msc", "bid", "ask"}.issubset(names):
        raise TypeError("Validated quote arrays require time_msc, bid and ask columns")
    return PreparedQuotes(ticks["time_msc"], ticks["bid"], ticks["ask"])


def _valid_quotes(quotes: Iterable[QuoteTick] | PreparedQuotes) -> PreparedQuotes:
    if isinstance(quotes, PreparedQuotes):
        return quotes
    ordered = list(quotes)
    if any(not isfinite(item.bid) or not isfinite(item.ask) or item.bid <= 0 or item.ask < item.bid for item in ordered):
        raise ValueError("Quotes must contain valid two-sided bid/ask prices.")
    indexed = sorted(enumerate(ordered), key=lambda item: (item[1].time_msc, item[0]))
    values = tuple(item[1] for item in indexed)
    return PreparedQuotes(
        tuple(item.time_msc for item in values),
        tuple(item.bid for item in values),
        tuple(item.ask for item in values),
    )


def _quote_for_signal(quotes: PreparedQuotes, signal_time_msc: int, delay_ms: int, max_quote_wait_ms: int) -> QuoteTick | None:
    arrival = signal_time_msc + delay_ms
    index = bisect_left(quotes.times, arrival)
    if index >= len(quotes):
        return None
    quote = QuoteTick(
        int(quotes.times[index]), float(quotes.bids[index]), float(quotes.asks[index])
    )
    return quote if quote.time_msc - arrival <= max_quote_wait_ms else None


def _fill_price(quote: QuoteTick, side: int, slippage_price: float) -> float:
    return quote.ask + slippage_price if side > 0 else quote.bid - slippage_price


def replay_lifecycle(lifecycle: PositionLifecycle, quotes: Iterable[QuoteTick] | PreparedQuotes, entry_delay_ms: int = 0, exit_delay_ms: int = 0, max_quote_wait_ms: int = 2_000, slippage_price: float = 0.0) -> ReplayResult:
    """Replay Demo fills. Combined executability is measured per source close/reversal event, not FIFO leg."""
    if min(entry_delay_ms, exit_delay_ms, max_quote_wait_ms) < 0 or slippage_price < 0:
        raise ValueError("Delay, quote wait and slippage must be non-negative.")
    rebuilt = reconstruct_lifecycle(lifecycle)
    if not rebuilt.valid:
        return _invalid_result(rebuilt.invalid_reasons, entry_delay_ms, exit_delay_ms)
    ordered_quotes = _valid_quotes(quotes)
    outcomes: dict[tuple[int, int, int], dict[str, list[bool] | PositionExecutionEvent]] = {}
    for key, event in rebuilt.event_records:
        outcomes[key] = {"event": event, "entry": [], "exit": [], "pairs": []}
    opening: dict[str, tuple[float, bool, float, float]] = {}
    trades: list[ExecutedTrade] = []
    copy_cost_total = 0.0
    for action in rebuilt.actions:
        delay = entry_delay_ms if action.kind == "entry" else exit_delay_ms
        quote = _quote_for_signal(ordered_quotes, action.event.time_msc, delay, max_quote_wait_ms)
        executable = quote is not None
        outcome = outcomes[action.event_key][action.kind]
        assert isinstance(outcome, list)
        outcome.append(executable)
        if action.kind == "entry":
            opening[action.action_id] = (_fill_price(quote, action.side, slippage_price) if quote else 0.0, executable, action.cost, action.lots)
            continue
        assert action.opening_action_id is not None
        entry_price, entry_ok, entry_cost, opening_lots = opening[action.opening_action_id]
        pairs = outcomes[action.event_key]["pairs"]
        assert isinstance(pairs, list)
        pairs.append(entry_ok and executable)
        if not entry_ok or not executable:
            trades.append(ExecutedTrade(action.opening_action_id, action.action_id, action.lots, 0.0, entry_ok, executable))
            continue
        assert quote is not None
        exit_price = _fill_price(quote, action.side, slippage_price)
        direction = -action.side
        allocated_entry_cost = entry_cost * action.lots / opening_lots
        net = (exit_price - entry_price) * direction * action.lots * lifecycle.contract_size * lifecycle.profit_rate - allocated_entry_cost - action.cost
        copy_cost_total += allocated_entry_cost + action.cost
        trades.append(ExecutedTrade(action.opening_action_id, action.action_id, action.lots, net, True, True))
    entry_outcomes: list[bool] = []
    exit_outcomes: list[bool] = []
    combined_outcomes: list[bool] = []
    for record in outcomes.values():
        event = record["event"]
        assert isinstance(event, PositionExecutionEvent)
        entry_actions = record["entry"]
        exit_actions = record["exit"]
        pairs = record["pairs"]
        assert isinstance(entry_actions, list) and isinstance(exit_actions, list) and isinstance(pairs, list)
        if event.entry in (ENTRY_IN, ENTRY_INOUT):
            entry_outcomes.append(bool(entry_actions) and all(entry_actions))
        if event.entry in (ENTRY_OUT, ENTRY_OUT_BY, ENTRY_INOUT):
            exit_outcomes.append(bool(exit_actions) and all(exit_actions))
            combined_outcomes.append(bool(pairs) and all(pairs) and (event.entry != ENTRY_INOUT or (bool(entry_actions) and all(entry_actions))))
    executed = [item for item in trades if item.entry_executable and item.exit_executable]
    values = [item.net_profit for item in executed]
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    return ReplayResult(
        valid=True,
        invalid_reasons=(),
        entry_delay_ms=entry_delay_ms,
        exit_delay_ms=exit_delay_ms,
        net_profit=sum(values),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=None if gross_loss == 0 else gross_profit / gross_loss,
        win_rate=sum(value > 0 for value in values) / len(values) if values else 0.0,
        entry_executable_ratio=sum(entry_outcomes) / len(entry_outcomes) if entry_outcomes else 0.0,
        exit_executable_ratio=sum(exit_outcomes) / len(exit_outcomes) if exit_outcomes else 0.0,
        combined_executable_ratio=sum(combined_outcomes) / len(combined_outcomes) if combined_outcomes else 0.0,
        average_net_profit=sum(values) / len(values) if values else 0.0,
        copy_cost_per_trade=copy_cost_total / len(executed) if executed else 0.0,
        completed_trades=len(trades),
        executed_trades=len(executed),
        entry_signals=len(entry_outcomes),
        exit_signals=len(exit_outcomes),
        completed_source_events=len(combined_outcomes),
        executed_source_events=sum(combined_outcomes),
        trades=tuple(trades),
    )


def _invalid_result(reasons: tuple[str, ...], entry_delay_ms: int, exit_delay_ms: int) -> ReplayResult:
    return ReplayResult(False, reasons, entry_delay_ms, exit_delay_ms, 0.0, 0.0, 0.0, None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _retention(result: ReplayResult, baseline: ReplayResult) -> float:
    return _clamp(result.net_profit / baseline.net_profit) if baseline.net_profit > 0 else 0.0


def _pf_retention(result: ReplayResult, baseline: ReplayResult) -> float:
    if baseline.profit_factor is None:
        return 1.0 if result.profit_factor is None else 0.0
    if baseline.profit_factor == 0.0:
        if result.profit_factor == 0.0:
            return 0.0
        return 1.0
    if result.profit_factor is None:
        return 1.0
    return _clamp(result.profit_factor / baseline.profit_factor)


def _break_even(lifecycle: PositionLifecycle, quotes: Iterable[QuoteTick] | PreparedQuotes, delays_ms: tuple[int, ...], hold_p25_ms: int, mode: str, max_quote_wait_ms: int, slippage_price: float) -> BreakEvenDelay:
    baseline = replay_lifecycle(lifecycle, quotes, 0, 0, max_quote_wait_ms, slippage_price)
    if baseline.net_profit <= 0:
        return BreakEvenDelay(0.0, False)
    limit = min(30_000, max(0, hold_p25_ms // 3))
    candidates = sorted({0, *(delay for delay in delays_ms if delay <= limit)})
    probe = candidates[-1] + 500
    while probe <= limit:
        candidates.append(probe)
        probe += 500
    previous_delay = 0
    previous_net = baseline.net_profit
    for delay in candidates[1:]:
        entry_delay = delay if mode in ("entry", "combined") else 0
        exit_delay = delay if mode in ("exit", "combined") else 0
        current = replay_lifecycle(lifecycle, quotes, entry_delay, exit_delay, max_quote_wait_ms, slippage_price).net_profit
        if current <= 0:
            denominator = previous_net - current
            crossing = float(delay) if denominator <= 0 else previous_delay + (delay - previous_delay) * previous_net / denominator
            return BreakEvenDelay(float(crossing), False)
        previous_delay, previous_net = delay, current
    return BreakEvenDelay(float(candidates[-1]), True)


def _aggregate_position_replays(results: tuple[ReplayResult, ...], entry_delay_ms: int, exit_delay_ms: int) -> ReplayResult:
    """Aggregate complete source Positions, never the FIFO legs inside them.

    A partial close can create several ``ExecutedTrade`` values for one source
    Position.  Those legs are useful for price reconstruction, but treating
    them as independent observations would inflate PF, win rate and trade
    count.  This boundary therefore aggregates one replay result per
    PositionLifecycle before calculating return-quality metrics.
    """
    if not results:
        return _invalid_result(("empty_portfolio",), entry_delay_ms, exit_delay_ms)
    invalid_reasons = tuple(reason for result in results for reason in result.invalid_reasons)
    if invalid_reasons:
        return _invalid_result(invalid_reasons, entry_delay_ms, exit_delay_ms)
    position_net = [result.net_profit for result in results]
    gross_profit = sum(value for value in position_net if value > 0)
    gross_loss = -sum(value for value in position_net if value < 0)
    entry_signals = sum(result.entry_signals for result in results)
    exit_signals = sum(result.exit_signals for result in results)
    completed_source_events = sum(result.completed_source_events for result in results)
    executed_source_events = sum(result.executed_source_events for result in results)
    entry_executed = sum(result.entry_executable_ratio * result.entry_signals for result in results)
    exit_executed = sum(result.exit_executable_ratio * result.exit_signals for result in results)
    copy_cost_total = sum(result.copy_cost_per_trade * result.executed_trades for result in results)
    executed_positions = sum(
        1
        for result in results
        if result.completed_source_events > 0 and result.executed_source_events == result.completed_source_events
    )
    return ReplayResult(
        valid=True,
        invalid_reasons=(),
        entry_delay_ms=entry_delay_ms,
        exit_delay_ms=exit_delay_ms,
        net_profit=sum(position_net),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=None if gross_loss == 0 else gross_profit / gross_loss,
        win_rate=sum(value > 0 for value in position_net) / len(position_net),
        entry_executable_ratio=entry_executed / entry_signals if entry_signals else 0.0,
        exit_executable_ratio=exit_executed / exit_signals if exit_signals else 0.0,
        combined_executable_ratio=executed_source_events / completed_source_events if completed_source_events else 0.0,
        average_net_profit=sum(position_net) / len(position_net),
        copy_cost_per_trade=copy_cost_total / len(position_net),
        completed_trades=len(position_net),
        executed_trades=executed_positions,
        entry_signals=entry_signals,
        exit_signals=exit_signals,
        completed_source_events=completed_source_events,
        executed_source_events=executed_source_events,
        trades=tuple(trade for result in results for trade in result.trades),
    )


def _portfolio_reconciliation(
    lifecycles: tuple[PositionLifecycle, ...],
    absolute_tolerance: float,
    relative_tolerance: float,
) -> SourceReconciliation:
    reconciliations = tuple(
        reconcile_source_lifecycle(lifecycle, absolute_tolerance=absolute_tolerance, relative_tolerance=relative_tolerance)
        for lifecycle in lifecycles
    )
    expected = sum(item.expected_net_usd for item in reconciliations)
    reconstructed = sum(item.reconstructed_net_usd for item in reconciliations)
    error = reconstructed - expected
    tolerance = absolute_tolerance + relative_tolerance * max(1.0, abs(expected), abs(reconstructed))
    failed = next((item for item in reconciliations if not item.reconciled), None)
    return SourceReconciliation(
        reconciled=failed is None and abs(error) <= tolerance,
        error_usd=error,
        expected_net_usd=expected,
        reconstructed_net_usd=reconstructed,
        reason=None if failed is None and abs(error) <= tolerance else (failed.reason if failed else "portfolio_source_profit_reconciliation_mismatch"),
    )


def _portfolio_replay(
    lifecycles: tuple[PositionLifecycle, ...],
    quotes: Iterable[QuoteTick] | PreparedQuotes,
    entry_delay_ms: int,
    exit_delay_ms: int,
    max_quote_wait_ms: int,
    slippage_price: float,
) -> ReplayResult:
    return _aggregate_position_replays(
        tuple(
            replay_lifecycle(lifecycle, quotes, entry_delay_ms, exit_delay_ms, max_quote_wait_ms, slippage_price)
            for lifecycle in lifecycles
        ),
        entry_delay_ms,
        exit_delay_ms,
    )


def _portfolio_break_even(
    lifecycles: tuple[PositionLifecycle, ...],
    quotes: Iterable[QuoteTick] | PreparedQuotes,
    delays_ms: tuple[int, ...],
    hold_p25_ms: int,
    mode: str,
    max_quote_wait_ms: int,
    slippage_price: float,
) -> BreakEvenDelay:
    baseline = _portfolio_replay(lifecycles, quotes, 0, 0, max_quote_wait_ms, slippage_price)
    if not baseline.valid or baseline.net_profit <= 0:
        return BreakEvenDelay(0.0, False)
    limit = min(30_000, max(0, hold_p25_ms // 3))
    candidates = sorted({0, *(delay for delay in delays_ms if delay <= limit)})
    probe = candidates[-1] + 500
    while probe <= limit:
        candidates.append(probe)
        probe += 500
    previous_delay = 0
    previous_net = baseline.net_profit
    for delay in candidates[1:]:
        entry_delay = delay if mode in ("entry", "combined") else 0
        exit_delay = delay if mode in ("exit", "combined") else 0
        current = _portfolio_replay(lifecycles, quotes, entry_delay, exit_delay, max_quote_wait_ms, slippage_price).net_profit
        if current <= 0:
            denominator = previous_net - current
            crossing = float(delay) if denominator <= 0 else previous_delay + (delay - previous_delay) * previous_net / denominator
            return BreakEvenDelay(float(crossing), False)
        previous_delay, previous_net = delay, current
    return BreakEvenDelay(float(candidates[-1]), True)


def _delay_hard_gate_reasons(
    reconciliation: SourceReconciliation,
    baseline: ReplayResult,
    actual_entry: ReplayResult,
    actual_exit: ReplayResult,
    actual_combined: ReplayResult,
    retained: float,
    conservative_break_even: BreakEvenDelay,
    actual_entry_p95_ms: int,
    actual_exit_p95_ms: int,
    expected_copy_cost: float,
) -> tuple[str, ...]:
    """Apply the P95 delay gates separately for open, close and combined fills."""
    reasons: list[str] = []
    if not reconciliation.reconciled:
        reasons.append(reconciliation.reason or "source_reconciliation_failed")
    if not baseline.valid or not actual_entry.valid or not actual_exit.valid or not actual_combined.valid:
        reasons.append("invalid_lifecycle")
    for label, result, executable_ratio in (
        ("entry", actual_entry, actual_entry.entry_executable_ratio),
        ("exit", actual_exit, actual_exit.exit_executable_ratio),
        ("combined", actual_combined, actual_combined.combined_executable_ratio),
    ):
        if result.net_profit <= 0:
            reasons.append(f"{label}_delay_net_not_positive")
        if result.profit_factor is not None and result.profit_factor < 1.05:
            reasons.append(f"{label}_delay_pf_below_1_05")
        if executable_ratio < 0.80:
            reasons.append(f"{label}_executable_below_80pct")
    if retained < 0.40:
        reasons.append("profit_retention_below_40pct")
    if conservative_break_even.delay_ms < 2 * max(actual_entry_p95_ms, actual_exit_p95_ms):
        reasons.append("break_even_below_two_p95")
    if actual_combined.average_net_profit < 2 * expected_copy_cost:
        reasons.append("average_net_below_copy_cost")
    return tuple(dict.fromkeys(reasons))


def evaluate_delay_scenarios(
    lifecycle: PositionLifecycle,
    quotes: Iterable[QuoteTick] | PreparedQuotes,
    delays_ms: Iterable[int],
    actual_p95_delay_ms: int | None = None,
    hold_p25_ms: int = 0,
    *,
    actual_entry_p95_ms: int | None = None,
    actual_exit_p95_ms: int | None = None,
    max_quote_wait_ms: int = 2_000,
    slippage_price: float = 0.0,
    expected_copy_cost: float = 0.0,
    reconciliation_absolute_tolerance: float = 0.01,
    reconciliation_relative_tolerance: float = 1e-6,
) -> DelayEvaluation:
    """Evaluate grid scenarios; legacy actual_p95_delay_ms applies only when both new P95s are omitted."""
    if actual_entry_p95_ms is None and actual_exit_p95_ms is None:
        if actual_p95_delay_ms is None:
            raise ValueError("actual_entry_p95_ms and actual_exit_p95_ms are required")
        actual_entry_p95_ms = actual_p95_delay_ms
        actual_exit_p95_ms = actual_p95_delay_ms
    elif actual_entry_p95_ms is None or actual_exit_p95_ms is None:
        raise ValueError("actual_entry_p95_ms and actual_exit_p95_ms must be supplied together")
    assert actual_entry_p95_ms is not None and actual_exit_p95_ms is not None
    if min(actual_entry_p95_ms, actual_exit_p95_ms, hold_p25_ms) < 0:
        raise ValueError("P95 delays and hold P25 must be non-negative")
    quote_tuple = _valid_quotes(quotes)
    delays = tuple(sorted({int(delay) for delay in delays_ms if int(delay) >= 0}))
    if not delays:
        raise ValueError("At least one non-negative delay is required")
    rebuilt = reconstruct_lifecycle(lifecycle)
    reconciliation = reconcile_source_lifecycle(lifecycle, rebuilt, reconciliation_absolute_tolerance, reconciliation_relative_tolerance)
    baseline = replay_lifecycle(lifecycle, quote_tuple, 0, 0, max_quote_wait_ms, slippage_price)
    scenarios: list[DelayScenario] = []
    for delay in delays:
        entry = replay_lifecycle(lifecycle, quote_tuple, delay, 0, max_quote_wait_ms, slippage_price)
        exit = replay_lifecycle(lifecycle, quote_tuple, 0, delay, max_quote_wait_ms, slippage_price)
        combined = replay_lifecycle(lifecycle, quote_tuple, delay, delay, max_quote_wait_ms, slippage_price)
        scenarios.append(DelayScenario(delay, entry, exit, combined, _retention(combined, baseline), _pf_retention(combined, baseline)))
    actual_entry = replay_lifecycle(lifecycle, quote_tuple, actual_entry_p95_ms, 0, max_quote_wait_ms, slippage_price)
    actual_exit = replay_lifecycle(lifecycle, quote_tuple, 0, actual_exit_p95_ms, max_quote_wait_ms, slippage_price)
    actual_combined = replay_lifecycle(lifecycle, quote_tuple, actual_entry_p95_ms, actual_exit_p95_ms, max_quote_wait_ms, slippage_price)
    retained = _retention(actual_combined, baseline)
    pf_retained = _pf_retention(actual_combined, baseline)
    score = 0.50 * retained + 0.30 * pf_retained + 0.20 * _clamp(actual_combined.combined_executable_ratio)
    entry_be = _break_even(lifecycle, quote_tuple, delays, hold_p25_ms, "entry", max_quote_wait_ms, slippage_price)
    exit_be = _break_even(lifecycle, quote_tuple, delays, hold_p25_ms, "exit", max_quote_wait_ms, slippage_price)
    combined_be = _break_even(lifecycle, quote_tuple, delays, hold_p25_ms, "combined", max_quote_wait_ms, slippage_price)
    conservative = min(entry_be, exit_be, combined_be, key=lambda item: item.delay_ms)
    reasons = _delay_hard_gate_reasons(
        reconciliation,
        baseline,
        actual_entry,
        actual_exit,
        actual_combined,
        retained,
        conservative,
        actual_entry_p95_ms,
        actual_exit_p95_ms,
        expected_copy_cost,
    )
    return DelayEvaluation(baseline, tuple(scenarios), actual_entry_p95_ms, actual_exit_p95_ms, actual_entry, actual_exit, actual_combined, entry_be, exit_be, combined_be, conservative, score, reconciliation.reconciled, reconciliation.error_usd, reconciliation.reason, not reasons, reasons)


def evaluate_delay_portfolio(
    lifecycles: Iterable[PositionLifecycle],
    quotes: Iterable[QuoteTick] | PreparedQuotes,
    delays_ms: Iterable[int],
    actual_p95_delay_ms: int | None = None,
    hold_p25_ms: int = 0,
    *,
    actual_entry_p95_ms: int | None = None,
    actual_exit_p95_ms: int | None = None,
    max_quote_wait_ms: int = 2_000,
    slippage_price: float = 0.0,
    expected_copy_cost: float = 0.0,
    reconciliation_absolute_tolerance: float = 0.01,
    reconciliation_relative_tolerance: float = 1e-6,
) -> DelayEvaluation:
    """Score every completed Position for one customer-product sleeve as one sample.

    The caller must supply the full (unfiltered) position history for exactly
    one ``account_key`` and product.  Loss-making positions remain in the
    return and PF denominators; selection belongs outside this domain.
    """
    lifecycle_tuple = tuple(lifecycles)
    if not lifecycle_tuple:
        raise ValueError("At least one PositionLifecycle is required")
    sleeve_keys = {(item.account_key, item.product) for item in lifecycle_tuple}
    if len(sleeve_keys) != 1:
        raise ValueError("Delay portfolio must contain one account_key and product")
    if actual_entry_p95_ms is None and actual_exit_p95_ms is None:
        if actual_p95_delay_ms is None:
            raise ValueError("actual_entry_p95_ms and actual_exit_p95_ms are required")
        actual_entry_p95_ms = actual_p95_delay_ms
        actual_exit_p95_ms = actual_p95_delay_ms
    elif actual_entry_p95_ms is None or actual_exit_p95_ms is None:
        raise ValueError("actual_entry_p95_ms and actual_exit_p95_ms must be supplied together")
    assert actual_entry_p95_ms is not None and actual_exit_p95_ms is not None
    if min(actual_entry_p95_ms, actual_exit_p95_ms, hold_p25_ms) < 0:
        raise ValueError("P95 delays and hold P25 must be non-negative")
    quote_tuple = _valid_quotes(quotes)
    delays = tuple(sorted({int(delay) for delay in delays_ms if int(delay) >= 0}))
    if not delays:
        raise ValueError("At least one non-negative delay is required")
    reconciliation = _portfolio_reconciliation(
        lifecycle_tuple,
        reconciliation_absolute_tolerance,
        reconciliation_relative_tolerance,
    )
    baseline = _portfolio_replay(lifecycle_tuple, quote_tuple, 0, 0, max_quote_wait_ms, slippage_price)
    scenarios: list[DelayScenario] = []
    for delay in delays:
        entry = _portfolio_replay(lifecycle_tuple, quote_tuple, delay, 0, max_quote_wait_ms, slippage_price)
        exit = _portfolio_replay(lifecycle_tuple, quote_tuple, 0, delay, max_quote_wait_ms, slippage_price)
        combined = _portfolio_replay(lifecycle_tuple, quote_tuple, delay, delay, max_quote_wait_ms, slippage_price)
        scenarios.append(DelayScenario(delay, entry, exit, combined, _retention(combined, baseline), _pf_retention(combined, baseline)))
    actual_entry = _portfolio_replay(lifecycle_tuple, quote_tuple, actual_entry_p95_ms, 0, max_quote_wait_ms, slippage_price)
    actual_exit = _portfolio_replay(lifecycle_tuple, quote_tuple, 0, actual_exit_p95_ms, max_quote_wait_ms, slippage_price)
    actual_combined = _portfolio_replay(lifecycle_tuple, quote_tuple, actual_entry_p95_ms, actual_exit_p95_ms, max_quote_wait_ms, slippage_price)
    retained = _retention(actual_combined, baseline)
    pf_retained = _pf_retention(actual_combined, baseline)
    score = 0.50 * retained + 0.30 * pf_retained + 0.20 * _clamp(actual_combined.combined_executable_ratio)
    entry_be = _portfolio_break_even(lifecycle_tuple, quote_tuple, delays, hold_p25_ms, "entry", max_quote_wait_ms, slippage_price)
    exit_be = _portfolio_break_even(lifecycle_tuple, quote_tuple, delays, hold_p25_ms, "exit", max_quote_wait_ms, slippage_price)
    combined_be = _portfolio_break_even(lifecycle_tuple, quote_tuple, delays, hold_p25_ms, "combined", max_quote_wait_ms, slippage_price)
    conservative = min(entry_be, exit_be, combined_be, key=lambda item: item.delay_ms)
    reasons = _delay_hard_gate_reasons(
        reconciliation,
        baseline,
        actual_entry,
        actual_exit,
        actual_combined,
        retained,
        conservative,
        actual_entry_p95_ms,
        actual_exit_p95_ms,
        expected_copy_cost,
    )
    return DelayEvaluation(
        baseline,
        tuple(scenarios),
        actual_entry_p95_ms,
        actual_exit_p95_ms,
        actual_entry,
        actual_exit,
        actual_combined,
        entry_be,
        exit_be,
        combined_be,
        conservative,
        score,
        reconciliation.reconciled,
        reconciliation.error_usd,
        reconciliation.reason,
        not reasons,
        reasons,
    )
