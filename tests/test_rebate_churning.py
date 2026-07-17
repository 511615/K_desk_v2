from __future__ import annotations

import importlib.util
from pathlib import Path


def load_rebate_module():
    path = Path(__file__).resolve().parents[1] / "legacy" / "apps" / "problem_account_registry" / "rebate_churning.py"
    spec = importlib.util.spec_from_file_location("kdesk_test_rebate_churning", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_route_code_accepts_v2_route_lists() -> None:
    module = load_rebate_module()
    source = {
        "crm_routes": [
            {"schema": "crm_cn", "mt_server_code": "10"},
            {"schema": "crm_vn", "mt_server_code": "11"},
        ]
    }

    assert module._source_route_code(source, "crm_cn") == "10"
    assert module._source_route_code(source, "crm_vn") == "11"
    assert module._source_route_code(source, "missing") == ""


def test_source_route_code_keeps_legacy_route_dict_support() -> None:
    module = load_rebate_module()
    source = {"crm_routes": {"crm_cn": "10"}}

    assert module._source_route_code(source, "crm_cn") == "10"
