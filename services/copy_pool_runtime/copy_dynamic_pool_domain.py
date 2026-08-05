"""Pure state and ranking rules for the dynamic copy-pool lifecycle.

This module intentionally has no database, clock, or execution dependency.  The
producer owns persistence and uses these serializable decisions to drive its
500ms event loop and its slower risk/ranking schedules.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from math import floor, isfinite
from typing import Callable, Iterable
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")
MONITOR_LIMIT = 30
RESERVE_LIMIT = 70


class PoolTier(str, Enum):
    RESERVE = "reserve"
    MONITOR = "monitor"
    ENTRY_SHADOW = "entry_shadow"
    ACTIVE = "active"
    RECOVERY_SHADOW = "recovery_shadow"
    EXECUTION_SUSPENDED = "execution_suspended"
    HARD_REJECTED = "hard_rejected"


@dataclass(frozen=True)
class RankingCandidate:
    sleeve_key: str
    account_key: str
    product: str
    score: float
    hard_eligible: bool
    activity_eligible: bool
    min_lot_feasible: bool

    def __post_init__(self) -> None:
        if not self.sleeve_key or not self.account_key or not self.product:
            raise ValueError("sleeve_key, account_key and product must be non-empty")
        if not isfinite(float(self.score)):
            raise ValueError("score must be finite")

    @property
    def executable(self) -> bool:
        return self.hard_eligible and self.activity_eligible and self.min_lot_feasible


@dataclass(frozen=True)
class RankUniverse:
    """Unique-account monitor/reserve selection with all selected sleeves retained."""

    monitor_accounts: tuple[str, ...]
    reserve_accounts: tuple[str, ...]
    monitor_sleeves: tuple[RankingCandidate, ...]
    reserve_sleeves: tuple[RankingCandidate, ...]
    primary_sleeves: tuple[RankingCandidate, ...]
    coverage_products: tuple[str, ...]
    cap_fallback_accounts: tuple[str, ...]


def _candidate_order(candidate: RankingCandidate) -> tuple[float, str, str, str]:
    return (-float(candidate.score), candidate.account_key, candidate.product, candidate.sleeve_key)


def build_rank_universe(candidates: Iterable[RankingCandidate]) -> RankUniverse:
    """Build 30 monitor plus 70 reserve slots without duplicate account occupancy.

    An account's strongest hard-qualified sleeve decides its account rank.  Once
    selected, all of that account's hard-qualified sleeves are retained so the
    execution/risk layers can still reason at account-product granularity.
    """
    eligible = sorted((item for item in candidates if item.hard_eligible), key=_candidate_order)
    by_account: dict[str, list[RankingCandidate]] = {}
    product_accounts: dict[str, set[str]] = {}
    for item in eligible:
        by_account.setdefault(item.account_key, []).append(item)
        product_accounts.setdefault(item.product, set()).add(item.account_key)

    primary = sorted((items[0] for items in by_account.values()), key=_candidate_order)
    coverage_products = tuple(sorted(product for product, accounts in product_accounts.items() if len(accounts) >= 3))
    total_target = min(MONITOR_LIMIT, len(primary))
    product_cap = max(1, floor(total_target * 0.40)) if total_target else 0
    selected: list[RankingCandidate] = []
    selected_accounts: set[str] = set()
    product_count: dict[str, int] = {}
    deferred: list[RankingCandidate] = []

    def add(candidate: RankingCandidate) -> None:
        selected.append(candidate)
        selected_accounts.add(candidate.account_key)
        product_count[candidate.product] = product_count.get(candidate.product, 0) + 1

    # Coverage works from product sleeves rather than the account primary
    # sleeve. A strong XAUUSD account can still provide NAS100 coverage.
    for product in coverage_products:
        kept = 0
        for candidate in eligible:
            if candidate.product != product or candidate.account_key in selected_accounts:
                continue
            if product_count.get(product, 0) >= product_cap:
                deferred.append(candidate)
                continue
            add(candidate)
            kept += 1
            if kept == 3 or len(selected) == MONITOR_LIMIT:
                break

    for candidate in primary:
        if len(selected) == MONITOR_LIMIT:
            break
        if candidate.account_key in selected_accounts:
            continue
        if product_count.get(candidate.product, 0) >= product_cap:
            deferred.append(candidate)
            continue
        add(candidate)

    # A cap must not make the monitor smaller when other products cannot fill it.
    fallback_accounts: list[str] = []
    if len(selected) < total_target:
        for candidate in sorted(deferred, key=_candidate_order):
            if len(selected) == total_target:
                break
            if candidate.account_key in selected_accounts:
                continue
            add(candidate)
            fallback_accounts.append(candidate.account_key)

    remaining = [item for item in primary if item.account_key not in selected_accounts]
    reserve_primary = remaining[:RESERVE_LIMIT]
    monitor_accounts = tuple(item.account_key for item in selected)
    reserve_accounts = tuple(item.account_key for item in reserve_primary)

    def retained(accounts: set[str]) -> tuple[RankingCandidate, ...]:
        return tuple(item for item in eligible if item.account_key in accounts)

    return RankUniverse(
        monitor_accounts=monitor_accounts,
        reserve_accounts=reserve_accounts,
        monitor_sleeves=retained(set(monitor_accounts)),
        reserve_sleeves=retained(set(reserve_accounts)),
        primary_sleeves=tuple(primary),
        coverage_products=coverage_products,
        cap_fallback_accounts=tuple(fallback_accounts),
    )


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _ensure_aware(datetime.fromisoformat(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid or naive persisted datetime") from exc


def _finite_nonnegative(value: float, name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return numeric


@dataclass(frozen=True)
class SleeveDynamicState:
    day_start_base_weight: float
    effective_weight: float = 0.0
    tier: PoolTier = PoolTier.MONITOR
    consecutive_active_qualifications: int = 0
    consecutive_qualified_falls: int = 0
    shadow_started_at: datetime | None = None
    shadow_ends_at: datetime | None = None
    last_ranked_at: datetime | None = None
    # Read-only daily client-budget allocation; it must never be summed across sleeves.
    frozen_daily_loss_budget: float = 0.0
    released_weight: float = 0.0
    redistribution_eligible_at: datetime | None = None
    entry_expired_at: tuple[datetime, ...] = field(default_factory=tuple)
    exit_expired_at: tuple[datetime, ...] = field(default_factory=tuple)
    suspended_at: datetime | None = None
    recovery_shadow_started_at: datetime | None = None
    weight_increase_events: tuple[tuple[datetime, float], ...] = field(default_factory=tuple)
    released_weight_events: tuple[tuple[datetime, float], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("day_start_base_weight", "effective_weight", "frozen_daily_loss_budget", "released_weight"):
            _finite_nonnegative(getattr(self, name), name)
        for stamp in (self.shadow_started_at, self.shadow_ends_at, self.last_ranked_at,
                      self.redistribution_eligible_at, self.suspended_at, self.recovery_shadow_started_at):
            if stamp is not None:
                _ensure_aware(stamp)
        for stamp in self.entry_expired_at + self.exit_expired_at:
            _ensure_aware(stamp)
        for stamp, amount in self.weight_increase_events + self.released_weight_events:
            _ensure_aware(stamp)
            _finite_nonnegative(amount, "weight event amount")

    def to_dict(self) -> dict[str, object]:
        return {
            "day_start_base_weight": self.day_start_base_weight,
            "effective_weight": self.effective_weight,
            "tier": self.tier.value,
            "consecutive_active_qualifications": self.consecutive_active_qualifications,
            "consecutive_qualified_falls": self.consecutive_qualified_falls,
            "shadow_started_at": _iso(self.shadow_started_at),
            "shadow_ends_at": _iso(self.shadow_ends_at),
            "last_ranked_at": _iso(self.last_ranked_at),
            "frozen_daily_loss_budget": self.frozen_daily_loss_budget,
            "released_weight": self.released_weight,
            "redistribution_eligible_at": _iso(self.redistribution_eligible_at),
            "entry_expired_at": [_iso(item) for item in self.entry_expired_at],
            "exit_expired_at": [_iso(item) for item in self.exit_expired_at],
            "suspended_at": _iso(self.suspended_at),
            "recovery_shadow_started_at": _iso(self.recovery_shadow_started_at),
            "weight_increase_events": [[_iso(at), amount] for at, amount in self.weight_increase_events],
            "released_weight_events": [[_iso(at), amount] for at, amount in self.released_weight_events],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SleeveDynamicState":
        return cls(
            day_start_base_weight=float(payload["day_start_base_weight"]),
            effective_weight=float(payload.get("effective_weight", 0.0)),
            tier=PoolTier(str(payload.get("tier", PoolTier.MONITOR.value))),
            consecutive_active_qualifications=int(payload.get("consecutive_active_qualifications", 0)),
            consecutive_qualified_falls=int(payload.get("consecutive_qualified_falls", 0)),
            shadow_started_at=_parse_iso(payload.get("shadow_started_at")),  # type: ignore[arg-type]
            shadow_ends_at=_parse_iso(payload.get("shadow_ends_at")),  # type: ignore[arg-type]
            last_ranked_at=_parse_iso(payload.get("last_ranked_at")),  # type: ignore[arg-type]
            frozen_daily_loss_budget=float(payload.get("frozen_daily_loss_budget", 0.0)),
            released_weight=float(payload.get("released_weight", 0.0)),
            redistribution_eligible_at=_parse_iso(payload.get("redistribution_eligible_at")),  # type: ignore[arg-type]
            entry_expired_at=tuple(_parse_iso(item) for item in payload.get("entry_expired_at", []) if item),  # type: ignore[arg-type]
            exit_expired_at=tuple(_parse_iso(item) for item in payload.get("exit_expired_at", []) if item),  # type: ignore[arg-type]
            suspended_at=_parse_iso(payload.get("suspended_at")),  # type: ignore[arg-type]
            recovery_shadow_started_at=_parse_iso(payload.get("recovery_shadow_started_at")),  # type: ignore[arg-type]
            weight_increase_events=tuple((_parse_iso(item[0]), float(item[1])) for item in payload.get("weight_increase_events", []) if item[0]),  # type: ignore[index,arg-type]
            released_weight_events=tuple((_parse_iso(item[0]), float(item[1])) for item in payload.get("released_weight_events", []) if item[0]),  # type: ignore[index,arg-type]
        )


def _reduce_weight(state: SleeveDynamicState, target: float, now: datetime) -> SleeveDynamicState:
    target = max(0.0, target)
    if target >= state.effective_weight:
        return state
    released = state.effective_weight - target
    events = state.released_weight_events + ((now, released),)
    earliest = min(at for at, _amount in events) + timedelta(minutes=30)
    return replace(
        state,
        effective_weight=target,
        released_weight=state.released_weight + released,
        redistribution_eligible_at=earliest,
        released_weight_events=events,
    )


def reduce_effective_weight(
    state: SleeveDynamicState, target: float, now: datetime
) -> SleeveDynamicState:
    """Public, auditable weight reduction used by portfolio-level caps."""
    return _reduce_weight(state, target, _ensure_aware(now))


def _increase_weight(state: SleeveDynamicState, target: float, now: datetime) -> SleeveDynamicState:
    target = min(max(0.0, target), state.day_start_base_weight * 1.2)
    if target <= state.effective_weight:
        return _reduce_weight(state, target, now)
    one_hour_ago = now - timedelta(hours=1)
    history = tuple((at, amount) for at, amount in state.weight_increase_events if at > one_hour_ago)
    fifteen_minutes_ago = now - timedelta(minutes=15)
    used_15_minutes = sum(amount for at, amount in history if at > fifteen_minutes_ago)
    used_hourly = sum(amount for _at, amount in history)
    base = max(0.0, state.day_start_base_weight)
    allowed = max(0.0, min(base * 0.05 - used_15_minutes, base * 0.10 - used_hourly))
    increase = min(target - state.effective_weight, allowed)
    if increase <= 0:
        return replace(state, weight_increase_events=history)
    return replace(
        state,
        effective_weight=state.effective_weight + increase,
        weight_increase_events=history + ((now, increase),),
    )


def update_rank_state(
    state: SleeveDynamicState,
    candidate: RankingCandidate,
    now: datetime,
    *,
    active_zone: bool,
    qualified_zone: bool,
    target_weight: float | None = None,
    required_active_qualifications: int = 2,
    entry_shadow_duration: timedelta = timedelta(minutes=10),
    fast_activation: bool = False,
) -> SleeveDynamicState:
    """Apply one 15-minute rank decision without leaking client budget across sleeves."""
    now = _ensure_aware(now)
    if required_active_qualifications < 1:
        raise ValueError("required_active_qualifications must be positive")
    if entry_shadow_duration <= timedelta(0):
        raise ValueError("entry_shadow_duration must be positive")
    # Ranking feeds can replay after a restart or arrive out of order. A rank
    # cycle is a state transition, so replaying it must not advance counters or
    # consume another weight-increase allowance.
    if state.last_ranked_at is not None and now <= state.last_ranked_at:
        return state
    if not candidate.hard_eligible:
        return replace(
            _reduce_weight(state, 0.0, now), tier=PoolTier.HARD_REJECTED,
            consecutive_active_qualifications=0, consecutive_qualified_falls=0,
            shadow_started_at=None, shadow_ends_at=None, last_ranked_at=now,
        )
    if state.tier in (PoolTier.HARD_REJECTED, PoolTier.EXECUTION_SUSPENDED, PoolTier.RECOVERY_SHADOW):
        return replace(state, last_ranked_at=now)

    active_ok = active_zone and candidate.executable
    desired = state.day_start_base_weight if target_weight is None else target_weight
    if state.tier == PoolTier.ENTRY_SHADOW:
        if not active_ok:
            return replace(_reduce_weight(state, 0.0, now), tier=PoolTier.MONITOR,
                           consecutive_active_qualifications=0, shadow_started_at=None,
                           shadow_ends_at=None, last_ranked_at=now)
        return replace(
            state,
            tier=PoolTier.ACTIVE,
            effective_weight=max(0.0, float(desired)),
            consecutive_active_qualifications=max(
                state.consecutive_active_qualifications, 1,
            ),
            consecutive_qualified_falls=0,
            shadow_started_at=None,
            shadow_ends_at=None,
            last_ranked_at=now,
        )

    if state.tier == PoolTier.ACTIVE:
        # An ACTIVE sleeve must remain executable. Losing either execution gate
        # is not a soft rank fall because this sleeve can no longer place orders.
        if not candidate.executable:
            return replace(
                _reduce_weight(state, 0.0, now),
                tier=PoolTier.MONITOR,
                consecutive_active_qualifications=0,
                consecutive_qualified_falls=0,
                last_ranked_at=now,
            )
        if not qualified_zone:
            falls = state.consecutive_qualified_falls + 1
            reduced = _reduce_weight(state, min(state.effective_weight, state.day_start_base_weight * 0.70), now)
            if falls >= 2:
                return replace(_reduce_weight(reduced, 0.0, now), tier=PoolTier.MONITOR,
                               consecutive_qualified_falls=falls, last_ranked_at=now)
            return replace(reduced, consecutive_qualified_falls=falls, last_ranked_at=now)
        if not active_zone:
            reduced = _reduce_weight(state, min(state.effective_weight, state.day_start_base_weight * 0.70), now)
            return replace(reduced, consecutive_qualified_falls=0, last_ranked_at=now)
        restored = replace(state, consecutive_qualified_falls=0, last_ranked_at=now)
        return _increase_weight(restored, desired, now)

    if not active_ok:
        return replace(
            _reduce_weight(state, 0.0, now),
            tier=PoolTier.MONITOR,
            consecutive_active_qualifications=0,
            consecutive_qualified_falls=0,
            shadow_started_at=None,
            shadow_ends_at=None,
            last_ranked_at=now,
        )
    return replace(
        state,
        tier=PoolTier.ACTIVE,
        effective_weight=max(0.0, float(desired)),
        consecutive_active_qualifications=max(
            state.consecutive_active_qualifications + 1, 1,
        ),
        consecutive_qualified_falls=0,
        shadow_started_at=None,
        shadow_ends_at=None,
        last_ranked_at=now,
    )


def advance_shadow_state(
    state: SleeveDynamicState, now: datetime, *, still_qualified: bool = True,
    shadow_health_ok: bool,
    target_weight: float | None = None,
    entry_shadow_duration: timedelta = timedelta(minutes=10),
) -> SleeveDynamicState:
    """Advance shadows only after an explicitly healthy observation window."""
    now = _ensure_aware(now)
    if entry_shadow_duration <= timedelta(0):
        raise ValueError("entry_shadow_duration must be positive")
    if state.tier == PoolTier.ENTRY_SHADOW:
        if not still_qualified:
            return replace(_reduce_weight(state, 0.0, now), tier=PoolTier.MONITOR,
                           consecutive_active_qualifications=0, shadow_started_at=None, shadow_ends_at=None)
        if not shadow_health_ok:
            return replace(
                _reduce_weight(state, 0.0, now),
                shadow_started_at=now,
                shadow_ends_at=now + entry_shadow_duration,
            )
        recent_rank = state.last_ranked_at is not None and now - state.last_ranked_at <= timedelta(minutes=15)
        if state.shadow_ends_at is not None and now >= state.shadow_ends_at and recent_rank:
            promoted = replace(state, tier=PoolTier.ACTIVE, consecutive_qualified_falls=0)
            return _increase_weight(promoted, state.day_start_base_weight if target_weight is None else target_weight, now)
        return state
    if state.tier == PoolTier.RECOVERY_SHADOW:
        if not still_qualified or not shadow_health_ok:
            return replace(state, tier=PoolTier.EXECUTION_SUSPENDED, recovery_shadow_started_at=None)
        if state.recovery_shadow_started_at is not None and now - state.recovery_shadow_started_at >= timedelta(minutes=10):
            return replace(state, tier=PoolTier.MONITOR, consecutive_active_qualifications=0,
                           consecutive_qualified_falls=0, recovery_shadow_started_at=None)
    return state


def daily_rebuild(
    state: SleeveDynamicState, base_weight: float, daily_loss_budget: float, *, hard_eligible: bool = False
) -> SleeveDynamicState:
    """Reset daily state only after a complete hard-eligibility pass.

    ``hard_eligible`` defaults to false so a stale or partial rebuild cannot
    accidentally release a HARD_REJECTED sleeve.
    """
    rebuilt = replace(
        state,
        day_start_base_weight=max(0.0, base_weight),
        frozen_daily_loss_budget=max(0.0, daily_loss_budget),
        released_weight=0.0,
        redistribution_eligible_at=None,
        released_weight_events=(),
        consecutive_active_qualifications=0,
        consecutive_qualified_falls=0,
        weight_increase_events=(),
    )
    if state.tier == PoolTier.EXECUTION_SUSPENDED:
        return replace(rebuilt, shadow_started_at=None, shadow_ends_at=None)
    if state.tier == PoolTier.HARD_REJECTED:
        if not hard_eligible:
            return replace(rebuilt, tier=PoolTier.HARD_REJECTED, effective_weight=0.0,
                           shadow_started_at=None, shadow_ends_at=None)
        return replace(rebuilt, tier=PoolTier.MONITOR, effective_weight=0.0,
                       shadow_started_at=None, shadow_ends_at=None)
    if state.tier == PoolTier.ENTRY_SHADOW:
        return replace(rebuilt, tier=PoolTier.MONITOR, effective_weight=0.0,
                       shadow_started_at=None, shadow_ends_at=None)
    return rebuilt


def redistribution_available(state: SleeveDynamicState, now: datetime) -> float:
    now = _ensure_aware(now)
    return sum(amount for at, amount in state.released_weight_events if now - at >= timedelta(minutes=30))


def consume_redistribution(
    state: SleeveDynamicState, now: datetime, amount: float | None = None
) -> tuple[SleeveDynamicState, float]:
    """Consume mature released-weight batches once; newer batches remain locked."""
    now = _ensure_aware(now)
    available = redistribution_available(state, now)
    requested = available if amount is None else _finite_nonnegative(amount, "redistribution amount")
    consume = min(requested, available)
    remaining = consume
    retained: list[tuple[datetime, float]] = []
    for at, event_amount in state.released_weight_events:
        if now - at >= timedelta(minutes=30) and remaining > 0:
            used = min(event_amount, remaining)
            event_amount -= used
            remaining -= used
        if event_amount > 0:
            retained.append((at, event_amount))
    next_eligible = min((at + timedelta(minutes=30) for at, _amount in retained), default=None)
    return replace(state, released_weight=sum(value for _at, value in retained),
                   released_weight_events=tuple(retained), redistribution_eligible_at=next_eligible), consume


def allowed_signal_delay_seconds(conservative_break_even_seconds: float, hold_p25_seconds: float) -> float:
    first = _finite_nonnegative(conservative_break_even_seconds, "conservative break-even delay")
    second = _finite_nonnegative(hold_p25_seconds, "holding P25")
    return min(first, second / 3.0)


def is_signal_expired(latency_seconds: float, allowed_delay_seconds: float) -> bool:
    """Equality is still timely. Exit expiry records quality only; execution may still reduce risk."""
    latency = _finite_nonnegative(latency_seconds, "signal latency")
    allowed = _finite_nonnegative(allowed_delay_seconds, "allowed signal delay")
    return latency > allowed


def record_expired_signal(
    state: SleeveDynamicState, direction: str, now: datetime
) -> SleeveDynamicState:
    """Record an entry or exit expiry; three same-direction expiries in 15m suspend."""
    now = _ensure_aware(now)
    if direction not in ("entry", "exit"):
        raise ValueError("direction must be 'entry' or 'exit'")
    cutoff = now - timedelta(minutes=15)
    entries = tuple(item for item in state.entry_expired_at if item >= cutoff)
    exits = tuple(item for item in state.exit_expired_at if item >= cutoff)
    if direction == "entry":
        entries += (now,)
    else:
        exits += (now,)
    next_state = replace(state, entry_expired_at=entries, exit_expired_at=exits)
    if len(entries) >= 3 or len(exits) >= 3:
        return replace(_reduce_weight(next_state, 0.0, now), tier=PoolTier.EXECUTION_SUSPENDED,
                       suspended_at=now, recovery_shadow_started_at=None)
    return next_state


def advance_expiry_recovery(state: SleeveDynamicState, now: datetime) -> SleeveDynamicState:
    """After ten quiet minutes, move a suspended sleeve to recovery shadow only."""
    now = _ensure_aware(now)
    if state.tier != PoolTier.EXECUTION_SUSPENDED:
        return state
    events = state.entry_expired_at + state.exit_expired_at
    latest = max(events) if events else state.suspended_at
    if latest is not None and now - latest >= timedelta(minutes=10):
        return replace(state, tier=PoolTier.RECOVERY_SHADOW, recovery_shadow_started_at=now)
    return state


@dataclass(frozen=True)
class SchedulerState:
    last_risk_at: datetime | None = None
    last_rank_at: datetime | None = None
    last_discovery_at: datetime | None = None
    last_daily_rebuild_date: str | None = None

    def __post_init__(self) -> None:
        for stamp in (self.last_risk_at, self.last_rank_at, self.last_discovery_at):
            if stamp is not None:
                _ensure_aware(stamp)
        if self.last_daily_rebuild_date is not None:
            if not isinstance(self.last_daily_rebuild_date, str):
                raise ValueError("last_daily_rebuild_date must be an ISO date string")
            try:
                parsed = date.fromisoformat(self.last_daily_rebuild_date)
            except ValueError as exc:
                raise ValueError("last_daily_rebuild_date must be an ISO date string") from exc
            if parsed.isoformat() != self.last_daily_rebuild_date:
                raise ValueError("last_daily_rebuild_date must be an ISO date string")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "last_risk_at": _iso(self.last_risk_at),
            "last_rank_at": _iso(self.last_rank_at),
            "last_discovery_at": _iso(self.last_discovery_at),
            "last_daily_rebuild_date": self.last_daily_rebuild_date,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, str | None]) -> "SchedulerState":
        return cls(_parse_iso(payload.get("last_risk_at")), _parse_iso(payload.get("last_rank_at")),
                   _parse_iso(payload.get("last_discovery_at")), payload.get("last_daily_rebuild_date"))


@dataclass(frozen=True)
class SchedulerDue:
    risk: bool
    rank: bool
    discovery: bool
    daily_rebuild: bool


def scheduler_due(
    state: SchedulerState,
    now: datetime,
    *,
    is_trading_day: Callable[[date], bool] | None = None,
) -> SchedulerDue:
    """Return due schedules, with an injectable exchange trading-day calendar."""
    now = _ensure_aware(now)
    local = now.astimezone(BEIJING)
    date_key = local.date().isoformat()
    trading_day = is_trading_day or (lambda value: value.weekday() < 5)
    return SchedulerDue(
        risk=state.last_risk_at is None or now - state.last_risk_at >= timedelta(seconds=10),
        rank=state.last_rank_at is None or now - state.last_rank_at >= timedelta(minutes=15),
        discovery=state.last_discovery_at is None or now - state.last_discovery_at >= timedelta(hours=1),
        daily_rebuild=(
            trading_day(local.date())
            and local.timetz().replace(tzinfo=None) >= time(5, 15)
            and state.last_daily_rebuild_date != date_key
        ),
    )


def mark_scheduler_run(state: SchedulerState, now: datetime, *, risk: bool = False, rank: bool = False,
                       discovery: bool = False, daily_rebuild_run: bool = False) -> SchedulerState:
    now = _ensure_aware(now)
    return replace(
        state,
        last_risk_at=now if risk else state.last_risk_at,
        last_rank_at=now if rank else state.last_rank_at,
        last_discovery_at=now if discovery else state.last_discovery_at,
        last_daily_rebuild_date=now.astimezone(BEIJING).date().isoformat() if daily_rebuild_run else state.last_daily_rebuild_date,
    )


def acknowledge_accepted_pool_build(state: SchedulerState, build_day: str) -> SchedulerState:
    """Advance scheduler state to an already validated accepted-pool build date."""
    parsed = date.fromisoformat(build_day)
    normalized = parsed.isoformat()
    if normalized != build_day:
        raise ValueError("build_day must be an ISO date string")
    if state.last_daily_rebuild_date is not None and state.last_daily_rebuild_date >= build_day:
        return state
    return replace(state, last_daily_rebuild_date=build_day)
