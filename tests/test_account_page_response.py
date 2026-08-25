from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kdesk.api.account_app import create_account_app
from kdesk.infrastructure.legacy_bridge import LegacyBridge
from kdesk.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    runtime = tmp_path / "runtime"
    return Settings(
        root=tmp_path, profile="test", host="127.0.0.1", account_port=8877, kline_port=8866,
        runtime_dir=runtime, database_path=runtime / "kdesk.sqlite", queue_database_path=runtime / "jobs.sqlite",
        artifact_dir=runtime / "artifacts", upload_dir=runtime / "uploads", log_dir=runtime / "logs",
        legacy_root=tmp_path / "legacy", legacy_output=tmp_path / "legacy_output",
        legacy_trade_database=tmp_path / "trades.sqlite", bootstrap_xlsx=runtime / "import" / "problematic_accounts.xlsx",
        legacy_compat_dir=runtime / "legacy_compat", frontend_dist=tmp_path / "frontend" / "dist", ui_mode="vue",
    )


def test_account_detail_revalidates_the_embedded_kline_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(LegacyBridge, "account_page", lambda _self, login: f"<html>{login}</html>")
    app = create_account_app(_settings(tmp_path))

    with TestClient(app) as client:
        response = client.get("/account/302360")

    assert response.headers["cache-control"] == "no-cache, must-revalidate"
