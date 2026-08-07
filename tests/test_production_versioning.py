from __future__ import annotations

from pathlib import Path

from kdesk.settings import Settings


def test_frontend_dist_can_be_pinned_to_a_versioned_release(monkeypatch, tmp_path: Path) -> None:
    release = tmp_path / "runtime" / "prod" / "frontend-releases" / "abc123"
    monkeypatch.setenv("KDESK_V2_ROOT", str(tmp_path))
    monkeypatch.setenv("KDESK_FRONTEND_DIST", str(release))

    assert Settings.load().frontend_dist == release.resolve()


def test_production_launcher_requires_main_clean_and_versioned_frontend() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_prod.ps1").read_text(encoding="utf-8")

    assert 'if ($branch -ne "main")' in launcher
    assert "git -C $Root status --porcelain" in launcher
    assert "frontend-releases" in launcher
    assert "$env:KDESK_FRONTEND_DIST" in launcher
