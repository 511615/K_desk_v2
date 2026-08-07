from __future__ import annotations

import gc
import json
from pathlib import Path
from typing import Any

import kuzu


class KuzuRelationshipDemoRepository:
    """Read a bounded evidence graph from an operator-created local Kuzu file."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def graph(self, depth: int) -> dict[str, Any]:
        if depth not in {1, 2, 3}:
            raise ValueError("depth must be between 1 and 3")
        if not self._database_path.is_file():
            raise FileNotFoundError("Kuzu demo graph is unavailable")

        database = kuzu.Database(str(self._database_path), read_only=True)
        connection = kuzu.Connection(database)
        try:
            subject_rows = self._rows(
                connection,
                "MATCH (subject:Entity) WHERE subject.subject = true RETURN subject.id, subject.label LIMIT 1",
            )
            if not subject_rows:
                raise ValueError("Kuzu demo graph has no subject")
            subject_id, subject_label = subject_rows[0]
            peer_rows = self._rows(
                connection,
                f"MATCH (subject:Entity)-[:Evidence*1..{depth}]->(peer:Entity) "
                "WHERE subject.id = $subject_id RETURN DISTINCT peer.id",
                {"subject_id": subject_id},
            )
            visible_ids = {str(subject_id), *(str(row[0]) for row in peer_rows)}
            entities = [
                {
                    "id": str(row[0]),
                    "type": str(row[1]),
                    "label": str(row[2]),
                    "platform": str(row[3] or ""),
                    "server": str(row[4] or ""),
                    "detail": str(row[5] or ""),
                    "isSubject": bool(row[6]),
                }
                for row in self._rows(
                    connection,
                    "MATCH (entity:Entity) "
                    "RETURN entity.id, entity.kind, entity.label, entity.platform, entity.server, entity.detail, entity.subject",
                )
                if str(row[0]) in visible_ids
            ]
            relationships = [
                {
                    "id": str(row[2]),
                    "type": str(row[3]),
                    "label": str(row[4]),
                    "source": str(row[0]),
                    "target": str(row[1]),
                    "evidence": self._evidence(row[5]),
                }
                for row in self._rows(
                    connection,
                    "MATCH (source:Entity)-[edge:Evidence]->(target:Entity) "
                    "RETURN source.id, target.id, edge.id, edge.kind, edge.label, edge.evidence",
                )
                if str(row[0]) in visible_ids and str(row[1]) in visible_ids
            ]
        finally:
            connection.close()
            del connection
            del database
            gc.collect()

        return {
            "source": "kuzu-local-cache",
            "account": str(subject_label),
            "depth": depth,
            "entities": entities,
            "relationships": relationships,
            "summary": {"entityCount": len(entities), "relationshipCount": len(relationships)},
        }

    @staticmethod
    def _rows(connection: kuzu.Connection, query: str, parameters: dict[str, str] | None = None) -> list[list[Any]]:
        result = connection.execute(query, parameters or {})
        rows: list[list[Any]] = []
        while result.has_next():
            rows.append(result.get_next())
        return rows

    @staticmethod
    def _evidence(value: Any) -> list[str]:
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return []
        return [str(item) for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []
