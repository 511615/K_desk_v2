from __future__ import annotations

from typing import Any, Mapping


DEFAULT_MANUAL_CONTROLS = {
    "equity_floor_enabled": True,
    "daily_loss_enabled": True,
    "cycle_loss_enabled": True,
    "auto_trading_enabled": True,
    "resume_requested": False,
}


def normalize_manual_controls(payload: Mapping[str, Any] | None) -> dict[str, bool]:
    source = payload if isinstance(payload, Mapping) else {}
    return {
        key: value if isinstance((value := source.get(key)), bool) else default
        for key, default in DEFAULT_MANUAL_CONTROLS.items()
    }
