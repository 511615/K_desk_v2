from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from math import isfinite
from typing import Iterable


SECONDS_PER_HOUR = 60 * 60
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR


@dataclass(frozen=True)
class AdjustedEquityPoint:
    timestamp: datetime
    equity_usd: float
    external_cashflow_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("AdjustedEquityPoint timestamp must be UTC-aware.")


@dataclass(frozen=True)
class DrawdownMetrics:
    mdd_20d: float
    mdd_60d: float
    current_drawdown: float
    max_daily_loss: float
    max_consecutive_loss_usd: float
    max_consecutive_losses: int
    max_recovery_seconds: float
    coverage_20d: bool
    coverage_60d: bool
    daily_coverage_complete: bool
    gate_reasons: tuple[str, ...]


@dataclass(frozen=True)
class TradeHoldingObservation:
    opened_at: datetime
    closed_at: datetime
    swap_usd: float
    gross_profit_usd: float
    long_loss_seconds: float = 0.0
    additions_while_loss: bool = False

    def __post_init__(self) -> None:
        if self.opened_at.tzinfo is None or self.opened_at.utcoffset() is None:
            raise ValueError("TradeHoldingObservation opened_at must be UTC-aware.")
        if self.closed_at.tzinfo is None or self.closed_at.utcoffset() is None:
            raise ValueError("TradeHoldingObservation closed_at must be UTC-aware.")
        if self.closed_at < self.opened_at:
            raise ValueError("TradeHoldingObservation closed_at must not precede opened_at.")
        hold_seconds = (self.closed_at - self.opened_at).total_seconds()
        if not isfinite(self.long_loss_seconds) or not 0.0 <= self.long_loss_seconds <= hold_seconds:
            raise ValueError("TradeHoldingObservation long_loss_seconds must be within holding duration.")


@dataclass(frozen=True)
class HoldingQualityMetrics:
    observation_count: int
    overnight_ratio: float
    natural_day_ratio: float
    weekend_count: int
    weekend_ratio: float
    swap_drag: float
    long_loss_ratio: float
    loss_addition_ratio: float
    hold_p90_seconds: float
    overnight_multiplier: float
    hold_p90_multiplier: float
    weekend_multiplier: float
    swap_multiplier: float
    long_loss_multiplier: float
    loss_addition_multiplier: float
    quality_multiplier: float
    hard_failed: bool
    gate_reasons: tuple[str, ...]


@dataclass(frozen=True)
class CarryRiskMetrics:
    max_floating_loss_ratio_30d: float
    max_underwater_seconds_30d: float
    max_losing_positions_30d: int
    risk_score: float
    quality_score: float
    hard_failed: bool
    gate_reasons: tuple[str, ...]


@dataclass(frozen=True)
class FactorInputs:
    risk_adjusted_return_5d: float
    risk_adjusted_return_20d: float
    spread_stress_return: float
    pf_quality: float
    delay_score: float
    return_to_drawdown: float
    holding_quality: float
    mdd_20d: float
    mdd_60d: float
    current_drawdown: float
    max_daily_loss: float
    delay_gates_passed: bool
    delay_factor_enabled: bool = False
    negative_equity: bool = False
    cashflow_adjusted_capital_exhaustion: bool = False
    nonpositive_balance_baseline: bool = False
    stop_out_compensation: bool = False
    holding_hard_failed: bool = False
    coverage_20d: bool = True
    coverage_60d: bool = True
    daily_drawdown_coverage: bool = True
    extra_gate_reasons: tuple[str, ...] = ()
    # V1 primary model inputs. None keeps backwards-compatible legacy scoring
    # for isolated callers and older fixtures; production pool evaluation sets
    # all three explicitly.
    cost_profit_score: float | None = None
    recent_strength_score: float | None = None
    cost_coverage_score: float | None = None
    carry_quality_score: float | None = None
    carry_hard_failed: bool = False


@dataclass(frozen=True)
class FactorResult:
    eligible: bool
    base_score: float
    factor_scores: dict[str, float]
    gate_reasons: tuple[str, ...]


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be UTC-aware.")
    return value.astimezone(timezone.utc)


def _clamp_unit(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _window_mdd(values: list[tuple[datetime, float]]) -> float:
    if any(equity <= 0 for _timestamp, equity in values):
        return 1.0
    peak: float | None = None
    maximum = 0.0
    for _timestamp, equity in values:
        if equity <= 0:
            continue
        if peak is None or equity > peak:
            peak = equity
        if peak is not None:
            maximum = max(maximum, (peak - equity) / peak)
    return maximum


def _as_tzinfo(value: tzinfo | timedelta | float | int) -> tzinfo:
    if isinstance(value, tzinfo):
        return value
    if isinstance(value, timedelta):
        return timezone(value)
    return timezone(timedelta(hours=float(value)))


def _window_with_boundary(
    adjusted: list[tuple[datetime, float]], cutoff: datetime
) -> list[tuple[datetime, float]]:
    prior = [item for item in adjusted if item[0] < cutoff]
    inside = [item for item in adjusted if item[0] >= cutoff]
    return ([prior[-1]] if prior else []) + inside


def _coverage(
    adjusted: list[tuple[datetime, float]],
    as_of: datetime,
    window_days: int,
    max_staleness: timedelta,
) -> tuple[bool, tuple[str, ...]]:
    cutoff = as_of - timedelta(days=window_days)
    reasons: list[str] = []
    if adjusted[0][0] > cutoff:
        reasons.append(f"insufficient_equity_coverage_{window_days}d")
    if as_of - adjusted[-1][0] > max_staleness:
        reasons.append(f"stale_equity_coverage_{window_days}d")
    if len(_window_with_boundary(adjusted, cutoff)) < 2:
        reasons.append(f"insufficient_equity_points_{window_days}d")
    return not reasons, tuple(reasons)


def _trading_day(value: datetime, rollover: time) -> date:
    local_date = value.date()
    return local_date - timedelta(days=1) if value.timetz().replace(tzinfo=None) < rollover else local_date


def _trading_day_start(value: date, rollover: time, tz: tzinfo) -> datetime:
    return datetime.combine(value, rollover, tzinfo=tz)


def calculate_adjusted_equity_metrics(
    points: Iterable[AdjustedEquityPoint],
    as_of: datetime,
    day_timezone: tzinfo = timezone.utc,
    rollover_time: time = time(0, 0),
    max_staleness: timedelta = timedelta(hours=24),
) -> DrawdownMetrics:
    """Calculate cashflow-adjusted drawdown metrics from an ordered equity evidence set."""
    as_of_utc = _require_aware(as_of, "as_of")
    if max_staleness < timedelta(0):
        raise ValueError("max_staleness must be non-negative.")
    ordered = sorted(
        (point for point in points if point.timestamp.astimezone(timezone.utc) <= as_of_utc),
        key=lambda point: point.timestamp.astimezone(timezone.utc),
    )
    if not ordered:
        return DrawdownMetrics(
            0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, False, False, False,
            ("missing_equity_history",),
        )

    raw_negative_equity = any(float(point.equity_usd) < 0.0 for point in ordered)
    funded_index = next(
        (index for index, point in enumerate(ordered) if float(point.equity_usd) > 0.0),
        None,
    )
    if funded_index is None:
        reasons = ["missing_funded_equity_baseline"]
        if raw_negative_equity:
            reasons.append("negative_equity")
        return DrawdownMetrics(
            1.0, 1.0, 1.0, 1.0, 0.0, 0, 0.0, False, False, False,
            tuple(reasons),
        )

    # A zero/negative pre-funding row is not an equity loss. The first funded
    # observation establishes the capital baseline, so its own deposit is not
    # subtracted from itself. Later external cashflows are removed normally.
    funded = ordered[funded_index:]
    cumulative_cashflow = 0.0
    adjusted: list[tuple[datetime, float]] = []
    for index, point in enumerate(funded):
        if index:
            cumulative_cashflow += float(point.external_cashflow_usd)
        adjusted.append((point.timestamp.astimezone(timezone.utc), float(point.equity_usd) - cumulative_cashflow))

    reasons: list[str] = []
    coverage_20d, coverage_20_reasons = _coverage(adjusted, as_of_utc, 20, max_staleness)
    coverage_60d, coverage_60_reasons = _coverage(adjusted, as_of_utc, 60, max_staleness)
    reasons.extend(coverage_20_reasons)
    reasons.extend(coverage_60_reasons)
    if raw_negative_equity:
        reasons.append("negative_equity")
    if any(value <= 0 for _timestamp, value in adjusted):
        reasons.append("cashflow_adjusted_capital_exhaustion")

    values_20d = _window_with_boundary(adjusted, as_of_utc - timedelta(days=20))
    values_60d = _window_with_boundary(adjusted, as_of_utc - timedelta(days=60))
    mdd_20d = _window_mdd(values_20d)
    mdd_60d = _window_mdd(values_60d)
    peak = adjusted[0][1]
    peak_timestamp = adjusted[0][0]
    current_drawdown = 0.0
    recovery_started_at: datetime | None = None
    max_recovery_seconds = 0.0
    for timestamp, value in adjusted:
        if peak > 0:
            current_drawdown = max(0.0, (peak - value) / peak)
        if value < peak and recovery_started_at is None:
            recovery_started_at = peak_timestamp
        if value >= peak:
            if recovery_started_at is not None:
                max_recovery_seconds = max(
                    max_recovery_seconds, (timestamp - recovery_started_at).total_seconds()
                )
                recovery_started_at = None
            if value > peak:
                peak = value
                peak_timestamp = timestamp
                current_drawdown = 0.0

    if recovery_started_at is not None:
        max_recovery_seconds = max(
            max_recovery_seconds, (as_of_utc - recovery_started_at).total_seconds()
        )

    daily_rows: dict[date, list[tuple[datetime, float]]] = {}
    daily_cutoff = as_of_utc - timedelta(days=60)
    for timestamp, value in adjusted:
        local = timestamp.astimezone(day_timezone)
        if timestamp >= daily_cutoff:
            daily_rows.setdefault(_trading_day(local, rollover_time), []).append((timestamp, value))
    max_daily_loss = 0.0
    daily_coverage_complete = True
    first_funded_day = _trading_day(
        adjusted[0][0].astimezone(day_timezone), rollover_time
    )
    for local_day, rows in daily_rows.items():
        boundary = _trading_day_start(local_day, rollover_time, day_timezone).astimezone(timezone.utc)
        # Do not judge the partial first trading day intersecting the 60-day
        # cutoff. It has no complete start boundary by definition.
        if boundary < daily_cutoff:
            continue
        baselines = [value for timestamp, value in adjusted if timestamp <= boundary]
        if not baselines:
            if local_day != first_funded_day:
                daily_coverage_complete = False
                reasons.append(f"missing_daily_baseline_{local_day.isoformat()}")
                continue
            # Before an account's first funding event no equity state exists.
            # Its first funded observation is the valid start of that day.
            start = rows[0][1]
        else:
            start = baselines[-1]
        if start <= 0:
            reasons.append(f"nonpositive_daily_baseline_{local_day.isoformat()}")
            continue
        max_daily_loss = max(max_daily_loss, (start - min(value for _timestamp, value in rows)) / start)

    consecutive_loss = 0.0
    consecutive_count = 0
    max_consecutive_loss = 0.0
    max_consecutive_count = 0
    for (_before_time, before), (_after_time, after) in zip(adjusted, adjusted[1:]):
        change = after - before
        if change < 0:
            consecutive_loss += -change
            consecutive_count += 1
            max_consecutive_loss = max(max_consecutive_loss, consecutive_loss)
            max_consecutive_count = max(max_consecutive_count, consecutive_count)
        elif change > 0:
            consecutive_loss = 0.0
            consecutive_count = 0

    return DrawdownMetrics(
        mdd_20d=mdd_20d,
        mdd_60d=mdd_60d,
        current_drawdown=current_drawdown,
        max_daily_loss=max_daily_loss,
        max_consecutive_loss_usd=max_consecutive_loss,
        max_consecutive_losses=max_consecutive_count,
        max_recovery_seconds=max_recovery_seconds,
        coverage_20d=coverage_20d,
        coverage_60d=coverage_60d,
        daily_coverage_complete=daily_coverage_complete,
        gate_reasons=tuple(dict.fromkeys(reasons)),
    )


def _crosses_weekend(opened: datetime, closed: datetime) -> bool:
    date = opened.date()
    end = closed.date()
    while date <= end:
        if date.weekday() >= 5:
            return True
        date += timedelta(days=1)
    return False


def _settlement_date(value: datetime, rollover: time) -> datetime.date:
    local_date = value.date()
    return local_date - timedelta(days=1) if value.timetz().replace(tzinfo=None) < rollover else local_date


def _quantile_90(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * 0.90
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def calculate_carry_risk_metrics(
    *,
    max_floating_loss_ratio_30d: float,
    max_underwater_seconds_30d: float,
    max_losing_positions_30d: int,
) -> CarryRiskMetrics:
    """Summarize low-cost adverse-position risk without tick replay.

    Historical equity drawdown and losing-position holding paths are accepted as
    conservative proxies. Runtime snapshots can progressively improve the
    observed maxima without retaining every quote or position snapshot.
    """
    depth = max(0.0, float(max_floating_loss_ratio_30d))
    duration = max(0.0, float(max_underwater_seconds_30d))
    positions = max(0, int(max_losing_positions_30d))
    risk_score = 100.0 * (
        0.55 * min(depth / 0.08, 1.0)
        + 0.30 * min(duration / (24 * SECONDS_PER_HOUR), 1.0)
        + 0.15 * min(positions / 5.0, 1.0)
    )
    hard_reasons: list[str] = []
    if depth >= 0.10:
        hard_reasons.append("max_floating_loss_ratio_30d_at_least_10pct")
    if duration >= 48 * SECONDS_PER_HOUR:
        hard_reasons.append("max_underwater_at_least_48h")
    if positions >= 8:
        hard_reasons.append("max_losing_positions_at_least_8")
    if risk_score >= 70.0:
        hard_reasons.append("carry_risk_score_at_least_70")

    return CarryRiskMetrics(
        max_floating_loss_ratio_30d=depth,
        max_underwater_seconds_30d=duration,
        max_losing_positions_30d=positions,
        risk_score=risk_score,
        quality_score=max(0.0, 1.0 - risk_score / 100.0),
        hard_failed=bool(hard_reasons),
        gate_reasons=tuple(hard_reasons),
    )


def calculate_holding_quality_metrics(
    observations: Iterable[TradeHoldingObservation],
    *,
    server_utc_offset: tzinfo | timedelta | float | int = 0,
    rollover_time: time = time(0, 0),
    as_of: datetime | None = None,
    window_days: int = 60,
) -> HoldingQualityMetrics:
    """Classify holding quality using server-local trading dates and settlement boundaries."""
    server_tz = _as_tzinfo(server_utc_offset)
    if window_days <= 0:
        raise ValueError("window_days must be positive.")
    supplied = list(observations)
    reference = _require_aware(as_of, "as_of") if as_of is not None else (
        max((row.closed_at.astimezone(timezone.utc) for row in supplied), default=None)
    )
    rows = [
        row for row in supplied
        if reference is not None
        and reference - timedelta(days=window_days) <= row.closed_at.astimezone(timezone.utc) <= reference
    ]
    if not rows:
        return HoldingQualityMetrics(
            0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, True, ("missing_holding_history",),
        )

    overnight_count = 0
    natural_day_count = 0
    weekend_count = 0
    long_loss_count = 0
    loss_addition_count = 0
    negative_swap = 0.0
    positive_gross_profit = 0.0
    holds: list[float] = []
    for row in rows:
        opened = row.opened_at.astimezone(server_tz)
        closed = row.closed_at.astimezone(server_tz)
        hold_seconds = max(0.0, (closed - opened).total_seconds())
        holds.append(hold_seconds)
        if _settlement_date(opened, rollover_time) != _settlement_date(closed, rollover_time):
            overnight_count += 1
        if opened.date() != closed.date():
            natural_day_count += 1
        if _crosses_weekend(opened, closed):
            weekend_count += 1
        if row.long_loss_seconds >= SECONDS_PER_HOUR or (
            hold_seconds > 0 and row.long_loss_seconds >= hold_seconds / 2.0
        ):
            long_loss_count += 1
        if row.additions_while_loss:
            loss_addition_count += 1
        negative_swap += max(-float(row.swap_usd), 0.0)
        positive_gross_profit += max(float(row.gross_profit_usd), 0.0)

    count = len(rows)
    overnight_ratio = overnight_count / count
    weekend_ratio = weekend_count / count
    p90 = _quantile_90(holds)
    reasons: list[str] = []
    if p90 > 24 * SECONDS_PER_HOUR:
        reasons.append("hold_p90_over_24h")
    if overnight_ratio > 0.60:
        reasons.append("overnight_ratio_over_60pct")
    if weekend_count >= 2:
        reasons.append("weekend_count_at_least_2")
    if weekend_ratio > 0.03:
        reasons.append("weekend_ratio_over_3pct")

    if overnight_ratio <= 0.10:
        overnight_multiplier = 1.0
    elif overnight_ratio <= 0.30:
        overnight_multiplier = 1.0 - 0.30 * (overnight_ratio - 0.10) / 0.20
    elif overnight_ratio <= 0.60:
        overnight_multiplier = 0.70 - 0.45 * (overnight_ratio - 0.30) / 0.30
    else:
        overnight_multiplier = 0.0

    if p90 <= 8 * SECONDS_PER_HOUR:
        hold_p90_multiplier = 1.0
    elif p90 <= 24 * SECONDS_PER_HOUR:
        hold_p90_multiplier = 1.0 - 0.30 * (p90 - 8 * SECONDS_PER_HOUR) / (16 * SECONDS_PER_HOUR)
    else:
        hold_p90_multiplier = 0.0

    weekend_multiplier = 1.0 - 0.20 * min(weekend_ratio, 0.03) / 0.03

    def multiplier(value: float, first: float, second: float, third: float, middle: float, low: float) -> float:
        if value <= first:
            return 1.0
        if value <= second:
            return 1.0 - (1.0 - middle) * (value - first) / (second - first)
        if value <= third:
            return middle - (middle - low) * (value - second) / (third - second)
        return low

    # Negative swap without any positive gross profit has no meaningful denominator;
    # represent it as the maximum drag instead of silently treating it as neutral.
    swap_drag = (
        negative_swap / positive_gross_profit
        if positive_gross_profit > 0
        else 1.0 if negative_swap > 0 else 0.0
    )
    long_loss_ratio = long_loss_count / count
    loss_addition_ratio = loss_addition_count / count
    swap_multiplier = multiplier(swap_drag, 0.05, 0.20, 0.50, 0.70, 0.20)
    long_loss_multiplier = multiplier(long_loss_ratio, 0.10, 0.30, 0.60, 0.70, 0.30)
    loss_addition_multiplier = multiplier(loss_addition_ratio, 0.05, 0.20, 0.50, 0.70, 0.20)
    quality_multiplier = (
        0.30 * hold_p90_multiplier
        + 0.25 * overnight_multiplier
        + 0.15 * weekend_multiplier
        + 0.10 * swap_multiplier
        + 0.10 * long_loss_multiplier
        + 0.10 * loss_addition_multiplier
    )

    return HoldingQualityMetrics(
        observation_count=count,
        overnight_ratio=overnight_ratio,
        natural_day_ratio=natural_day_count / count,
        weekend_count=weekend_count,
        weekend_ratio=weekend_ratio,
        swap_drag=swap_drag,
        long_loss_ratio=long_loss_ratio,
        loss_addition_ratio=loss_addition_ratio,
        hold_p90_seconds=p90,
        overnight_multiplier=overnight_multiplier,
        hold_p90_multiplier=hold_p90_multiplier,
        weekend_multiplier=weekend_multiplier,
        swap_multiplier=swap_multiplier,
        long_loss_multiplier=long_loss_multiplier,
        loss_addition_multiplier=loss_addition_multiplier,
        quality_multiplier=quality_multiplier,
        hard_failed=bool(reasons),
        gate_reasons=tuple(reasons),
    )


def calculate_factor_result(inputs: FactorInputs) -> FactorResult:
    """Return the versioned base score after non-compensable hard gates."""
    raw_scores = {
        "risk_adjusted_return_5d": inputs.risk_adjusted_return_5d,
        "risk_adjusted_return_20d": inputs.risk_adjusted_return_20d,
        "spread_stress_return": inputs.spread_stress_return,
        "pf_quality": inputs.pf_quality,
        "delay_score": inputs.delay_score,
        "return_to_drawdown": inputs.return_to_drawdown,
        "holding_quality": inputs.holding_quality,
        "carry_quality": (
            inputs.carry_quality_score
            if inputs.carry_quality_score is not None else 0.0
        ),
    }
    factor_scores = {name: _clamp_unit(value) for name, value in raw_scores.items()}
    configured_weights = {
        "risk_adjusted_return_5d": 0.20,
        "risk_adjusted_return_20d": 0.15,
        "spread_stress_return": 0.15,
        "pf_quality": 0.10,
        "delay_score": 0.20,
        "return_to_drawdown": 0.10,
        "holding_quality": 0.10,
    }
    if (
        inputs.cost_profit_score is not None
        and inputs.recent_strength_score is not None
        and inputs.cost_coverage_score is not None
        and inputs.carry_quality_score is not None
    ):
        # Production V2 adds adverse-position quality to the transparent
        # primary ordering signal. Hard failures remain non-compensable.
        base_score = (
            0.45 * _clamp_unit(inputs.cost_profit_score)
            + 0.25 * _clamp_unit(inputs.recent_strength_score)
            + 0.15 * _clamp_unit(inputs.cost_coverage_score)
            + 0.15 * _clamp_unit(inputs.carry_quality_score)
        )
    elif (
        inputs.cost_profit_score is not None
        and inputs.recent_strength_score is not None
        and inputs.cost_coverage_score is not None
    ):
        base_score = (
            0.50 * _clamp_unit(inputs.cost_profit_score)
            + 0.30 * _clamp_unit(inputs.recent_strength_score)
            + 0.20 * _clamp_unit(inputs.cost_coverage_score)
        )
    else:
        weights = dict(configured_weights)
        if not inputs.delay_factor_enabled:
            weights.pop("delay_score")
            retained_total = sum(weights.values())
            weights = {name: value / retained_total for name, value in weights.items()}
        base_score = sum(weights[name] * factor_scores[name] for name in weights)
    reasons = list(inputs.extra_gate_reasons)
    if not inputs.coverage_20d:
        reasons.append("insufficient_equity_coverage_20d")
    if not inputs.coverage_60d:
        reasons.append("insufficient_equity_coverage_60d")
    if not inputs.daily_drawdown_coverage:
        reasons.append("incomplete_daily_drawdown_coverage")
    if inputs.mdd_20d > 0.10:
        reasons.append("mdd_20d_over_10pct")
    if inputs.mdd_60d > 0.20:
        reasons.append("mdd_60d_over_20pct")
    if inputs.current_drawdown > 0.10:
        reasons.append("current_drawdown_over_10pct")
    if inputs.max_daily_loss > 0.08:
        reasons.append("max_daily_loss_over_8pct")
    if inputs.delay_factor_enabled and not inputs.delay_gates_passed:
        reasons.append("delay_hard_gate_failed")
    if inputs.negative_equity:
        reasons.append("negative_equity")
    if inputs.cashflow_adjusted_capital_exhaustion:
        reasons.append("cashflow_adjusted_capital_exhaustion")
    if inputs.nonpositive_balance_baseline:
        reasons.append("nonpositive_balance_baseline")
    if inputs.stop_out_compensation:
        reasons.append("stop_out_compensation")
    if inputs.holding_hard_failed:
        reasons.append("holding_quality_hard_gate_failed")
    if inputs.carry_hard_failed:
        reasons.append("carry_risk_hard_gate_failed")
    return FactorResult(
        eligible=not reasons,
        base_score=base_score,
        factor_scores=factor_scores,
        gate_reasons=tuple(dict.fromkeys(reasons)),
    )
