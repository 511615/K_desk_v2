from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping


WINDOWS_EPOCH_TICKS = 116_444_736_000_000_000
TICKS_PER_SECOND = 10_000_000


def canonical_symbol(symbol: str) -> str:
    return str(symbol).upper().split(".", 1)[0]


def filetime_to_datetime(value: int) -> datetime:
    seconds = (int(value) - WINDOWS_EPOCH_TICKS) / TICKS_PER_SECOND
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def datetime_to_filetime(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * TICKS_PER_SECOND + WINDOWS_EPOCH_TICKS)


def is_abook_status(value: object) -> bool:
    return "A" in str(value or "").upper()


def holding_score_multiplier(median_seconds: float | None) -> float:
    if median_seconds is None or not math.isfinite(median_seconds):
        return 1.0
    if median_seconds <= 3.0:
        return 0.0
    if median_seconds >= 30.0:
        return 1.0
    return 0.5 + 0.5 * (median_seconds - 3.0) / 27.0


def intraday_multiplier(net_usd: float, equity_usd: float) -> float:
    if equity_usd <= 0 or net_usd >= 0:
        return 1.0
    loss_rate = -net_usd / equity_usd
    if loss_rate >= 0.02:
        return 0.0
    if loss_rate >= 0.01:
        return 0.5 * (0.02 - loss_rate) / 0.01
    return 1.0 - 0.5 * loss_rate / 0.01


def normalize_with_cap(
    raw: Mapping[int, float], budget: float = 0.25, cap: float = 0.03
) -> dict[int, float]:
    weights = {key: 0.0 for key in raw}
    remaining = {key for key, value in raw.items() if value > 0}
    remaining_budget = budget
    while remaining and remaining_budget > 1e-12:
        subtotal = sum(raw[key] for key in remaining)
        if subtotal <= 0:
            break
        proposed = {
            key: raw[key] / subtotal * remaining_budget for key in remaining
        }
        over = [key for key, value in proposed.items() if value > cap]
        if not over:
            weights.update(proposed)
            break
        for key in over:
            weights[key] = cap
            remaining.remove(key)
            remaining_budget -= cap
    return weights


def quantize_lots(value: float, step: float = 0.01) -> float:
    if step <= 0:
        raise ValueError("Lot step must be positive.")
    sign = 1.0 if value >= 0 else -1.0
    units = math.floor(abs(value) / step + 0.5 + 1e-12)
    return round(sign * units * step, 8)


def position_lot_cap(
    *,
    reference_equity_usd: float,
    current_equity_usd: float,
    hard_cap_lots: float,
    stress_move_usd_per_unit: float,
    contract_size: float,
    risk_fraction: float,
    margin_per_lot_usd: float,
    margin_fraction: float,
    lot_step: float = 0.01,
) -> float:
    values = (
        reference_equity_usd,
        current_equity_usd,
        hard_cap_lots,
        stress_move_usd_per_unit,
        contract_size,
        risk_fraction,
        margin_per_lot_usd,
        margin_fraction,
        lot_step,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Position-cap inputs must be finite.")
    if min(reference_equity_usd, current_equity_usd, hard_cap_lots, lot_step) <= 0:
        return 0.0
    if min(stress_move_usd_per_unit, contract_size, risk_fraction) <= 0:
        return 0.0
    if min(margin_per_lot_usd, margin_fraction) <= 0:
        return 0.0
    stress_cap = (
        reference_equity_usd
        * risk_fraction
        / (stress_move_usd_per_unit * contract_size)
    )
    margin_cap = current_equity_usd * margin_fraction / margin_per_lot_usd
    raw_cap = min(hard_cap_lots, stress_cap, margin_cap)
    units = math.floor(raw_cap / lot_step + 1e-12)
    return round(max(0, units) * lot_step, 8)


def drawdown_throttle(cycle_pnl_usd: float, loss_limit_usd: float) -> float:
    """Scale exposure from 100% to 0% as a cycle approaches its loss stop."""
    if loss_limit_usd <= 0:
        raise ValueError("Loss limit must be positive.")
    if cycle_pnl_usd >= 0:
        return 1.0
    used = min(1.0, -cycle_pnl_usd / loss_limit_usd)
    if used <= 0.20:
        return 1.0
    return max(0.0, (1.0 - used) / 0.80)


def hysteresis_target(
    raw_target: float,
    current_target: float,
    max_lots: float = 0.01,
    enter_lots: float = 0.01,
    exit_lots: float = 0.005,
    lot_step: float = 0.01,
) -> float:
    if max_lots < 0 or enter_lots <= 0 or exit_lots < 0 or lot_step <= 0:
        raise ValueError("Position thresholds must be positive.")
    if max_lots < lot_step - 1e-12:
        return 0.0

    def target_for(value: float) -> float:
        capped = max(-max_lots, min(max_lots, value))
        quantized = quantize_lots(capped, lot_step)
        return max(-max_lots, min(max_lots, quantized))

    if abs(current_target) < 1e-12:
        if raw_target >= enter_lots:
            return target_for(raw_target)
        if raw_target <= -enter_lots:
            return target_for(raw_target)
        return 0.0
    if current_target > 0:
        if raw_target <= -enter_lots:
            return target_for(raw_target)
        if abs(raw_target) <= exit_lots:
            return 0.0
        if raw_target > 0:
            return max(lot_step, target_for(raw_target))
        return min(current_target, max_lots)
    if raw_target >= enter_lots:
        return target_for(raw_target)
    if abs(raw_target) <= exit_lots:
        return 0.0
    if raw_target < 0:
        return min(-lot_step, target_for(raw_target))
    return max(current_target, -max_lots)


def guarded_execution_target(
    current: float,
    desired: float,
    allow_new_exposure: bool,
    tolerance: float = 1e-9,
) -> float:
    """Return the immediately executable target without combining a gated reversal."""
    if abs(current - desired) <= tolerance:
        return current
    reversal = current * desired < -(tolerance**2)
    increases_exposure = abs(desired) > abs(current) + tolerance
    if allow_new_exposure:
        return desired
    if reversal:
        return 0.0
    if increases_exposure:
        return current
    return desired


def update_source_position(
    current: float,
    action: int,
    entry: int,
    lots: float,
    volume_closed_lots: float = 0.0,
) -> float:
    if action not in (0, 1) or entry not in (0, 1, 2, 3):
        return current
    sign = 1.0 if action == 0 else -1.0
    if entry == 0:
        return current + sign * lots
    if entry in (1, 3):
        if current > 0 and sign < 0:
            return max(0.0, current - lots)
        if current < 0 and sign > 0:
            return min(0.0, current + lots)
        return current
    close_lots = min(abs(current), max(0.0, volume_closed_lots))
    if current > 0 and sign < 0:
        reduced = max(0.0, current - close_lots)
    elif current < 0 and sign > 0:
        reduced = min(0.0, current + close_lots)
    else:
        reduced = current
    open_lots = max(0.0, lots - close_lots)
    return reduced + sign * open_lots


@dataclass(frozen=True)
class ClientSpec:
    login: int
    alias: str
    equity_usd: float
    base_weight: float
    money_scale: float = 1.0
    adjusted_score: float = 0.0
    is_abook: bool = False
    median_hold_seconds: float | None = None


@dataclass(frozen=True, order=True)
class DealCursor:
    timestamp: int = 0
    deal: int = 0


@dataclass(frozen=True)
class DealEvent:
    deal: int
    timestamp: int
    login: int
    position_id: int
    action: int
    entry: int
    symbol: str
    lots: float
    volume_closed_lots: float
    profit: float
    commission: float
    storage: float
    fee: float

    @property
    def cursor(self) -> DealCursor:
        return DealCursor(self.timestamp, self.deal)


@dataclass
class SourcePortfolio:
    clients: Mapping[int, ClientSpec]
    positions: dict[tuple[int, int, str], float] = field(default_factory=dict)
    intraday_net_usd: dict[int, float] = field(default_factory=dict)
    effective_weights: dict[int, float] = field(default_factory=dict)
    cursor: DealCursor = field(default_factory=DealCursor)
    duplicate_events: int = 0

    def __post_init__(self) -> None:
        for login, client in self.clients.items():
            self.intraday_net_usd.setdefault(login, 0.0)
            self.effective_weights.setdefault(login, client.base_weight)

    def replace_positions(self, rows: Iterable[Mapping[str, object]]) -> None:
        replacement: dict[tuple[int, int, str], float] = {}
        for row in rows:
            login = int(row["Login"])
            if login not in self.clients:
                continue
            product = canonical_symbol(str(row["Symbol"]))
            lots = float(row["lots"])
            signed = lots if int(row["Action"]) == 0 else -lots
            if abs(signed) > 1e-12:
                replacement[(login, int(row["Position"]), product)] = signed
        self.positions = replacement

    def apply_deal(self, event: DealEvent) -> bool:
        if event.cursor <= self.cursor:
            self.duplicate_events += 1
            return False
        self.cursor = event.cursor
        client = self.clients.get(event.login)
        if client is None:
            return False
        product = canonical_symbol(event.symbol)
        key = (event.login, event.position_id, product)
        current = self.positions.get(key, 0.0)
        updated = update_source_position(
            current,
            event.action,
            event.entry,
            event.lots,
            event.volume_closed_lots,
        )
        if abs(updated) < 1e-12:
            self.positions.pop(key, None)
        else:
            self.positions[key] = updated
        net_delta = (
            event.profit + event.commission + event.storage + event.fee
        ) * client.money_scale
        self.intraday_net_usd[event.login] += net_delta
        self.effective_weights[event.login] = (
            client.base_weight
            * intraday_multiplier(
                self.intraday_net_usd[event.login], client.equity_usd
            )
        )
        return True

    def set_intraday_net(self, values: Mapping[int, float]) -> None:
        for login, net in values.items():
            if login not in self.clients:
                continue
            client = self.clients[login]
            net_usd = float(net) * client.money_scale
            self.intraday_net_usd[login] = net_usd
            self.effective_weights[login] = client.base_weight * intraday_multiplier(
                net_usd, client.equity_usd
            )

    def client_product_position(self, login: int, product: str) -> float:
        return sum(
            lots
            for (row_login, _position_id, row_product), lots in self.positions.items()
            if row_login == login and row_product == product
        )

    def target(self, product: str, demo_equity_usd: float) -> tuple[float, float, float]:
        contributions: list[float] = []
        for login, client in self.clients.items():
            source_lots = self.client_product_position(login, product)
            if abs(source_lots) < 1e-12:
                continue
            contributions.append(
                source_lots
                * demo_equity_usd
                * self.effective_weights[login]
                / max(client.equity_usd, 1.0)
            )
        gross_long = sum(max(value, 0.0) for value in contributions)
        gross_short = sum(max(-value, 0.0) for value in contributions)
        return sum(contributions), gross_long, gross_short

    def comparable_positions(self) -> dict[tuple[int, int, str], float]:
        return {
            key: round(value, 8)
            for key, value in self.positions.items()
            if abs(value) > 1e-10
        }


def server_time_from_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone(timedelta(hours=3)))


def friday_policy(server_time: datetime) -> str:
    if server_time.weekday() != 4:
        return "normal"
    if (server_time.hour, server_time.minute) >= (23, 30):
        return "flatten"
    if (server_time.hour, server_time.minute) >= (22, 30):
        return "reduce_only"
    return "normal"
