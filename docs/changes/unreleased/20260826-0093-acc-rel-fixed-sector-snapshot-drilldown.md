---
change_id: 20260826-0093-acc-rel-fixed-sector-snapshot-drilldown
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Drill into fixed-area relationships one snapshot layer at a time

## Before and after

The fixed-area route rendered every discovered relationship instance in every sector at once. Dense
IB/CRM branches therefore formed a stack of nodes and lines before the operator had selected a sector.

## Change

- Use the existing complete relationship snapshot as a local navigation graph.
- Render the current centre account's immediate first-layer account points in all of their sectors,
  with no deeper account points.
- Open one sector at a time to reveal only its original evidence lines and expanded detail for those
  immediate account instances.
- Selecting an account updates both the existing account profile and the next sector centre without
  triggering an additional propagation or score query. A local return control restores the prior
  centre.
- Keep the global locator independent of drill-down state: it always renders every de-duplicated real
  account in the snapshot.

## Impact

Presentation and interaction only. The existing expansion job, scores, relation IDs, profile API,
relation-detail API, coverage and source reads remain unchanged and read-only.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Fixed-sector browser regression verifies visible first-layer account points, sector expansion, account
  drill-down/profile selection and the complete de-duplicated global locator.
- The existing Galaxy relation-detail regression remains required, ensuring the shared raw-edge
  evidence interaction is preserved.

## Deployment and rollback

Deploy through the normal controlled release workflow. Rollback is revision-only; it has no data
migration or external source effect.
