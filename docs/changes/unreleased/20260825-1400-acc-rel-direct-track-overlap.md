---
change_id: 20260825-1400-acc-rel-direct-track-overlap
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Replace parallel intersection lanes with direct track overlap

## Before and after

The previous star-track presentation derived a long arc for each intersecting component and put
families in adjacent radial lanes. In a dense graph this repeated bands and labels until the relation
view was difficult to read.

The canonical relation band now remains exactly where it was. For each extra evidence family at a
shared account, Galaxy overlays only one normal-width, unlabelled segment at that account's existing
star-track radius. Two actual relation tracks therefore meet directly at the shared account; the
renderer adds no parallel lane, enclosing circle, extra ring, member-count label or interaction target.

## Impact

This is a Galaxy presentation-only correction. Relationship discovery, score propagation, evidence,
API contracts, Kuzu projection and read-only data access do not change. Expand/collapse continues to
operate on the canonical relation community only.

## Verification

Focused Galaxy/API regressions assert the direct segment renderer, absence of the former lane and
centroid-circle renderers, and valid embedded JavaScript syntax. The final change also runs the
governance generator and the Fast and Full verification gates.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` to describe direct normal-track overlap and to remove the
previous parallel-lane and duplicate-label wording.

## Deployment and rollback

Release from clean `main` as version `2.1.4`. Rollback is the preceding application revision and
8777 restart; no migration or external-state reversal is required.
