from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from kdesk import __version__
from kdesk.settings import Settings

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _git_sha(root: Path) -> str:
    configured = os.environ.get("KDESK_GIT_SHA", "").strip()
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _schema_revision(database_path: Path) -> str:
    if not database_path.is_file():
        return "uninitialized"
    try:
        with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True, timeout=2) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
    except sqlite3.Error:
        return "unversioned"
    return str(row[0]) if row else "unversioned"


def _registry(root: Path) -> tuple[str, int]:
    try:
        payload = json.loads((root / "docs" / "feature-registry.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unavailable", 0
    return str(payload.get("registryVersion") or "unavailable"), len(payload.get("features") or [])


def build_metadata(settings: Settings) -> dict:
    registry_version, feature_count = _registry(SOURCE_ROOT)
    return {
        "version": __version__,
        "gitSha": _git_sha(SOURCE_ROOT),
        "buildTime": os.environ.get("KDESK_BUILD_TIME", "").strip() or datetime.now(UTC).isoformat(),
        "schemaRevision": _schema_revision(settings.database_path),
        "featureRegistryVersion": registry_version,
        "featureCount": feature_count,
        "compatibilityLevel": "legacy-account-v1",
    }
