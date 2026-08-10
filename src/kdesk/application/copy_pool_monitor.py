from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class CopyPoolSnapshotRepository(Protocol):
    def dashboard(self, *, timeline_limit: int, event_limit: int, order_limit: int) -> dict[str, Any]: ...

    def account_target(self, alias: str) -> str | None: ...

    def update_controls(self, values: dict[str, bool]) -> dict[str, Any]: ...

    def request_recovery(self, *, wait_seconds: float = 10.0) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CopyPoolMonitorService:
    repository: CopyPoolSnapshotRepository

    def dashboard(self, *, timeline_limit: int, event_limit: int, order_limit: int) -> dict[str, Any]:
        return self.repository.dashboard(
            timeline_limit=timeline_limit,
            event_limit=event_limit,
            order_limit=order_limit,
        )

    def account_target(self, alias: str) -> str | None:
        return self.repository.account_target(alias)

    def update_controls(self, values: dict[str, bool]) -> dict[str, Any]:
        return self.repository.update_controls(values)

    def request_recovery(self, *, wait_seconds: float = 10.0) -> dict[str, Any]:
        return self.repository.request_recovery(wait_seconds=wait_seconds)
