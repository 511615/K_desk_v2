from __future__ import annotations

import hashlib
import heapq
import re
import threading
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

RULE_VERSION = "account-profile-v1"
PROFILE_THRESHOLDS = {
    "minimum_behavior_orders": 5,
    "minimum_holding_comparison_orders": 10,
    "short_holding_ratio_percent": 50.0,
    "holding_loss_multiple": 2.0,
    "minimum_losing_holding_minutes": 30.0,
}
DIRECTED = {"copy_order", "direct_ib", "ib_direct_account", "ib_owned_account", "ib_identity", "ib_direct_rebate"}
STRENGTH = {
    "same_crm_user": 0.95,
    "login_ip": 0.90,
    "client_id": 0.90,
    "ea_feature": 0.80,
    "copy_order": 0.80,
    "copy_group": 0.75,
    "trade_open_close_sync": 0.78,
    "toxic_sync_same": 0.78,
    "suspected_hedge": 0.82,
    "toxic_sync_opposite": 0.82,
    "rebate": 0.70,
    "ib_direct_rebate": 0.70,
    "direct_ib": 0.60,
    "ib_direct_account": 0.60,
    "ib_owned_account": 0.60,
    "ib_identity": 1.0,
    "same_name": 0.35,
}
PRESENTATION = {
    "same_crm_user": ("同名账户", "这些交易账户归属于同一个客户。", "只说明账户归属一致，不代表交易行为一致。"),
    "same_name": ("同名账户", "账户名称规范化后相同。", "同名仅是调查线索，不能单独确认由同一人控制。"),
    "login_ip": (
        "同 LastIP",
        "账户当前可用的最后登录 IP 快照相同。",
        "数据库只有当前 LastIP，不能还原完整历史登录记录。",
    ),
    "client_id": ("同 CID", "账户当前可用的 CID 快照相同。", "CID 只代表当前可用快照，不单独证明由同一人控制。"),
    "ea_feature": (
        "EA / 路由特征",
        "Comment、ExpertID、Magic 或路由特征存在匹配。",
        "自动化交易线索不单独证明策略完全相同。",
    ),
    "copy_order": (
        "跟单关系",
        "已识别主账户与跟随账户，并存在跟单源、路由或订单映射证据。",
        "方向表示已识别的主从关系。",
    ),
    "copy_group": ("跟单群组", "账户位于同一可解释跟单群组。", "群组关系不代表每两个成员间都有直接跟单。"),
    "trade_open_close_sync": ("开平仓同步", "账户间存在开仓和平仓时间同步线索。", "时间同步线索，不等同于跟单。"),
    "toxic_sync_same": ("开平仓同步", "账户间存在同向开平仓时间同步线索。", "时间同步线索，不等同于跟单。"),
    "suspected_hedge": (
        "疑似对锁",
        "存在相反方向、时间接近且手数相似的重复交易。",
        "调查线索不直接认定违规或恶意对锁。",
    ),
    "toxic_sync_opposite": (
        "疑似对锁",
        "存在相反方向、时间接近且手数相似的重复交易。",
        "调查线索不直接认定违规或恶意对锁。",
    ),
    "rebate": ("返佣关系", "账户之间存在返佣记录或异常返佣收益线索。", "应结合交易盈利和返佣占比判断。"),
    "ib_direct_rebate": (
        "IB 直接返佣",
        "该账户属于指定 IB 的直接返佣人员范围。",
        "仅展示异常返佣或状态达到 P 及以上的账户。",
    ),
    "direct_ib": ("直属 IB", "该客户的直属上级 IB 已识别。", "关系方向为客户到直属 IB。"),
    "ib_direct_account": (
        "直属上级 IB 本人账户",
        "该交易账户归属于直属上级 IB 本人。",
        "不是该 IB 的普通下属客户账户。",
    ),
    "ib_owned_account": ("IB 本人名下账户", "该交易账户归属于指定 IB 本人。", "身份归属不等同返佣上下级。"),
    "ib_identity": ("IB 身份确认", "当前交易账户对应客户具有 IB 身份。", "身份桥只解释 IB 路径。"),
}
SENSITIVE = re.compile(
    r"select\s|from\s|join\s|user_id|mt_users_account|password|api_data|safe_password|phonepassword|身份证|email\s*[=:]",
    re.I,
)
METRIC_LABEL_KEYS = {
    "symbol",
    "direction",
    "openTimeDiffSeconds",
    "closeTimeDiffSeconds",
    "openDeltaSeconds",
    "closeDeltaSeconds",
    "lotSimilarity",
    "volumeSimilarity",
    "matchCount",
    "matchedOrders",
    "orderCount",
    "rebateAmount",
    "rebateRatio",
    "tradeProfit",
    "totalProfit",
    "platform",
    "server",
    "observedAt",
    "start",
    "end",
}
METRIC_LABELS = {
    "symbol": "品种",
    "direction": "方向",
    "openTimeDiffSeconds": "开仓时间差（秒）",
    "closeTimeDiffSeconds": "平仓时间差（秒）",
    "openDeltaSeconds": "开仓时间差（秒）",
    "closeDeltaSeconds": "平仓时间差（秒）",
    "lotSimilarity": "手数相似度",
    "volumeSimilarity": "手数相似度",
    "matchCount": "匹配次数",
    "matchedOrders": "匹配订单数",
    "orderCount": "订单数",
    "rebateAmount": "返佣金额",
    "rebateRatio": "返佣占比",
    "tradeProfit": "交易盈利",
    "totalProfit": "综合盈利",
    "platform": "平台",
    "server": "服务器",
    "observedAt": "记录时间",
    "start": "开始时间",
    "end": "结束时间",
}
PROFILE_METRIC_LABELS = {
    "orderCount": "订单样本数",
    "closedOrders": "已平仓订单数",
    "shortCloseOrders": "短平订单数",
    "highFrequencyOrderRatio": "短平占比",
    "shortHoldingRatio": "短平占比",
    "winningAverageHoldingMinutes": "盈利订单平均持仓（分钟）",
    "losingAverageHoldingMinutes": "亏损订单平均持仓（分钟）",
    "longestLosingHoldingMinutes": "最长亏损持仓（分钟）",
    "eventCount": "事件次数",
    "batchCount": "批次数",
    "maxOrdersPerBatch": "单批最大订单数",
    "maxCumulativeLots": "最大累计手数",
    "longRatio": "多单占比",
    "shortRatio": "空单占比",
    "matchedOrders": "匹配订单数",
    "matchedOrderCount": "匹配订单数",
    "groupCount": "匹配群组数",
    "comment": "Comment 归一结果",
    "expertId": "ExpertID",
    "magic": "Magic",
    "matchClue": "匹配线索",
}


def text(value: Any) -> str:
    return str(value or "").strip()


def status(value: Any) -> str:
    return text(value).upper() or "B"


def evidence_key(edge: dict[str, Any]) -> str:
    return text(edge.get("evidenceKey") or edge.get("evidence_id") or edge.get("evidenceId") or edge.get("detail"))


def edge_id(edge: dict[str, Any]) -> str:
    if text(edge.get("id")):
        return text(edge["id"])
    raw = "|".join((text(edge.get("source")), text(edge.get("target")), text(edge.get("type")), evidence_key(edge)))
    return "edge:" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def relation_key(edge: dict[str, Any]) -> str:
    source, target, kind = text(edge.get("source")), text(edge.get("target")), text(edge.get("type"))
    if kind not in DIRECTED:
        source, target = sorted((source, target))
    return "|".join((source, target, kind, evidence_key(edge)))


class RelationshipInspectionService:
    def __init__(self, cache_seconds: float = 600, max_cache_entries: int = 256) -> None:
        self.cache_seconds = cache_seconds
        self.max_cache_entries = max_cache_entries
        self.cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
        self.lock = threading.Lock()

    def build_node_profile(
        self,
        root: str,
        node_id: str,
        snapshot: dict[str, Any],
        risk: dict[str, Any] | None,
        automation: dict[str, Any] | None,
        *,
        start: str = "",
        end: str = "",
    ) -> dict[str, Any]:
        risk, automation = risk or {}, automation or {}
        digest = hashlib.sha1(repr((risk, automation)).encode()).hexdigest()
        cache_key = (root, node_id, snapshot.get("revision"), start, end, RULE_VERSION, digest)
        if cached := self._cached(cache_key):
            return cached
        entities = {text(item.get("id")): item for item in snapshot.get("entities", []) if isinstance(item, dict)}
        node = entities.get(node_id) or next(
            (item for item in entities.values() if text(item.get("label")) == node_id), None
        )
        if not node or text(node.get("type")) != "account":
            raise KeyError("当前调查快照中不存在该账户节点")
        filters = snapshot.get("filters") if isinstance(snapshot.get("filters"), dict) else {}
        account = {
            "login": text(node.get("label")),
            "node_id": text(node.get("id")),
            "platform": text(node.get("platform") or filters.get("platform")),
            "server": text(node.get("server") or filters.get("server")),
            "currency": text(node.get("currency")),
            "database_status": status(node.get("databaseStatus")),
            "score": round(float(node.get("score") or (100 if node.get("isSubject") else 0)), 1),
            "depth": int(node.get("hops") or node.get("depth") or 0),
            "expandable": bool(node.get("expandable", True)),
            "detail_url": self._detail_url(node),
        }
        tags, metrics, limitations = self._profile_tags(node, snapshot, risk, automation)
        failed = [
            item for item in snapshot.get("coverage", []) if isinstance(item, dict) and item.get("status") == "failed"
        ]
        coverage_status = "pending" if snapshot.get("inProgress") else "partial" if failed else "complete"
        limitations += [text(item.get("reason")) for item in failed if text(item.get("reason"))]
        limitations += [text(item) for item in snapshot.get("limitations", []) if text(item)]
        result = {
            "ok": True,
            "rule_version": RULE_VERSION,
            "snapshot_version": snapshot.get("revision", 0),
            "account": account,
            "coverage": {
                "start": start,
                "end": end,
                "status": coverage_status,
                "limitations": list(dict.fromkeys(limitations)),
            },
            "tags": tags,
            "metrics": metrics,
            "recommendations": self._recommendations(node, snapshot, tags),
        }
        return self._store(cache_key, result)

    def build_relation_bundles(self, relationships: Iterable[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(relationships, dict):
            relationships = relationships.get("relationships", [])
        deduped: dict[str, dict[str, Any]] = {}
        for edge in relationships:
            if isinstance(edge, dict) and edge.get("source") and edge.get("target"):
                deduped.setdefault(relation_key(edge), {**edge, "id": edge_id(edge)})
        pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for edge in deduped.values():
            pair = tuple(sorted((text(edge.get("source")), text(edge.get("target")))))
            pairs.setdefault(pair, []).append(edge)
        bundles = []
        for pair, items in sorted(pairs.items()):
            by_type: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                by_type.setdefault(text(item.get("type")), []).append(item)
            relations = [self._merge_same_type(kind, same_type) for kind, same_type in sorted(by_type.items())]
            bundles.append(
                {
                    "id": "bundle:" + hashlib.sha1("|".join(pair).encode()).hexdigest()[:16],
                    "endpoints": list(pair),
                    "endpoint_ids": list(pair),
                    "relation_count": len(relations),
                    "relations": relations,
                }
            )
        return bundles

    @staticmethod
    def _merge_same_type(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = sorted(items, key=edge_id)
        merged = dict(ordered[0])
        merged["type"] = kind
        merged["edge_ids"] = [edge_id(item) for item in ordered]
        merged["evidence_keys"] = list(dict.fromkeys(evidence_key(item) for item in ordered if evidence_key(item)))
        merged["evidence"] = [
            evidence for item in ordered for evidence in RelationshipInspectionService._evidence(item)
        ]
        metrics: dict[str, Any] = {}
        for item in ordered:
            if isinstance(item.get("metrics"), dict):
                metrics.update(item["metrics"])
        merged["metrics"] = metrics
        return merged

    def build_relation_detail(
        self, requested_id: str, snapshot: dict[str, Any], *, detail_page: int = 1, detail_limit: int = 50
    ) -> dict[str, Any]:
        if detail_page < 1 or not 1 <= detail_limit <= 200:
            raise ValueError("证据分页参数无效")
        edges = [item for item in snapshot.get("relationships", []) if isinstance(item, dict)]
        bundles = self.build_relation_bundles(edges)
        bundle = next((item for item in bundles if item["id"] == requested_id), None)
        selected = None
        if bundle is None:
            selected = next((item for item in edges if edge_id(item) == requested_id), None)
            if selected is None:
                raise KeyError("当前调查快照中不存在该关系")
            endpoints = {text(selected.get("source")), text(selected.get("target"))}
            bundle = next(item for item in bundles if set(item["endpoints"]) == endpoints)
        ordered = list(bundle["relations"])
        if selected:
            ordered.sort(key=lambda item: edge_id(item) != edge_id(selected))
        entities = {text(item.get("id")): item for item in snapshot.get("entities", []) if isinstance(item, dict)}
        relations = [self._relation(item, entities, detail_page, detail_limit) for item in ordered]
        filters = snapshot.get("filters") if isinstance(snapshot.get("filters"), dict) else {}
        for relation in relations:
            relation["time_range"]["start"] = relation["time_range"]["start"] or text(filters.get("start"))
            relation["time_range"]["end"] = relation["time_range"]["end"] or text(filters.get("end"))
        failed = [
            item for item in snapshot.get("coverage", []) if isinstance(item, dict) and item.get("status") == "failed"
        ]
        return {
            "ok": True,
            "edge_id": bundle["id"],
            "snapshot_version": snapshot.get("revision", 0),
            "rule_version": RULE_VERSION,
            "relation_count": len(ordered),
            "source": self._endpoint(entities.get(bundle["endpoints"][0]), bundle["endpoints"][0]),
            "target": self._endpoint(entities.get(bundle["endpoints"][1]), bundle["endpoints"][1]),
            "relations": relations,
            "coverage": {
                "status": "pending" if snapshot.get("inProgress") else "partial" if failed else "complete",
                "limitations": list(
                    dict.fromkeys(
                        [text(item) for item in snapshot.get("limitations", []) if text(item)]
                        + [text(item.get("reason")) for item in failed if text(item.get("reason"))]
                    )
                ),
            },
        }

    def _profile_tags(
        self, node: dict[str, Any], snapshot: dict[str, Any], risk: dict[str, Any], automation: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
        tags = [{"name": status(node.get("databaseStatus")), "family": "status", "metrics": {}}]
        for key, name in (("ea", "EA"), ("copy", "跟单")):
            value = automation.get(key)
            if isinstance(value, dict) and value.get("detected"):
                tags.append({"name": name, "family": "automation", "metrics": self._safe_profile_metrics(value)})
        panels = risk.get("riskPanels") if isinstance(risk.get("riskPanels"), dict) else {}
        behavior = panels.get("highFrequency") if isinstance(panels.get("highFrequency"), dict) else {}
        if not behavior and isinstance(risk.get("tradeBehavior"), dict):
            behavior = risk["tradeBehavior"]
        orders = int(behavior.get("orderCount") or behavior.get("closedOrders") or 0)
        minimum_orders = int(PROFILE_THRESHOLDS["minimum_behavior_orders"])
        metrics = {
            "behavior_status": "insufficient" if orders < minimum_orders else "available",
            "behavior": self._safe_profile_metrics(behavior),
        }
        limitations = [] if orders >= minimum_orders else ["交易行为样本不足，未生成短平、扛单等行为标签。"]
        if orders >= minimum_orders:
            short_ratio = float(behavior.get("highFrequencyOrderRatio") or behavior.get("shortHoldingRatio") or 0)
            if not short_ratio:
                short_ratio = float(behavior.get("shortCloseOrders") or 0) / orders * 100
            if short_ratio >= PROFILE_THRESHOLDS["short_holding_ratio_percent"]:
                tags.append(
                    {
                        "name": "短平",
                        "family": "behavior",
                        "metrics": {"订单样本数": orders, "短平占比": round(short_ratio, 2)},
                    }
                )
            win, loss = (
                float(behavior.get("winningAverageHoldingMinutes") or 0),
                float(behavior.get("losingAverageHoldingMinutes") or 0),
            )
            if orders >= PROFILE_THRESHOLDS["minimum_holding_comparison_orders"] and loss >= max(
                win * PROFILE_THRESHOLDS["holding_loss_multiple"],
                PROFILE_THRESHOLDS["minimum_losing_holding_minutes"],
            ):
                tags.append(
                    {
                        "name": "扛单",
                        "family": "behavior",
                        "metrics": {
                            "盈利订单平均持仓（分钟）": round(win, 2),
                            "亏损订单平均持仓（分钟）": round(loss, 2),
                            **(
                                {"最长亏损持仓（分钟）": behavior.get("longestLosingHoldingMinutes")}
                                if behavior.get("longestLosingHoldingMinutes") is not None
                                else {}
                            ),
                        },
                    }
                )
            for key, name in (
                ("adverseAveraging", "逆势加仓"),
                ("batchEntry", "批量进场"),
                ("directionConcentration", "方向集中"),
            ):
                if isinstance(behavior.get(key), dict) and behavior[key].get("detected"):
                    tags.append(
                        {"name": name, "family": "behavior", "metrics": self._safe_profile_metrics(behavior[key])}
                    )
        relation_names = {
            "same_crm_user": "同名账户",
            "same_name": "同名账户",
            "login_ip": "同 LastIP",
            "client_id": "同 CID",
            "ea_feature": "EA",
            "copy_order": "跟单",
            "copy_group": "跟单",
            "rebate": "返佣异常",
            "ib_direct_rebate": "返佣异常",
            "direct_ib": "IB 关系",
            "ib_direct_account": "IB 关系",
            "ib_owned_account": "IB 关系",
            "trade_open_close_sync": "开平仓同步",
            "toxic_sync_same": "开平仓同步",
            "suspected_hedge": "疑似对锁",
            "toxic_sync_opposite": "疑似对锁",
        }
        known = {item["name"] for item in tags}
        for edge in snapshot.get("relationships", []):
            if isinstance(edge, dict) and node.get("id") in {edge.get("source"), edge.get("target")}:
                name = relation_names.get(text(edge.get("type")))
                if name and name not in known:
                    tags.append({"name": name, "family": "relationship", "metrics": {}})
                    known.add(name)
        return tags, metrics, limitations

    def _recommendations(
        self, selected: dict[str, Any], snapshot: dict[str, Any], tags: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        entities = {text(item.get("id")): item for item in snapshot.get("entities", []) if isinstance(item, dict)}
        subject = next((item for item in entities.values() if item.get("isSubject")), None)
        if not subject:
            return []
        graph: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for edge in snapshot.get("relationships", []):
            if not isinstance(edge, dict):
                continue
            source, target = text(edge.get("source")), text(edge.get("target"))
            if source and target:
                graph.setdefault(source, []).append((target, edge))
                graph.setdefault(target, []).append((source, edge))
        paths = self._paths(text(subject.get("id")), graph)
        selected_features = {item["name"] for item in tags if item.get("family") != "status"}
        result = []
        for item in entities.values():
            node_id = text(item.get("id"))
            if (
                item.get("type") != "account"
                or node_id in {text(subject.get("id")), text(selected.get("id"))}
                or node_id not in paths
            ):
                continue
            nodes, edges, strength = paths[node_id]
            names = [PRESENTATION.get(text(edge.get("type")), (text(edge.get("type")), "", ""))[0] for edge in edges]
            candidate = set(names)
            union = selected_features | candidate
            similarity = len(selected_features & candidate) / len(union) if union else 0
            result.append(
                {
                    "login": text(item.get("label")),
                    "node_id": node_id,
                    "database_status": status(item.get("databaseStatus")),
                    "association": round((0.7 * strength + 0.3 * similarity) * 100, 1),
                    "reasons": list(dict.fromkeys(names))[:2],
                    "path": nodes,
                    "path_summary": " → ".join(text(entities.get(node, {}).get("label") or node) for node in nodes),
                    "detail_url": self._detail_url(item),
                }
            )
        return sorted(result, key=lambda item: (-item["association"], item["login"]))[:8]

    @staticmethod
    def _paths(
        root: str, graph: dict[str, list[tuple[str, dict[str, Any]]]]
    ) -> dict[str, tuple[list[str], list[dict[str, Any]], float]]:
        best = {root: ([root], [], 1.0)}
        queue = [(-1.0, 0, root)]
        sequence = 0
        while queue:
            negative, _, current = heapq.heappop(queue)
            nodes, edges, current_strength = best[current]
            if -negative + 1e-9 < current_strength:
                continue
            for neighbor, edge in graph.get(current, []):
                if neighbor in nodes:
                    continue
                candidate = current_strength * STRENGTH.get(text(edge.get("type")), 0.5)
                if neighbor not in best or candidate > best[neighbor][2] + 1e-9:
                    best[neighbor] = (nodes + [neighbor], edges + [edge], candidate)
                    sequence += 1
                    heapq.heappush(queue, (-candidate, sequence, neighbor))
        return best

    def _relation(
        self, edge: dict[str, Any], entities: dict[str, dict[str, Any]], page: int, limit: int
    ) -> dict[str, Any]:
        kind = text(edge.get("type"))
        name, conclusion, limitation = PRESENTATION.get(
            kind, (kind or "关系线索", "当前调查图中存在可回溯关系线索。", "调查线索不是违规结论。")
        )
        source, target = text(edge.get("source")), text(edge.get("target"))
        source_endpoint = self._endpoint(entities.get(source), source)
        target_endpoint = self._endpoint(entities.get(target), target)
        evidence = self._evidence(edge)
        start = (page - 1) * limit
        return {
            "edge_id": edge_id(edge),
            "type": kind,
            "business_name": name,
            "source": source_endpoint,
            "target": target_endpoint,
            "direction": (
                f"{source_endpoint['login']} → {target_endpoint['login']}"
                if kind in DIRECTED or edge.get("directed")
                else "无主从方向"
            ),
            "conclusion": conclusion,
            "metrics": self._safe_metrics(edge.get("metrics")),
            "time_range": {
                "start": text(edge.get("validFrom") or edge.get("start")),
                "end": text(edge.get("validTo") or edge.get("end")),
            },
            "evidence": evidence[start : start + limit],
            "evidence_total": len(evidence),
            "detail_page": page,
            "detail_limit": limit,
            "limitations": limitation,
        }

    @staticmethod
    def _safe_metrics(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {METRIC_LABELS[key]: item for key, item in value.items() if key in METRIC_LABEL_KEYS}

    @staticmethod
    def _safe_profile_metrics(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {
            PROFILE_METRIC_LABELS[key]: item
            for key, item in value.items()
            if key in PROFILE_METRIC_LABELS and item not in (None, "", {}, []) and not isinstance(item, (dict, list))
        }

    @classmethod
    def _evidence(cls, edge: dict[str, Any]) -> list[str]:
        values = []
        for key in ("evidence", "evidenceSummary", "evidence_summary", "details"):
            value = edge.get(key)
            values += value if isinstance(value, list) else [value] if value not in (None, "", {}, []) else []
        result = []
        for value in values:
            if isinstance(value, dict):
                safe = cls._safe_metrics(value)
                if safe:
                    result.append("；".join(f"{key}: {item}" for key, item in safe.items()))
            elif text(value) and not SENSITIVE.search(text(value)):
                result.append(text(value))
        return result[:100]

    @staticmethod
    def _endpoint(entity: dict[str, Any] | None, fallback: str) -> dict[str, Any]:
        entity = entity or {}
        account = entity.get("type") == "account"
        return {
            "node_id": text(entity.get("id") or fallback),
            "login": text(entity.get("label") or fallback),
            "platform": text(entity.get("platform")),
            "server": text(entity.get("server")),
            "database_status": status(entity.get("databaseStatus")) if account else "",
            "detail_url": RelationshipInspectionService._detail_url(entity) if account else "",
        }

    @staticmethod
    def _detail_url(entity: dict[str, Any]) -> str:
        return f"/account/{quote(text(entity.get('label')), safe='')}?platform={quote(text(entity.get('platform')), safe='')}&server={quote(text(entity.get('server')), safe='')}"

    def _cached(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        with self.lock:
            item = self.cache.get(key)
            if item and time.monotonic() - item[0] <= self.cache_seconds:
                return item[1]
            if item:
                self.cache.pop(key, None)
        return None

    def _store(self, key: tuple[Any, ...], value: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if len(self.cache) >= self.max_cache_entries:
                self.cache.pop(min(self.cache, key=lambda item: self.cache[item][0]), None)
            self.cache[key] = (time.monotonic(), value)
        return value
