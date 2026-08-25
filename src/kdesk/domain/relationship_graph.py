from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

RELATION_ENTITY_TYPES = {
    "same_crm_user": "crm_user",
    "login_ip": "ip",
    "ea_feature": "ea_profile",
    "copy_order": "copy_source",
    "copy_group": "copy_source",
    "rebate": "ib",
    "ib": "ib",
    "same_name": "identity",
    "device": "device",
    "email": "email_hash",
    "identity": "identity_hash",
    "toxic_sync_same": "trade_sync_window",
    "toxic_sync_opposite": "trade_sync_window",
}


def build_presentation_graph(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    *,
    subject_id: str,
    max_members_per_group: int = 200,
) -> dict[str, Any]:
    """Build a relation-entity projection without changing scoring semantics.

    The scored account graph remains the source of truth. This projection is only for
    investigation rendering: repeated account-to-account edges are represented by one
    relationship entity and member edges, so the UI can collapse a group safely.
    """
    nodes = {str(item.get("id")): dict(item) for item in entities if str(item.get("id") or "")}
    accounts = {key for key, item in nodes.items() if str(item.get("type") or "") == "account"}
    rendered: dict[str, dict[str, Any]] = {key: dict(value) for key, value in nodes.items()}
    edges: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    same_crm_component_keys = _account_component_keys(
        relationships,
        nodes,
        accounts,
        relation_type="same_crm_user",
    )

    for raw in relationships:
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        if source not in nodes or target not in nodes:
            continue
        relation_type = str(raw.get("type") or "unknown")
        # Existing evidence entities (EA/IP/IB/etc.) are retained and only get metadata.
        existing_entity = target if target not in accounts else source if source not in accounts else ""
        if existing_entity:
            _add_edge(edges, raw, source, target, relation_type)
            continue
        # Shared-LastIP expansion also yields account-to-account edges. If the
        # same projection already contains the concrete IP entity, connect both
        # accounts to that entity instead of creating a second "登录 IP" group.
        concrete_entity = _matching_concrete_entity(raw, nodes, relation_type)
        if concrete_entity:
            for account_id in (source, target):
                if account_id in accounts:
                    _add_entity_link(edges, raw, concrete_entity, account_id, relation_type)
            continue
        group_key = _group_key(
            raw,
            source,
            target,
            nodes,
            account_component_key=(
                (same_crm_component_keys.get(source) or same_crm_component_keys.get(target))
                if relation_type == "same_crm_user"
                else ""
            ),
        )
        group = groups.setdefault(group_key, _new_group(group_key, raw, relation_type))
        group["members"].update((source, target))
        if len(group["evidence"]) < 20:
            group["evidence"].extend(str(item) for item in raw.get("evidence") or [] if item)

    for group_key, group in groups.items():
        group_id = f"relation-group:{group_key}"
        member_ids = sorted(item for item in group["members"] if item in accounts)
        group["memberCount"] = len(member_ids)
        group["visibleMemberCount"] = min(len(member_ids), max_members_per_group)
        group["truncated"] = len(member_ids) > max_members_per_group
        rendered[group_id] = {
            "id": group_id,
            "type": "relation_group",
            "relationType": group["relationType"],
            "label": group["label"],
            "detail": group["detail"],
            "memberCount": group["memberCount"],
            "visibleMemberCount": group["visibleMemberCount"],
            "truncated": group["truncated"],
            "expandable": True,
            "isSubject": False,
        }
        for account_id in member_ids[:max_members_per_group]:
            # The subject already gets the explicit subject-to-group edge below.
            # Emitting it again as a group member creates two visible lines for
            # the same account/group pair and obscures the investigation path.
            if account_id == subject_id:
                continue
            edge = {
                "id": f"group-member:{group_key}:{account_id}",
                "source": group_id,
                "target": account_id,
                "type": group["relationType"],
                "typeLabel": group["label"],
                "label": group["label"],
                "evidence": group["evidence"][:20],
                "groupId": group_id,
                "isAggregated": True,
            }
            edges[edge["id"]] = edge
        subject_members = [item for item in member_ids if item == subject_id]
        if subject_members or any(item == subject_id for item in group["members"]):
            edge = {
                "id": f"subject-group:{group_key}",
                "source": subject_id,
                "target": group_id,
                "type": group["relationType"],
                "typeLabel": group["label"],
                "label": group["label"],
                "evidence": group["evidence"][:20],
                "groupId": group_id,
                "isAggregated": True,
            }
            edges[edge["id"]] = edge
    paths = _shortest_paths(subject_id, rendered, list(edges.values()))
    for entity_id, path in paths.items():
        rendered[entity_id]["path"] = path
    return {
        "entities": list(rendered.values()),
        "relationships": list(edges.values()),
        "groups": [
            {key: value for key, value in group.items() if key not in {"members", "evidence"}}
            | {"id": f"relation-group:{group_key}", "evidence": group["evidence"][:20]}
            for group_key, group in groups.items()
        ],
        "subjectId": subject_id,
        "modelVersion": "relationship-entity-v1",
        "pathCoverage": len(paths),
    }


def _group_key(
    raw: dict[str, Any],
    source: str,
    target: str,
    nodes: dict[str, dict[str, Any]],
    *,
    account_component_key: str = "",
) -> str:
    relation_type = str(raw.get("type") or "unknown")
    label = str(raw.get("label") or raw.get("typeLabel") or relation_type).strip()
    # Prefer a canonical non-account endpoint, otherwise use relation family+label.
    for candidate in (source, target):
        if candidate in nodes and str(nodes[candidate].get("type") or "") != "account":
            return f"{relation_type}|entity|{candidate}"
    if account_component_key:
        return account_component_key
    # Relationship families represent one semantic entity even when each pair
    # has a different evidence sentence. Keeping evidence out of the key avoids
    # recreating the O(n²) account-pair fan-out in the presentation layer.
    return f"{relation_type}|label|{label}"


def _account_component_keys(
    relationships: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    accounts: set[str],
    *,
    relation_type: str,
) -> dict[str, str]:
    """Return stable group keys for disconnected account-only components."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for raw in relationships:
        if str(raw.get("type") or "") != relation_type:
            continue
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        if source not in accounts or target not in accounts or source not in nodes or target not in nodes:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)

    component_keys: dict[str, str] = {}
    visited: set[str] = set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        members: list[str] = []
        pending: deque[str] = deque([start])
        visited.add(start)
        while pending:
            current = pending.popleft()
            members.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
        key = f"{relation_type}|component|{'|'.join(sorted(members))}"
        component_keys.update({member: key for member in members})
    return component_keys


def _new_group(group_key: str, raw: dict[str, Any], relation_type: str) -> dict[str, Any]:
    label = str(raw.get("typeLabel") or raw.get("label") or relation_type)
    return {
        "id": group_key,
        "relationType": relation_type,
        "label": label,
        "detail": label,
        "entityType": RELATION_ENTITY_TYPES.get(relation_type, "relation"),
        "members": set(),
        "evidence": [],
        "state": "collapsed",
    }


def _add_edge(edges: dict[str, dict[str, Any]], raw: dict[str, Any], source: str, target: str, relation_type: str) -> None:
    edge = dict(raw)
    edge["source"] = source
    edge["target"] = target
    edge["type"] = relation_type
    edge.setdefault("typeLabel", edge.get("label") or relation_type)
    edges[str(edge.get("id") or f"edge:{relation_type}:{source}:{target}")] = edge


def _matching_concrete_entity(raw: dict[str, Any], nodes: dict[str, dict[str, Any]], relation_type: str) -> str:
    """Return an existing concrete evidence entity for an account-pair edge."""
    if relation_type != "login_ip":
        return ""
    evidence = " ".join(str(item) for item in raw.get("evidence") or [])
    candidates = [
        (key, item)
        for key, item in nodes.items()
        if str(item.get("type") or "") == "ip" and str(item.get("label") or "")
    ]
    for key, item in candidates:
        label = str(item.get("label") or "")
        if label and label in evidence:
            return key
    # Keep the fallback conservative: only recognize an explicit IPv4 token,
    # never infer a relation from an arbitrary text label.
    if not re.search(r"\bLastIP\s*[:：]\s*\d{1,3}(?:\.\d{1,3}){3}\b", evidence, re.IGNORECASE):
        return ""
    return ""


def _add_entity_link(edges: dict[str, dict[str, Any]], raw: dict[str, Any], entity_id: str, account_id: str, relation_type: str) -> None:
    edge = dict(raw)
    edge["id"] = f"entity-link:{relation_type}:{entity_id}:{account_id}"
    edge["source"] = entity_id
    edge["target"] = account_id
    edge["type"] = relation_type
    edge["isAggregated"] = True
    edges[edge["id"]] = edge


def _shortest_paths(subject_id: str, nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for edge in edges:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source in nodes and target in nodes:
            adjacency[source].append((target, edge))
            adjacency[target].append((source, edge))
    result: dict[str, list[dict[str, str]]] = {subject_id: []}
    queue: deque[str] = deque([subject_id])
    while queue:
        current = queue.popleft()
        for neighbor, edge in adjacency.get(current, []):
            if neighbor in result:
                continue
            result[neighbor] = [*result[current], {"from": current, "to": neighbor, "relation": str(edge.get("typeLabel") or edge.get("label") or edge.get("type") or "关系"), "edgeId": str(edge.get("id") or "")}]
            queue.append(neighbor)
    return result
