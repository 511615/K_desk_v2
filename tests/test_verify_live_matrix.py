from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_live_matrix.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("verify_live_matrix_test_module", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_matrix(monkeypatch: pytest.MonkeyPatch, fixture: Path, finance: dict[str, object]) -> int:
    module = load_script_module()

    def fake_fetch(base_url: str, path: str, query: dict[str, str]) -> dict:
        if path == "/api/account-lookup":
            return {"databases": [{"latestSource": {"server": "AC CN MT4"}}]}
        return {"riskPanels": {"finance": finance}}

    monkeypatch.setattr(module, "fetch", fake_fetch)
    monkeypatch.setattr(sys, "argv", ["verify_live_matrix.py", "--fixture", str(fixture)])
    with pytest.raises(SystemExit) as result:
        module.main()
    return int(result.value.code)


def test_live_matrix_checks_volatile_finance_without_static_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = tmp_path / "matrix.json"
    fixture.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "account": "5002693",
                        "platform": "MT4",
                        "server": "AC CN MT4",
                        "volatileFields": ["balance", "netDeposit", "rebate", "comprehensiveProfit"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert run_matrix(
        monkeypatch,
        fixture,
        {"balance": 500.0, "netDeposit": 1000.0, "rebate": 12.0, "comprehensiveProfit": -488.0},
    ) == 0


def test_live_matrix_rejects_missing_volatile_finance_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = tmp_path / "matrix.json"
    fixture.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "account": "5002693",
                        "platform": "MT4",
                        "server": "AC CN MT4",
                        "volatileFields": ["balance", "netDeposit"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert run_matrix(monkeypatch, fixture, {"balance": 500.0}) == 1
