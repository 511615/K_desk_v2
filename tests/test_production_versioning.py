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


def test_account_only_health_check_is_passed_as_a_named_switch() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_prod.ps1").read_text(encoding="utf-8")

    assert "@(& $healthScript -AccountOnly)" in launcher
    assert '$healthArguments += "-AccountOnly"' not in launcher


def test_production_launcher_replaces_a_non_production_listener_before_accepting_the_port() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_prod.ps1").read_text(encoding="utf-8")

    assert "Get-KDeskServiceMetadata" in launcher
    assert '($metadata.profile -ne "prod")' in launcher or 'if ($Port -eq 8777 -and $metadata.profile -ne "prod")' in launcher
    assert "Stop-Process -Id $rootProcess.ProcessId -Force" in launcher
    assert "still unavailable after replacement" in launcher


def test_production_launcher_verifies_listener_owner_and_runtime_database() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_prod.ps1").read_text(encoding="utf-8")

    assert "Get-KDeskSupervisorProcess" in launcher
    assert "Test-KDeskProductionListener" in launcher
    assert "$supervisor.ExecutablePath -ne $Python" in launcher
    assert "$metadata.workerQueue" in launcher
    assert "$metadata.database" in launcher


def test_production_health_check_rejects_a_service_using_another_runtime_queue() -> None:
    root = Path(__file__).resolve().parents[1]
    health_check = (root / "scripts" / "health_check_prod.ps1").read_text(encoding="utf-8")

    assert '$expectedDatabase = Join-Path $Root "runtime\\prod\\kdesk.sqlite"' in health_check
    assert "$response.workerQueue" in health_check
    assert "$response.database" in health_check


def test_production_process_guards_skip_uninspectable_system_processes() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_prod.ps1").read_text(encoding="utf-8")
    health_check = (root / "scripts" / "health_check_prod.ps1").read_text(encoding="utf-8")
    stopper = (root / "scripts" / "stop_prod.ps1").read_text(encoding="utf-8")

    assert "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue" in launcher
    assert "ConvertFrom-Json" in health_check
    assert "runtime\\prod\\workers" in health_check
    assert "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue" in stopper
    assert "Occupant:" in stopper
    assert "ExecutablePath" in stopper
    assert "Get-KDeskSupervisorProcess" in stopper
    assert "Stop-Process -Id $supervisor.ProcessId -Force" in stopper


def test_production_launcher_pins_child_python_imports_to_main_source_tree() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_prod.ps1").read_text(encoding="utf-8")

    assert '$env:PYTHONPATH = Join-Path $Root "src"' in launcher
    assert '$env:PYTHONNOUSERSITE = "1"' in launcher
    assert '"--workers", "1"' not in launcher


def test_worker_runtime_heartbeat_markers_are_used_for_queue_readiness() -> None:
    root = Path(__file__).resolve().parents[1]
    runner = (root / "src" / "kdesk" / "worker" / "runner.py").read_text(encoding="utf-8")
    health_check = (root / "scripts" / "health_check_prod.ps1").read_text(encoding="utf-8")

    assert "worker_marker" in runner
    assert "workers" in runner
    assert "ConvertFrom-Json" in health_check
    assert "runtime\\prod\\workers" in health_check


def test_release_script_is_pinned_to_clean_main_production_root() -> None:
    root = Path(__file__).resolve().parents[1]
    release = (root / "scripts" / "release_prod.ps1").read_text(encoding="utf-8")

    assert "branch --show-current" in release
    assert "Production release requires the main branch" in release
    assert "D:\\risk\\K_desk_v2_main" in release
    assert "Production release requires a clean Git worktree" in release
    assert "SkipGitCleanCheck" not in release
    assert "verify_deployed_release.ps1" in release


def test_deployed_release_verifier_checks_identity_and_graph_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    verifier = (root / "scripts" / "verify_deployed_release.ps1").read_text(encoding="utf-8")

    assert "/api/meta" in verifier
    assert "ExpectedGitSha" in verifier
    assert "ExpectedVersion" in verifier
    assert "ExpectedGitSha).StartsWith" in verifier
    assert "sourceRoot" in verifier
    assert "data-graph-type=\"focus-force\"" in verifier
    assert "graph_type=galaxy" in verifier


def test_dev_promotion_is_fast_forward_only_and_preserves_previous_main() -> None:
    root = Path(__file__).resolve().parents[1]
    promotion = (root / "scripts" / "promote_dev.ps1").read_text(encoding="utf-8")

    assert "D:\\risk\\K_desk_v2_main" in promotion
    assert "D:\\risk\\K_desk_v2_dev" in promotion
    assert "-Mode Full" in promotion
    assert "merge-base" in promotion
    assert "--is-ancestor" in promotion
    assert "'branch', '-f', 'back', $mainSha" in promotion
    assert "'merge', '--ff-only', 'dev'" in promotion
    assert "branch refs/heads/back" in promotion
