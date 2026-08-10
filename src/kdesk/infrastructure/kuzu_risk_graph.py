from __future__ import annotations

import gc
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import kuzu

from kdesk.domain.relationship_propagation import propagate_scores


class KuzuRiskGraphRepository:
    """Read an operator-created account evidence projection and score it in memory."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def graph(self, threshold: float) -> dict[str, Any]:
        if not self._database_path.is_file():
            raise FileNotFoundError("Kuzu risk graph is unavailable")
        database = kuzu.Database(str(self._database_path), read_only=True)
        connection = kuzu.Connection(database)
        try:
            entities = [
                {
                    "id": str(row[0]), "type": str(row[1]), "label": str(row[2]),
                    "platform": str(row[3] or ""), "server": str(row[4] or ""),
                    "detail": str(row[5] or ""), "isSubject": bool(row[6]),
                }
                for row in self._rows(
                    connection,
                    "MATCH (entity:Entity) RETURN entity.id, entity.kind, entity.label, entity.platform, "
                    "entity.server, entity.detail, entity.subject",
                )
            ]
            relationships = [
                {
                    "id": str(row[2]), "source": str(row[0]), "target": str(row[1]),
                    "type": str(row[3]), "label": str(row[4]), "evidence": self._evidence(row[5]),
                }
                for row in self._rows(
                    connection,
                    "MATCH (source:Entity)-[edge:Evidence]->(target:Entity) RETURN source.id, target.id, "
                    "edge.id, edge.kind, edge.label, edge.evidence",
                )
            ]
        finally:
            connection.close()
            del connection
            del database
            gc.collect()

        result = propagate_scores(entities, relationships, threshold=threshold)
        subject = next(entity for entity in result["entities"] if entity["id"] == result["subjectId"])
        return {"source": "kuzu-local-cache", "account": str(subject["label"]), **result}

    def score_projection(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        threshold: float,
    ) -> dict[str, Any]:
        """Materialize request facts in Kuzu, read them back, then release the local projection."""
        with TemporaryDirectory(prefix="kdesk-kuzu-risk-") as temporary_dir:
            database_path = Path(temporary_dir) / "projection.kuzu"
            database = kuzu.Database(str(database_path))
            connection = kuzu.Connection(database)
            try:
                connection.execute(
                    "CREATE NODE TABLE Entity(id STRING, kind STRING, label STRING, platform STRING, server STRING, "
                    "detail STRING, subject BOOL, PRIMARY KEY(id))"
                )
                connection.execute(
                    "CREATE REL TABLE Evidence(FROM Entity TO Entity, id STRING, kind STRING, label STRING, evidence STRING)"
                )
                for entity in entities:
                    connection.execute(
                        "CREATE (:Entity {id: $id, kind: $kind, label: $label, platform: $platform, server: $server, "
                        "detail: $detail, subject: $subject})",
                        {
                            "id": str(entity.get("id") or ""),
                            "kind": str(entity.get("type") or ""),
                            "label": str(entity.get("label") or ""),
                            "platform": str(entity.get("platform") or ""),
                            "server": str(entity.get("server") or ""),
                            "detail": str(entity.get("detail") or ""),
                            "subject": bool(entity.get("isSubject")),
                        },
                    )
                for relationship in relationships:
                    connection.execute(
                        "MATCH (source:Entity), (target:Entity) WHERE source.id = $source AND target.id = $target "
                        "CREATE (source)-[:Evidence {id: $id, kind: $kind, label: $label, evidence: $evidence}]->(target)",
                        {
                            "source": str(relationship.get("source") or ""),
                            "target": str(relationship.get("target") or ""),
                            "id": str(relationship.get("id") or ""),
                            "kind": str(relationship.get("type") or "unknown"),
                            "label": str(relationship.get("label") or relationship.get("type") or "关联证据"),
                            "evidence": json.dumps(list(relationship.get("evidence") or []), ensure_ascii=False),
                        },
                    )
                projected_entities = self._read_entities(connection)
                projected_relationships = self._read_relationships(connection)
            finally:
                connection.close()
                del connection
                del database
                gc.collect()
        result = propagate_scores(projected_entities, projected_relationships, threshold=threshold)
        subject = next(entity for entity in result["entities"] if entity["id"] == result["subjectId"])
        return {"source": "kuzu-request-projection", "account": str(subject["label"]), **result}

    @staticmethod
    def _rows(connection: kuzu.Connection, query: str) -> list[list[Any]]:
        result = connection.execute(query)
        rows: list[list[Any]] = []
        while result.has_next():
            rows.append(result.get_next())
        return rows

    def _read_entities(self, connection: kuzu.Connection) -> list[dict[str, Any]]:
        return [
            {
                "id": str(row[0]), "type": str(row[1]), "label": str(row[2]),
                "platform": str(row[3] or ""), "server": str(row[4] or ""),
                "detail": str(row[5] or ""), "isSubject": bool(row[6]),
            }
            for row in self._rows(
                connection,
                "MATCH (entity:Entity) RETURN entity.id, entity.kind, entity.label, entity.platform, "
                "entity.server, entity.detail, entity.subject",
            )
        ]

    def _read_relationships(self, connection: kuzu.Connection) -> list[dict[str, Any]]:
        return [
            {
                "id": str(row[2]), "source": str(row[0]), "target": str(row[1]),
                "type": str(row[3]), "label": str(row[4]), "evidence": self._evidence(row[5]),
            }
            for row in self._rows(
                connection,
                "MATCH (source:Entity)-[edge:Evidence]->(target:Entity) RETURN source.id, target.id, "
                "edge.id, edge.kind, edge.label, edge.evidence",
            )
        ]

    @staticmethod
    def _evidence(value: Any) -> list[str]:
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item)[:500] for item in parsed if isinstance(item, str)][:20]
