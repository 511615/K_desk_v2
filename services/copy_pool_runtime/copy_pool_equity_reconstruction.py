"""Account intraday equity reconstruction from authoritative daily rows and position snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from copy_pool_factor_domain import AdjustedEquityPoint


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class DailyEquityAnchor:
    timestamp: datetime
    balance_credit_usd: float
    equity_usd: float
    external_cashflow_usd: float = 0.0

    def __post_init__(self) -> None:
        _utc(self.timestamp, "DailyEquityAnchor.timestamp")


@dataclass(frozen=True)
class AccountMoneyEvent:
    timestamp: datetime
    sequence: int
    account_value_delta_usd: float
    external_cashflow_usd: float = 0.0

    def __post_init__(self) -> None:
        _utc(self.timestamp, "AccountMoneyEvent.timestamp")


@dataclass(frozen=True)
class PositionInterval:
    position_id: str
    opened_at: datetime
    closed_at: datetime

    def __post_init__(self) -> None:
        opened = _utc(self.opened_at, "PositionInterval.opened_at")
        closed = _utc(self.closed_at, "PositionInterval.closed_at")
        if closed < opened:
            raise ValueError("PositionInterval.closed_at must not precede opened_at")


@dataclass(frozen=True)
class PositionFloatingSnapshot:
    timestamp: datetime
    position_id: str
    floating_usd: float

    def __post_init__(self) -> None:
        _utc(self.timestamp, "PositionFloatingSnapshot.timestamp")


@dataclass(frozen=True)
class ReconstructedEquity:
    points: tuple[AdjustedEquityPoint, ...]
    intraday_complete: bool
    reasons: tuple[str, ...]
    emitted_intraday_points: int
    skipped_incomplete_snapshots: int


def reconstruct_intraday_equity(
    anchors: Iterable[DailyEquityAnchor],
    money_events: Iterable[AccountMoneyEvent],
    intervals: Iterable[PositionInterval],
    snapshots: Iterable[PositionFloatingSnapshot],
    *,
    max_snapshot_sync_gap_seconds: float = 2.0,
) -> ReconstructedEquity:
    """Reconstruct only synchronized points; never treat missing position floats as zero."""
    daily = sorted(anchors, key=lambda item: _utc(item.timestamp, "anchor"))
    if not daily:
        return ReconstructedEquity((), False, ("missing_daily_equity_anchor",), 0, 0)
    positions = tuple(intervals)
    by_position = {item.position_id: item for item in positions}
    if len(by_position) != len(positions):
        raise ValueError("Position intervals must be unique by position_id")

    timeline: list[tuple[datetime, int, int, object]] = []
    for index, item in enumerate(daily):
        timeline.append((_utc(item.timestamp, "anchor"), 0, index, item))
    for index, item in enumerate(money_events):
        timeline.append((_utc(item.timestamp, "money event"), 1, int(item.sequence), item))
    for index, item in enumerate(snapshots):
        if item.position_id not in by_position:
            continue
        timeline.append((_utc(item.timestamp, "snapshot"), 2, index, item))
    timeline.sort(key=lambda item: (item[0], item[1], item[2]))

    balance_credit = float(daily[0].balance_credit_usd)
    latest_float: dict[str, float] = {}
    points: list[AdjustedEquityPoint] = []
    emitted = 0
    skipped = 0
    pending_since: datetime | None = None
    saw_snapshot_for = {key: False for key in by_position}

    for timestamp, kind, _sequence, payload in timeline:
        if kind == 0:
            item = payload
            assert isinstance(item, DailyEquityAnchor)
            balance_credit = float(item.balance_credit_usd)
            points.append(
                AdjustedEquityPoint(
                    timestamp=timestamp,
                    equity_usd=float(item.equity_usd),
                    external_cashflow_usd=float(item.external_cashflow_usd),
                )
            )
            continue
        if kind == 1:
            item = payload
            assert isinstance(item, AccountMoneyEvent)
            balance_credit += float(item.account_value_delta_usd)
            if item.external_cashflow_usd:
                active = [
                    key for key, interval in by_position.items()
                    if _utc(interval.opened_at, "opened") <= timestamp < _utc(interval.closed_at, "closed")
                ]
                if all(saw_snapshot_for[key] for key in active):
                    points.append(
                        AdjustedEquityPoint(
                            timestamp=timestamp,
                            equity_usd=balance_credit + sum(latest_float.get(key, 0.0) for key in active),
                            external_cashflow_usd=float(item.external_cashflow_usd),
                        )
                    )
            continue

        item = payload
        assert isinstance(item, PositionFloatingSnapshot)
        interval = by_position[item.position_id]
        if not (_utc(interval.opened_at, "opened") <= timestamp <= _utc(interval.closed_at, "closed")):
            continue
        latest_float[item.position_id] = float(item.floating_usd)
        saw_snapshot_for[item.position_id] = True
        active = [
            key for key, candidate in by_position.items()
            if _utc(candidate.opened_at, "opened") <= timestamp < _utc(candidate.closed_at, "closed")
        ]
        if not all(saw_snapshot_for[key] and key in latest_float for key in active):
            pending_since = pending_since or timestamp
            continue
        if pending_since is not None:
            if (timestamp - pending_since).total_seconds() > max_snapshot_sync_gap_seconds:
                skipped += 1
            pending_since = None
        points.append(
            AdjustedEquityPoint(
                timestamp=timestamp,
                equity_usd=balance_credit + sum(latest_float[key] for key in active),
            )
        )
        emitted += 1

    ordered: dict[datetime, AdjustedEquityPoint] = {}
    for point in sorted(points, key=lambda item: item.timestamp):
        previous = ordered.get(point.timestamp)
        if previous is not None and point.external_cashflow_usd == 0:
            point = AdjustedEquityPoint(
                timestamp=point.timestamp,
                equity_usd=point.equity_usd,
                external_cashflow_usd=previous.external_cashflow_usd,
            )
        ordered[point.timestamp] = point

    reasons: list[str] = []
    missing_positions = sorted(key for key, seen in saw_snapshot_for.items() if not seen)
    if missing_positions:
        reasons.append("missing_position_snapshot_coverage")
    if pending_since is not None:
        skipped += 1
    if skipped:
        reasons.append("unsynchronized_position_snapshot_coverage")
    if positions and emitted == 0:
        reasons.append("missing_intraday_equity_points")
    return ReconstructedEquity(
        points=tuple(ordered.values()),
        intraday_complete=not reasons,
        reasons=tuple(reasons),
        emitted_intraday_points=emitted,
        skipped_incomplete_snapshots=skipped,
    )
