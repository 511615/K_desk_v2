from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def source_position_key(account_key: str, position_id: int, product: str) -> str:
    return f"{account_key}|{int(position_id)}|{product}"


def copy_comment(alias: str, account_key: str, position_id: int, product: str) -> str:
    digest = hashlib.sha1(
        f"{account_key}|{int(position_id)}|{product}".encode("utf-8")
    ).hexdigest()[:6].upper()
    return f"CPV2:{alias}:{digest}"


def loss_budget_multiplier(usage: float) -> float:
    value = max(0.0, float(usage))
    if value >= 1.0:
        return 0.0
    if value <= 0.20:
        return 1.0
    if value <= 0.50:
        return 1.0 - 0.30 * (value - 0.20) / 0.30
    if value <= 0.80:
        return 0.70 - 0.45 * (value - 0.50) / 0.30
    return 0.25 * (1.0 - (value - 0.80) / 0.20)


def slow_weight_increase(
    current: float,
    target: float,
    elapsed_minutes: float,
    per_15_minutes: float = 0.05,
    per_hour: float = 0.10,
) -> float:
    if target <= current:
        return max(0.0, target)
    elapsed = max(0.0, float(elapsed_minutes))
    allowed = min(
        per_15_minutes * elapsed / 15.0,
        per_hour * elapsed / 60.0,
    )
    return min(target, current + allowed)


def quantize_lots(value: float, minimum: float, step: float) -> float:
    if value < minimum - 1e-12:
        return 0.0
    units = math.floor(value / step + 1e-12)
    result = round(units * step, 8)
    return result if result >= minimum - 1e-12 else 0.0


@dataclass
class DemoChildTicket:
    ticket: int
    lots: float
    side: int
    open_time: str
    open_price: float


@dataclass
class IndependentCopyPosition:
    source_key: str
    account_key: str
    client_alias: str
    product: str
    source_position_id: int
    source_lots: float
    copied_lots: float = 0.0
    copy_eligible: bool = False
    restart_monitor_only: bool = False
    comment: str = ""
    status: str = "monitor"
    reject_reason: str = ""
    source_opened_at: str = ""
    first_signal_at: str = ""
    last_signal_at: str = ""
    risk_signal_at: str = ""
    source_closed_at: str = ""
    source_open_price: float | None = None
    source_current_price: float | None = None
    source_realized_pnl_usd: float | None = None
    source_floating_pnl_usd: float | None = None
    source_total_pnl_usd: float | None = None
    demo_realized_pnl_usd: float | None = None
    demo_floating_pnl_usd: float | None = None
    demo_total_pnl_usd: float | None = None
    exit_only_source_baseline_lots: float = 0.0
    exit_only_copy_baseline_lots: float = 0.0
    last_action: str = "monitor"
    children: list[DemoChildTicket] = field(default_factory=list)

    @property
    def side(self) -> int:
        return 1 if self.source_lots > 0 else -1 if self.source_lots < 0 else 0

    @property
    def copied_signed_lots(self) -> float:
        return sum(child.lots * child.side for child in self.children)

    def public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side
        payload["copied_signed_lots"] = self.copied_signed_lots
        payload["demo_tickets"] = [child.ticket for child in self.children]
        return payload


@dataclass
class ClientCopyRisk:
    account_key: str
    client_alias: str
    base_weight: float
    effective_weight: float
    loss_budget_usd: float
    realized_pnl_usd: float = 0.0
    floating_pnl_usd: float = 0.0
    cycle_baseline_pnl_usd: float = 0.0
    pause_until: str | None = None
    recovery_shadow_until: str | None = None
    last_weight_update_at: str | None = None
    status: str = "monitor"
    reduction_reason: str = ""

    @property
    def total_pnl_usd(self) -> float:
        return (
            self.realized_pnl_usd
            + self.floating_pnl_usd
            - self.cycle_baseline_pnl_usd
        )

    @property
    def loss_used_usd(self) -> float:
        return max(-self.total_pnl_usd, 0.0)

    @property
    def loss_usage(self) -> float:
        if self.loss_budget_usd <= 0:
            return float("inf")
        return self.loss_used_usd / self.loss_budget_usd

    def public(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "total_pnl_usd": self.total_pnl_usd,
            "loss_used_usd": self.loss_used_usd,
            "loss_usage": self.loss_usage,
            "loss_multiplier": loss_budget_multiplier(self.loss_usage),
        }

    def is_paused(self, now: datetime) -> bool:
        return _future(self.pause_until, now)

    def is_recovery_shadow(self, now: datetime) -> bool:
        return _future(self.recovery_shadow_until, now)


def _future(value: str | None, now: datetime) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return parsed > reference


@dataclass
class IndependentCopyBook:
    legacy_source_positions: set[str] = field(default_factory=set)
    positions: dict[str, IndependentCopyPosition] = field(default_factory=dict)
    clients: dict[str, ClientCopyRisk] = field(default_factory=dict)
    rejected_events: int = 0

    def mark_bootstrap_positions(self, rows: Iterable[Mapping[str, Any]]) -> None:
        current: set[str] = set()
        for row in rows:
            key = source_position_key(
                str(row["account_key"]),
                int(row["position_id"]),
                str(row["product"]),
            )
            current.add(key)
            if key in self.positions:
                position = self.positions[key]
                observed = float(row["lots"])
                approved = float(position.source_lots)
                if approved * observed > 0:
                    # A reduction that happened while offline must reduce the
                    # Demo copy. An increase is not approved without its live
                    # source event and therefore must never be chased.
                    if abs(observed) < abs(approved):
                        position.source_lots = observed
                elif abs(observed) < 1e-12 or approved * observed < 0:
                    # A close or reversal observed only at restart may remove
                    # old risk, but the opposite leg remains monitor-only.
                    position.source_lots = 0.0
            else:
                self.legacy_source_positions.add(key)
        for key, position in self.positions.items():
            if key not in current and abs(position.source_lots) > 1e-12:
                position.source_lots = 0.0
        self.legacy_source_positions.intersection_update(current)

    def mark_restart_positions_monitor_only(
        self,
        restored_source_keys: Iterable[str],
    ) -> int:
        marked = 0
        for key in restored_source_keys:
            position = self.positions.get(str(key))
            if (
                position is None
                or position.children
                or abs(position.source_lots) < 1e-12
            ):
                continue
            position.copy_eligible = False
            position.restart_monitor_only = True
            position.status = "monitor"
            position.reject_reason = "restart_without_demo_ticket"
            marked += 1
        return marked

    def migrate_source_position(
        self,
        account_key: str,
        client_alias: str,
        product: str,
        previous_position_id: int,
        replacement_position_id: int,
    ) -> IndependentCopyPosition | None:
        """Move MT4 ownership across a partial-close replacement Ticket."""
        previous_key = source_position_key(
            account_key, previous_position_id, product
        )
        replacement_key = source_position_key(
            account_key, replacement_position_id, product
        )
        if previous_key == replacement_key:
            return self.positions.get(previous_key)
        if replacement_key in self.positions or replacement_key in self.legacy_source_positions:
            raise RuntimeError(
                f"Replacement source position already exists: {replacement_key}"
            )
        if previous_key in self.legacy_source_positions:
            self.legacy_source_positions.remove(previous_key)
            self.legacy_source_positions.add(replacement_key)
            return None
        position = self.positions.pop(previous_key, None)
        if position is None:
            return None
        position.source_key = replacement_key
        position.source_position_id = int(replacement_position_id)
        position.client_alias = client_alias
        self.positions[replacement_key] = position
        return position

    def observe_source_position(
        self,
        account_key: str,
        client_alias: str,
        product: str,
        position_id: int,
        before_lots: float,
        after_lots: float,
        signal_time: datetime,
    ) -> tuple[str, IndependentCopyPosition | None]:
        key = source_position_key(account_key, position_id, product)
        stamp = signal_time.isoformat()
        if key in self.legacy_source_positions:
            if abs(after_lots) < 1e-12:
                self.legacy_source_positions.remove(key)
            return "legacy_monitor_only", None
        existing = self.positions.get(key)
        if existing is None:
            if abs(before_lots) > 1e-12 or abs(after_lots) < 1e-12:
                return "monitor_only", None
            created = IndependentCopyPosition(
                source_key=key,
                account_key=account_key,
                client_alias=client_alias,
                product=product,
                source_position_id=position_id,
                source_lots=after_lots,
                source_opened_at=stamp,
                comment=copy_comment(client_alias, account_key, position_id, product),
                status="pending_risk",
                first_signal_at=stamp,
                last_signal_at=stamp,
                risk_signal_at=stamp,
                last_action="open",
            )
            self.positions[key] = created
            return "open", created
        existing.last_signal_at = stamp
        if abs(after_lots) < 1e-12:
            existing.source_lots = 0.0
            existing.source_closed_at = stamp
            existing.last_action = "close"
            return "close", existing
        if existing.source_lots * after_lots < 0:
            existing.source_lots = after_lots
            existing.risk_signal_at = stamp
            existing.last_action = "reverse"
            return "reverse", existing
        action = "increase" if abs(after_lots) > abs(existing.source_lots) else "reduce"
        existing.source_lots = after_lots
        if action == "increase":
            existing.risk_signal_at = stamp
        existing.last_action = action
        return action, existing

    def positions_for_client(self, account_key: str) -> list[IndependentCopyPosition]:
        return [
            position
            for position in self.positions.values()
            if position.account_key == account_key
        ]

    def remove_closed(self, source_key: str) -> None:
        # Closed mappings remain in the current trading-day ledger so their Demo
        # realized P/L still belongs to the originating client's loss budget.
        position = self.positions.get(source_key)
        if position is not None and not position.children and abs(position.source_lots) < 1e-12:
            if position.restart_monitor_only:
                del self.positions[source_key]
            else:
                position.status = "closed"

    def prune_closed(self) -> None:
        self.positions = {
            key: position
            for key, position in self.positions.items()
            if position.children or abs(position.source_lots) >= 1e-12
        }

    def ticket_owners(self) -> dict[int, str]:
        return {
            child.ticket: key
            for key, position in self.positions.items()
            for child in position.children
        }

    def to_private(self) -> dict[str, Any]:
        return {
            "legacy_source_positions": sorted(self.legacy_source_positions),
            "positions": {
                key: position.public()
                for key, position in self.positions.items()
            },
            "clients": {
                key: risk.public()
                for key, risk in self.clients.items()
            },
            "rejected_events": self.rejected_events,
        }

    @classmethod
    def from_private(cls, payload: Mapping[str, Any] | None) -> "IndependentCopyBook":
        if not isinstance(payload, Mapping):
            return cls()
        book = cls(
            legacy_source_positions={
                str(value) for value in payload.get("legacy_source_positions", [])
            },
            rejected_events=int(payload.get("rejected_events", 0)),
        )
        for key, raw in dict(payload.get("positions", {})).items():
            if not isinstance(raw, Mapping):
                continue
            account_key = str(raw["account_key"])
            client_alias = str(raw["client_alias"])
            product = str(raw["product"])
            source_position_id = int(raw["source_position_id"])
            children = [
                DemoChildTicket(
                    ticket=int(child["ticket"]),
                    lots=float(child["lots"]),
                    side=int(child["side"]),
                    open_time=str(child.get("open_time") or ""),
                    open_price=float(child.get("open_price") or 0.0),
                )
                for child in raw.get("children", [])
                if isinstance(child, Mapping)
            ]
            book.positions[str(key)] = IndependentCopyPosition(
                source_key=str(key),
                account_key=account_key,
                client_alias=client_alias,
                product=product,
                source_position_id=source_position_id,
                source_lots=float(raw.get("source_lots", 0.0)),
                copied_lots=float(raw.get("copied_lots", 0.0)),
                copy_eligible=bool(raw.get("copy_eligible", False)),
                restart_monitor_only=bool(raw.get("restart_monitor_only", False)),
                comment=copy_comment(
                    client_alias, account_key, source_position_id, product
                ),
                status=str(raw.get("status") or "monitor"),
                reject_reason=str(raw.get("reject_reason") or ""),
                source_opened_at=str(raw.get("source_opened_at") or ""),
                first_signal_at=str(raw.get("first_signal_at") or ""),
                last_signal_at=str(raw.get("last_signal_at") or ""),
                risk_signal_at=str(
                    raw.get("risk_signal_at")
                    or raw.get("source_opened_at")
                    or raw.get("first_signal_at")
                    or ""
                ),
                source_closed_at=str(raw.get("source_closed_at") or ""),
                source_open_price=(
                    float(raw["source_open_price"])
                    if raw.get("source_open_price") is not None else None
                ),
                source_current_price=(
                    float(raw["source_current_price"])
                    if raw.get("source_current_price") is not None else None
                ),
                source_realized_pnl_usd=(
                    float(raw["source_realized_pnl_usd"])
                    if raw.get("source_realized_pnl_usd") is not None else None
                ),
                source_floating_pnl_usd=(
                    float(raw["source_floating_pnl_usd"])
                    if raw.get("source_floating_pnl_usd") is not None else None
                ),
                source_total_pnl_usd=(
                    float(raw["source_total_pnl_usd"])
                    if raw.get("source_total_pnl_usd") is not None else None
                ),
                demo_realized_pnl_usd=(
                    float(raw["demo_realized_pnl_usd"])
                    if raw.get("demo_realized_pnl_usd") is not None else None
                ),
                demo_floating_pnl_usd=(
                    float(raw["demo_floating_pnl_usd"])
                    if raw.get("demo_floating_pnl_usd") is not None else None
                ),
                demo_total_pnl_usd=(
                    float(raw["demo_total_pnl_usd"])
                    if raw.get("demo_total_pnl_usd") is not None else None
                ),
                exit_only_source_baseline_lots=float(
                    raw.get("exit_only_source_baseline_lots", 0.0)
                ),
                exit_only_copy_baseline_lots=float(
                    raw.get("exit_only_copy_baseline_lots", 0.0)
                ),
                last_action=str(raw.get("last_action") or "monitor"),
                children=children,
            )
        for key, raw in dict(payload.get("clients", {})).items():
            if not isinstance(raw, Mapping):
                continue
            book.clients[str(key)] = ClientCopyRisk(
                account_key=str(key),
                client_alias=str(raw["client_alias"]),
                base_weight=float(raw.get("base_weight", 0.0)),
                effective_weight=float(raw.get("effective_weight", 0.0)),
                loss_budget_usd=float(raw.get("loss_budget_usd", 0.0)),
                realized_pnl_usd=float(raw.get("realized_pnl_usd", 0.0)),
                floating_pnl_usd=float(raw.get("floating_pnl_usd", 0.0)),
                cycle_baseline_pnl_usd=float(
                    raw.get("cycle_baseline_pnl_usd", 0.0)
                ),
                pause_until=(
                    str(raw["pause_until"]) if raw.get("pause_until") else None
                ),
                recovery_shadow_until=(
                    str(raw["recovery_shadow_until"])
                    if raw.get("recovery_shadow_until")
                    else None
                ),
                last_weight_update_at=(
                    str(raw["last_weight_update_at"])
                    if raw.get("last_weight_update_at")
                    else None
                ),
                status=str(raw.get("status") or "monitor"),
                reduction_reason=str(raw.get("reduction_reason") or ""),
            )
        return book
