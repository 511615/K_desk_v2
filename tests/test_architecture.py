from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kdesk_governance_architecture", ROOT / "scripts" / "governance.py")
assert SPEC and SPEC.loader
governance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


def test_legacy_import_boundary_and_mt_read_only_rule() -> None:
    governance.validate_architecture()


def test_domain_does_not_import_outer_layers() -> None:
    forbidden = ("fastapi", "sqlalchemy", "pymysql", "MetaTrader5", "kdesk.infrastructure", "kdesk.api")
    for path in (ROOT / "src" / "kdesk" / "domain").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), f"outer dependency in {path}"
