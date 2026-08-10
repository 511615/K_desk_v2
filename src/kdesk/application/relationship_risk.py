from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from kdesk.application.relationship_network import AccountRelationshipNetworkService
from kdesk.domain.relationship_propagation import propagate_scores

ProjectionScorer = Callable[[list[dict[str, Any]], list[dict[str, Any]], float], dict[str, Any]]
SharedIpLookup = Callable[[str, dict[str, str]], dict[str, Any]]
ToxicLookup = Callable[[str, dict[str, str]], dict[str, Any]]

MAX_ACCOUNT_EXPANSIONS = 100
MAX_DISCOVERY_SECONDS = 12.0
MAX_TOXIC_CHECKS = 2
BUILTIN_RELATION_TYPES = [
    {"id": "toxic_sync_same", "label": "Toxic 同向同步开平仓"},
    {"id": "toxic_sync_opposite", "label": "Toxic 反向同步开平仓"},
]


class AccountRelationshipRiskService:
    """Replace the legacy fact graph response with a Kuzu-scored investigation graph."""

    def __init__(
        self,
        evidence_network: AccountRelationshipNetworkService,
        projection_scorer: ProjectionScorer,
        shared_ip_lookup: SharedIpLookup,
        toxic_lookup: ToxicLookup | None = None,
    ) -> None:
        self._evidence_network = evidence_network
        self._projection_scorer = projection_scorer
        self._shared_ip_lookup = shared_ip_lookup
        self._toxic_lookup = toxic_lookup

    def build(self, login: str, filters: dict[str, str], threshold: float, *, include_toxic: bool = False) -> dict[str, Any]:
        pending: dict[str, dict[str, str]] = {self._account_key(login, filters): dict(filters)}
        visited: set[str] = set()
        entities: dict[str, dict[str, Any]] = {}
        relationships: dict[str, dict[str, Any]] = {}
        coverage: list[dict[str, str]] = []
        relation_types: list[dict[str, str]] = []
        latest_scored: dict[str, Any] | None = None
        toxic_checks = 0
        query_budget_exhausted = False
        root_key = self._account_key(login, filters)
        deadline = time.monotonic() + MAX_DISCOVERY_SECONDS
        while pending and len(visited) < MAX_ACCOUNT_EXPANSIONS:
            if time.monotonic() >= deadline:
                query_budget_exhausted = True
                coverage.append({
                    "source": "relationshipDiscovery", "status": "partial",
                    "reason": f"已达到 {MAX_DISCOVERY_SECONDS:g} 秒查询预算", "account": "",
                })
                break
            account_key, account_filters = next(iter(pending.items()))
            pending.pop(account_key)
            if account_key in visited:
                continue
            visited.add(account_key)
            account_login = account_key.split("|", 1)[0].removeprefix("account:")
            evidence = self._evidence_network.build(account_login, account_filters)
            if not relation_types:
                relation_types = list(evidence["relationTypes"])
                relation_types.extend(BUILTIN_RELATION_TYPES)
            self._merge_evidence(evidence, entities, relationships)
            if account_key in entities:
                entities[account_key]["isSubject"] = account_key == self._account_key(login, filters)
            coverage.extend({**item, "account": account_login} for item in evidence["coverage"])
            try:
                shared_ip = self._shared_ip_lookup(account_login, account_filters)
                self._merge_shared_ip(account_key, shared_ip, entities, relationships)
                coverage.extend({**item, "account": account_login} for item in shared_ip.get("coverage", []))
            except Exception as exc:
                coverage.append({"source": "sharedLastIp", "status": "failed", "reason": str(exc), "account": account_login})
            current_score = 100.0 if account_key == root_key else self._node_score(latest_scored, account_key)
            if include_toxic and self._toxic_lookup and current_score >= 30 and toxic_checks < MAX_TOXIC_CHECKS:
                toxic_checks += 1
                try:
                    toxic = self._toxic_lookup(account_login, account_filters)
                    self._merge_toxic(account_key, toxic, entities, relationships)
                    coverage.extend({**item, "account": account_login} for item in toxic.get("coverage", []))
                except Exception as exc:
                    coverage.append({"source": "toxicSync", "status": "failed", "reason": str(exc), "account": account_login})
            if root_key not in entities:
                raise RuntimeError("问题账户未能写入关系投影")
            # Kuzu is deliberately materialized once, after discovery. Rebuilding an on-disk
            # graph after every hop turns a broad account cluster into a memory/CPU amplifier.
            latest_scored = propagate_scores(list(entities.values()), list(relationships.values()), threshold=threshold)
            for entity in latest_scored["entities"]:
                if entity.get("type") != "account" or not entity.get("expandable"):
                    continue
                candidate_key = str(entity["id"])
                if candidate_key not in visited and candidate_key not in pending:
                    pending[candidate_key] = {
                        "platform": str(entity.get("platform") or ""),
                        "server": str(entity.get("server") or ""),
                        "symbol": "",
                        "start": "",
                        "end": "",
                    }
        if latest_scored is None:
            raise RuntimeError("关系图没有可用的账户证据")
        scored = self._projection_scorer(list(entities.values()), list(relationships.values()), threshold)
        discovery_truncated = bool(pending)
        scored["truncated"] = bool(scored.get("truncated")) or discovery_truncated
        scored["summary"]["discoveryAccountCount"] = len(visited)
        labels = {item["id"]: item["label"] for item in relation_types}
        for relationship in scored["relationships"]:
            relationship["typeLabel"] = labels.get(relationship["type"], relationship["type"])
        scored["summary"]["evidenceCount"] = sum(len(item.get("evidence", [])) for item in scored["relationships"])
        failed = [item for item in coverage if item["status"] == "failed"]
        return {
            "ok": True,
            "account": login,
            "filters": dict(filters),
            "relationTypes": relation_types,
            "coverage": coverage,
            "limitations": [
                "关系图按调查优先级扩散；分数用于排序和决定是否继续读取下一层，不是违规或欺诈结论。",
                f"已实际扩展 {len(visited)} 个达到阈值的账户；队列剩余 {len(pending)} 个。当前已接入 CRM、同服务器 LastIP、EA、跟单、返佣和 Toxic 同步订单边。",
                f"Toxic 全平台同步订单检查已执行 {toxic_checks} 次；仅检查调查分数不低于 30 的账户，单次请求最多 {MAX_TOXIC_CHECKS} 次，避免对低分外围节点进行无界全库扫描。",
                f"本次关系发现查询预算为 {MAX_DISCOVERY_SECONDS:g} 秒；超过预算时返回已完成的部分图谱，不会无限等待。" if query_budget_exhausted else "本次关系发现查询在预算内完成。",
                *[
                    f"{item['source']} 查询失败：{item['reason']}"
                    for item in failed
                    if item["reason"]
                ],
            ],
            "discoveryTruncated": discovery_truncated,
            "queryBudgetExhausted": query_budget_exhausted,
            **scored,
        }

    @staticmethod
    def _account_key(login: str, filters: dict[str, str]) -> str:
        return "account:" + "|".join((str(login), str(filters.get("platform") or ""), str(filters.get("server") or "")))

    def _merge_evidence(self, evidence: dict[str, Any], entities: dict[str, dict[str, Any]], relationships: dict[str, dict[str, Any]]) -> None:
        id_map: dict[str, str] = {}
        for entity in evidence["entities"]:
            entity_id = self._entity_key(entity)
            id_map[str(entity["id"])] = entity_id
            entities.setdefault(entity_id, {**entity, "id": entity_id, "isSubject": False})
        for relationship in evidence["relationships"]:
            source = id_map.get(str(relationship["source"]))
            target = id_map.get(str(relationship["target"]))
            if not source or not target:
                continue
            edge_id = "|".join((str(relationship["type"]), source, target, str(relationship["label"])))
            relationships.setdefault(edge_id, {**relationship, "id": edge_id, "source": source, "target": target})

    @staticmethod
    def _entity_key(entity: dict[str, Any]) -> str:
        return ":".join((str(entity.get("type") or "unknown"), "|".join((str(entity.get("label") or ""), str(entity.get("platform") or ""), str(entity.get("server") or "")))))

    @staticmethod
    def _node_score(scored: dict[str, Any] | None, entity_id: str) -> float:
        if not scored:
            return 0.0
        for entity in scored.get("entities", []):
            if str(entity.get("id")) == entity_id:
                return float(entity.get("score") or 0)
        return 0.0

    def _merge_shared_ip(self, account_key: str, payload: dict[str, Any], entities: dict[str, dict[str, Any]], relationships: dict[str, dict[str, Any]]) -> None:
        for row in payload.get("peers", []):
            peer = {"type": "account", "label": str(row["account"]), "platform": str(row.get("platform") or ""), "server": str(row.get("server") or ""), "detail": "同当前 LastIP", "isSubject": False}
            peer_id = self._entity_key(peer)
            entities.setdefault(peer_id, {**peer, "id": peer_id})
            edge_id = "|".join(("login_ip", account_key, peer_id, str(row.get("ip") or "")))
            relationships.setdefault(edge_id, {
                "id": edge_id, "source": account_key, "target": peer_id, "type": "login_ip", "label": "同当前 LastIP",
                "evidence": [f"LastIP：{row.get('ip')}", f"最后访问：{row.get('lastAccessAt') or '-'}"],
            })

    def _merge_toxic(self, account_key: str, payload: dict[str, Any], entities: dict[str, dict[str, Any]], relationships: dict[str, dict[str, Any]]) -> None:
        for row in payload.get("matches", []):
            account = str(row.get("account") or "")
            if not account:
                continue
            peer = {
                "type": "account", "label": account,
                "platform": str(row.get("platform") or ""), "server": str(row.get("server") or ""),
                "detail": "Toxic 同步开平仓", "isSubject": False,
            }
            peer_id = self._entity_key(peer)
            entities.setdefault(peer_id, {**peer, "id": peer_id})
            opposite = str(row.get("relation") or "").lower() == "opposite"
            relation_type = "toxic_sync_opposite" if opposite else "toxic_sync_same"
            label = "Toxic 反向同步开平仓" if opposite else "Toxic 同向同步开平仓"
            evidence = [
                f"品种：{row.get('symbol') or '-'}",
                f"目标订单：{row.get('targetOrderId') or '-'}；关联订单：{row.get('orderId') or '-'}",
                f"开仓差 {self._seconds(row.get('openDeltaSeconds'))}；平仓差 {self._seconds(row.get('closeDeltaSeconds'))}",
            ]
            if row.get("lotSimilarityPct") not in (None, ""):
                evidence.append(f"手数相似度：{row['lotSimilarityPct']}%")
            edge_id = "|".join((relation_type, account_key, peer_id, str(row.get("targetOrderId") or ""), str(row.get("orderId") or "")))
            relationships.setdefault(edge_id, {
                "id": edge_id, "source": account_key, "target": peer_id, "type": relation_type,
                "label": label, "evidence": evidence,
            })

    @staticmethod
    def _seconds(value: Any) -> str:
        try:
            return f"{float(value):g}s"
        except (TypeError, ValueError):
            return "-"
