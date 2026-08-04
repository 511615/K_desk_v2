from __future__ import annotations

from copy_manual_controls import DEFAULT_MANUAL_CONTROLS, normalize_manual_controls


def test_defaults_keep_all_protections_enabled() -> None:
    controls = normalize_manual_controls({})

    assert controls == DEFAULT_MANUAL_CONTROLS
    assert controls["equity_floor_enabled"] is True
    assert controls["daily_loss_enabled"] is True
    assert controls["cycle_loss_enabled"] is True
    assert controls["auto_trading_enabled"] is True
    assert controls["resume_requested"] is False


def test_operator_can_disable_limits_and_request_recovery() -> None:
    controls = normalize_manual_controls(
        {
            "equity_floor_enabled": False,
            "daily_loss_enabled": False,
            "cycle_loss_enabled": True,
            "auto_trading_enabled": False,
            "resume_requested": True,
        }
    )

    assert controls == {
        "equity_floor_enabled": False,
        "daily_loss_enabled": False,
        "cycle_loss_enabled": True,
        "auto_trading_enabled": False,
        "resume_requested": True,
    }


def test_invalid_values_fail_closed_to_defaults() -> None:
    controls = normalize_manual_controls(
        {
            "equity_floor_enabled": "false",
            "daily_loss_enabled": 0,
            "cycle_loss_enabled": None,
            "auto_trading_enabled": "true",
            "resume_requested": 1,
        }
    )

    assert controls == DEFAULT_MANUAL_CONTROLS
