from __future__ import annotations

from pathlib import Path

from kdesk.infrastructure.kuzu_risk_graph import KuzuRiskGraphRepository


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
