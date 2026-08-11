from __future__ import annotations

import gc
import json
import multiprocessing
from pathlib import Path
from queue import Empty
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from typing import Any

import kuzu

from kdesk.domain.relationship_propagation import propagate_scores

DEFAULT_KUZU_TIMEOUT_SECONDS = 4.0


def _kuzu_worker(result_queue: Any, database_path: str, operation: str, payload: dict[str, Any]) -> None:
    """Run native Kuzu work outside the account-service process.

    Kuzu may retain native allocations after a request even after Python references are released. A
    short-lived child gives Windows ownership of those allocations and guarantees that the account
    service can reclaim them when the child exits or is terminated.
    """
    try:
        repository = KuzuRiskGraphRepository(Path(database_path))
        if operation == "graph":
            result = repository._graph_in_process(float(payload["threshold"]))
        elif operation == "score_projection":
            result = repository._score_projection_in_process(
                list(payload["entities"]), list(payload["relationships"]), float(payload["threshold"]),
            )
        else:
            raise ValueError("unsupported Kuzu operation")
        result_queue.put(("ok", result))
    except FileNotFoundError as exc:
        result_queue.put(("file_not_found", str(exc)))
    except Exception:
        result_queue.put(("error", "Kuzu request projection failed"))


class KuzuRiskGraphRepository:
    """Run request-scoped Kuzu work in one bounded child process at a time."""

    def __init__(
        self,
        database_path: Path,
        *,
        timeout_seconds: float = DEFAULT_KUZU_TIMEOUT_SECONDS,
        worker_target: Any = _kuzu_worker,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Kuzu timeout must be positive")
        self._database_path = database_path
        self._timeout_seconds = timeout_seconds
        self._worker_target = worker_target
        self._gate = BoundedSemaphore(1)

    def graph(self, threshold: float) -> dict[str, Any]:
        return self._run_isolated("graph", {"threshold": threshold})

    def _graph_in_process(self, threshold: float) -> dict[str, Any]:
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
        return self._run_isolated(
            "score_projection",
            {"entities": entities, "relationships": relationships, "threshold": threshold},
        )

    def _score_projection_in_process(
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

    def _run_isolated(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._gate.acquire(blocking=False):
            raise RuntimeError("Kuzu projection is busy; existing account evidence will be returned")
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=self._worker_target,
            args=(result_queue, str(self._database_path), operation, payload),
            daemon=True,
        )
        try:
            process.start()
            try:
                kind, value = result_queue.get(timeout=self._timeout_seconds)
            except Empty:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
                raise RuntimeError(f"Kuzu projection timed out after {self._timeout_seconds:g} seconds") from None
            process.join(timeout=0.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if kind == "ok" and isinstance(value, dict):
                return value
            if kind == "file_not_found":
                raise FileNotFoundError(str(value))
            raise RuntimeError(str(value) or "Kuzu request projection failed")
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            result_queue.close()
            result_queue.join_thread()
            self._gate.release()

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
