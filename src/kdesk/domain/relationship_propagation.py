from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Any

DEFAULT_THRESHOLD = 12.0
LAYER_DECAY = 0.96
MAX_VISIBLE_NODES = 2_000
MAX_EXPANSIONS = 10_000

# These are investigation-priority weights, not a fraud conclusion.  A score is
# only comparable within this graph rule version and must retain its evidence ledger.
RELATIONSHIP_STRENGTHS = {
    "same_crm_user": 0.95,
    # CRM/IB entities explain a route.  They are deliberately weak bridge edges so a broad
    # distribution hierarchy never turns every downstream account into an auto-expanded peer.
    "crm_owner": 0.05,
    "direct_ib": 0.05,
    "ib_owned_account": 0.05,
    "top_ib_group": 0.05,
    # This is the verified shortcut to an IB user's own trading account, not the IB's downline.
    "ib_direct_account": 0.60,
    # An account and the CRM IB identity that owns it are the same investigation subject.
    # Keep this identity bridge lossless; the next business relationship still decays normally.
    "ib_identity": 1.00,
    # A direct rebate payee is a real, bounded IB branch.  It is intentionally not the
    # broad top-IB aggregate, so it may continue normal evidence discovery when eligible.
    "ib_direct_rebate": 0.70,
    "login_ip": 0.90,
    "ea_feature": 0.80,
    "copy_order": 0.80,
    "copy_group": 0.75,
    "rebate": 0.70,
    "toxic_sync_same": 0.78,
    "toxic_sync_opposite": 0.82,
    "same_name": 0.35,
}


def propagate_scores(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    layer_decay: float = LAYER_DECAY,
    max_visible_nodes: int = MAX_VISIBLE_NODES,
    max_expansions: int = MAX_EXPANSIONS,
) -> dict[str, Any]:
    """Score an evidence graph until the next node no longer meets the threshold.

    Traversal is deliberately not depth-bounded.  It is residual propagation: a
    newly received contribution is forwarded once, attenuated by relation strength
    and layer decay.  Repeated evidence of one relation family keeps only the
    strongest contribution; independent families combine with noisy-OR.
    """
    if not 0 < threshold <= 100:
        raise ValueError("threshold must be between 1 and 100")
    if not 0 < layer_decay < 1:
        raise ValueError("layer_decay must be between 0 and 1")
    if max_visible_nodes < 1 or max_expansions < 1:
        raise ValueError("graph safety limits must be positive")

    nodes = {str(item.get("id") or ""): dict(item) for item in entities if str(item.get("id") or "")}
    subjects = [node_id for node_id, item in nodes.items() if bool(item.get("isSubject"))]
    if len(subjects) != 1:
        raise ValueError("Kuzu risk graph must contain exactly one subject")
    subject_id = subjects[0]

    normalized_edges = [
        {
            "id": str(item.get("id") or ""),
            "source": str(item.get("source") or ""),
            "target": str(item.get("target") or ""),
            "type": str(item.get("type") or "unknown"),
            "label": str(item.get("label") or item.get("type") or "关联证据"),
            "evidence": list(item.get("evidence") or []),
        }
        for item in relationships
        if str(item.get("source") or "") in nodes and str(item.get("target") or "") in nodes
    ]
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in normalized_edges:
        adjacency[edge["source"]].append(edge)
        if edge["target"] != edge["source"]:
            adjacency[edge["target"]].append(edge)

    state = {
        node_id: {"score": 100.0 if node_id == subject_id else 0.0, "pending": 100.0 if node_id == subject_id else 0.0,
                  "hops": 0 if node_id == subject_id else None, "ledger": {}}
        for node_id in nodes
    }
    queue: list[tuple[float, int, str]] = [(-100.0, 0, subject_id)]
    sequence = 1
    expansions = 0
    truncated = False

    while queue:
        _neg_pending, _sequence, current_id = heapq.heappop(queue)
        current = state[current_id]
        residual = float(current["pending"])
        if residual <= 1e-9:
            continue
        current["pending"] = 0.0
        expansions += 1
        if expansions > max_expansions:
            truncated = True
            break

        for edge in sorted(adjacency.get(current_id, []), key=lambda item: (item["id"], item["type"])):
            target_id = edge["target"] if edge["source"] == current_id else edge["source"]
            if target_id == subject_id:
                continue
            # IB identity and direct-rebate edges are directional discovery branches.
            # Letting a role/payee feed its score straight back would artificially
            # amplify the originating account or IB merely because the route is visible.
            if edge["type"] in {"ib_identity", "ib_direct_rebate"} and edge["source"] != current_id:
                continue
            target = state[target_id]
            strength = RELATIONSHIP_STRENGTHS.get(edge["type"], 0.30)
            # Identity nodes only make a CRM role explicit.  Applying the normal per-hop
            # decay here would make the score depend on whether the role is rendered,
            # rather than on a new evidence family.
            decay = 1.0 if edge["type"] == "ib_identity" else layer_decay
            contribution = min(residual * strength * decay, 99.99)
            family = edge["type"]
            existing = target["ledger"].get(family)
            if existing and existing["contribution"] >= contribution:
                continue
            ledger = dict(target["ledger"])
            ledger[family] = {
                "type": family,
                "label": edge["label"],
                "relationId": edge["id"],
                "from": current_id,
                "contribution": round(contribution, 2),
                "strength": round(strength, 2),
                "evidence": edge["evidence"][:20],
            }
            new_score = _noisy_or(entry["contribution"] for entry in ledger.values())
            delta = max(new_score - float(target["score"]), 0.0)
            if delta <= 1e-9:
                continue
            target["ledger"] = ledger
            target["score"] = new_score
            target["pending"] = float(target["pending"]) + delta
            current_hops = int(current["hops"] or 0)
            target["hops"] = min(target["hops"], current_hops + 1) if target["hops"] is not None else current_hops + 1
            if new_score >= threshold:
                heapq.heappush(queue, (-float(target["pending"]), sequence, target_id))
                sequence += 1

        if sum(1 for item in state.values() if item["score"] > 0) >= max_visible_nodes:
            truncated = True
            break

    visible_ids = {node_id for node_id, item in state.items() if item["score"] > 0 or node_id == subject_id}
    rendered_entities = []
    for node_id, source in nodes.items():
        if node_id not in visible_ids:
            continue
        item = dict(source)
        node_state = state[node_id]
        score = round(float(node_state["score"]), 2)
        item.update(
            score=score,
            hops=node_state["hops"],
            expandable=bool(node_id == subject_id or score >= threshold),
            riskLevel=_risk_level(score, threshold),
            riskColor=_risk_color(score, threshold),
            scoreLedger=sorted(node_state["ledger"].values(), key=lambda entry: (-entry["contribution"], entry["type"])),
        )
        rendered_entities.append(item)
    rendered_entities.sort(key=lambda item: (not item.get("isSubject"), -item["score"], str(item["label"])))

    rendered_relationships = []
    for edge in normalized_edges:
        if edge["source"] not in visible_ids or edge["target"] not in visible_ids:
            continue
        rendered_relationships.append({
            **edge,
            "strength": round(RELATIONSHIP_STRENGTHS.get(edge["type"], 0.30), 2),
        })

    return {
        "subjectId": subject_id,
        "threshold": round(float(threshold), 2),
        "truncated": truncated,
        "entities": rendered_entities,
        "relationships": rendered_relationships,
        "summary": {
            "entityCount": len(rendered_entities),
            "relationshipCount": len(rendered_relationships),
            "expandedNodes": expansions,
            "ruleVersion": "risk-propagation-v1",
        },
    }


def _noisy_or(contributions: Any) -> float:
    remaining = 1.0
    for contribution in contributions:
        remaining *= 1.0 - min(max(float(contribution), 0.0), 99.99) / 100.0
    return min(max((1.0 - remaining) * 100.0, 0.0), 100.0)


def _risk_level(score: float, threshold: float) -> str:
    if score >= 60:
        return "高风险关联"
    if score >= 30:
        return "重点关联"
    if score >= threshold:
        return "可扩散关联"
    return "外围线索"


def _risk_color(score: float, threshold: float) -> str:
    if score >= 60:
        return "#ef4444"
    if score >= 30:
        return "#f97316"
    if score >= threshold:
        return "#eab308"
    return "#94a3b8"
