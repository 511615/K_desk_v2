---
change_id: 20260810-1650-acc-rel-readable-force-layout
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: improvement
status: unreleased
compatibility: compatible
---

# Make relationship graph connections readable

## Before and after

The former hop-ring layout piled accounts into the same radius and rendered every relation as an
indistinguishable line. The graph now uses a deterministic force layout with node repulsion and
relation-weighted attraction; each combined edge carries its visible relation label.

## Impact

No API or data query changes. The Canvas combines parallel edges only for display, leaving the full
evidence ledger unchanged for scoring and the right-side detail pane.

## Documentation updated

ACC-REL-001 now records the relation-aware layout and combined edge labels.

## Verification

API page tests assert the combined-edge and relation-label renderer contract.

## Deployment and rollback

Deploy by restarting only 8777 after Full verification. Rollback restores the previous commit and
restarts 8777; no data migration or remote write is involved.
