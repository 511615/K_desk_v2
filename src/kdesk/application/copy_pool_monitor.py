from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class CopyPoolSnapshotRepository(Protocol):
    def dashboard(self, *, timeline_limit: int, event_limit: int, order_limit: int) -> dict[str, Any]: ...

    def account_target(self, alias: str) -> str | None: ...


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
