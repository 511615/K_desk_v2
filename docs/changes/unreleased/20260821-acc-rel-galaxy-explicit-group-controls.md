---
change_id: 20260821-acc-rel-galaxy-explicit-group-controls
features: ["ACC-REL-003"]
change_type: modification
status: unreleased
compatibility: compatible
---

# ACC-REL-021 — Galaxy explicit group controls

- Feature: `ACC-REL-003` account relationship investigation workspace
- Scope: `K_desk_v2_rel_dev` clone on port `8977` only
- Status: implemented, awaiting user acceptance

## Change

Galaxy circle bands and anchors no longer toggle groups on direct canvas clicks. This removes
the accidental expand/collapse behavior caused by overlapping node, edge, and band hit areas.
The detail panel now renders explicit per-group `展开` / `合并` controls, and a compact `恢复初始`
button is available in the toolbar. Blank canvas clicks no longer reset the investigation.

## Compatibility

- Account-node selection and evidence-edge selection remain unchanged.
- The original galaxy renderer and its data model remain in use; this is an interaction-layer change.
- Production port `8777` was not modified or restarted.

## Verification

- `python -m py_compile src/kdesk/api/kuzu_risk_page.py` passed.
- `git diff --check` passed.
- Clone `8977` restarted and `health_clone_8977.ps1` returned `ok: true`.
- `GET /kuzu-risk?...&graph_type=galaxy` returned HTTP 200 and contains the explicit-control markers.

## Before and after

Before, overlapping canvas targets caused accidental group toggles. After, group operations use deterministic
targets and an explicit reset control while account and evidence selection retain their existing meaning.

## Impact

Galaxy interaction behavior only; API payloads, discovery and scoring remain compatible.

## Documentation updated

Updated the relationship workspace current-state documents and this immutable change record.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back the release snapshot to restore the prior
interaction layer.
