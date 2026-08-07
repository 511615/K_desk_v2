from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kdesk.domain.historical_funds import build_historical_funds


class HistoricalFundsService:
    """Compose routed read-only facts into a historical funds reconstruction."""

    def __init__(self, legacy_call: Callable[..., Any]):
        self._legacy_call = legacy_call

    def build(self, login: str, filters: dict[str, str] | None = None) -> dict[str, Any]:
        raw = self._legacy_call("account_historical_funds_source_payload", login, filters or {})
        if not raw.get("available"):
            return raw
        replay = build_historical_funds(
            platform=raw.get("platform", ""),
            currency=raw.get("currency", "USD"),
            money_scale=float(raw.get("moneyScale") or 1.0),
            events=raw.get("events", []),
            anchors=raw.get("anchors", []),
            current_anchor=raw.get("currentAnchor"),
        )
        return {
            "available": True,
            "account": raw.get("account", login),
            "platform": raw.get("platform", ""),
            "server": raw.get("server", ""),
            "source": raw.get("source", ""),
            "currency": raw.get("currency", "USD"),
            "coverage": raw.get("coverage", {}),
            **replay,
        }
