from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kdesk_governance", ROOT / "scripts" / "governance.py")
assert SPEC and SPEC.loader
governance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


def test_feature_registry_is_complete_and_current() -> None:
    registry = governance.build_registry()
    governance.write_or_check(governance.REGISTRY_PATH, registry, check=True)
    assert len(registry["features"]) >= 10
    assert len({item["feature_id"] for item in registry["features"]}) == len(registry["features"])


def test_change_records_reference_existing_features() -> None:
    registry = governance.build_registry()
    feature_ids = {item["feature_id"] for item in registry["features"]}
    for document in governance.change_documents():
        assert governance.REQUIRED_CHANGE_FIELDS <= document.metadata.keys()
        assert set(document.metadata["features"]) <= feature_ids
        assert not governance.validate_sections(document, governance.REQUIRED_CHANGE_SECTIONS)


def test_openapi_snapshots_are_current() -> None:
    for name, payload in governance.openapi_payloads().items():
        governance.write_or_check(governance.OPENAPI_DIR / name, payload, check=True)


def test_feature_documents_map_to_real_code_and_tests() -> None:
    for feature in governance.build_registry()["features"]:
        for path in feature["code"] + feature["tests"]:
            assert (ROOT / path).exists(), f"{feature['feature_id']} references missing path {path}"
