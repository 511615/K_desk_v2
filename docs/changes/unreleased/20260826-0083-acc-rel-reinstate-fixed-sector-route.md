---
change_id: 20260826-0083-acc-rel-reinstate-fixed-sector-route
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Reinstate the separate fixed-area relationship route

## Before and after

The fixed-area renderer existed in source but its graph-type selector card, route mapping and asset
activation had been removed. As a result, production offered only the original three graph types.

## Change

- Add `固定区域关系网` to the graph-type selector and route `graph_type=fixed-sector` to the
  relationship canvas without replacing the original Galaxy route.
- Activate the fixed-area renderer only on that explicit graph type; Galaxy keeps its existing
  star-track renderer.
- Treat transitive same-name and same-CRM account families as centre members. The outer fixed
  sectors retain raw evidence IDs for the existing node-profile and relation-detail interactions.

## Impact

Presentation and routing only. Propagation, score calculations, source queries, evidence payloads
and account/profile APIs remain unchanged and read-only.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- API contract tests cover the chooser, route, activation guard and immutable click dispatcher.
- Development service verification checks the chooser card and the fixed-sector asset/guard response.
- Standard Fast, Full, promotion and production release verification are required before handoff.

## Deployment and rollback

Standard promotion and release only. Rollback returns to the prior application revision; no data
or remote source state changes are involved.
