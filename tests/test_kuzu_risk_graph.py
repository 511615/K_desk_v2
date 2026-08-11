from __future__ import annotations

import time
from pathlib import Path

import pytest

from kdesk.infrastructure.kuzu_risk_graph import KuzuRiskGraphRepository


def _slow_kuzu_worker(*_args: object) -> None:
    time.sleep(1)


def test_kuzu_risk_repository_materializes_and_reads_a_request_scoped_projection(tmp_path: Path) -> None:
    repository = KuzuRiskGraphRepository(tmp_path / "unused.kuzu")

    result = repository.score_projection(
        [
            {"id": "account:seed", "type": "account", "label": "639549", "isSubject": True},
            {"id": "account:peer", "type": "account", "label": "639550", "isSubject": False},
        ],
        [{"id": "ip-1", "source": "account:seed", "target": "account:peer", "type": "login_ip", "label": "同 LastIP"}],
        threshold=12,
    )

    assert result["source"] == "kuzu-request-projection"
    assert result["summary"]["entityCount"] == 2
    assert result["relationships"][0]["type"] == "login_ip"


def test_kuzu_risk_repository_hard_stops_a_timed_out_child(tmp_path: Path) -> None:
    repository = KuzuRiskGraphRepository(
        tmp_path / "unused.kuzu",
        timeout_seconds=0.01,
        worker_target=_slow_kuzu_worker,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        repository.score_projection([], [], threshold=12)
