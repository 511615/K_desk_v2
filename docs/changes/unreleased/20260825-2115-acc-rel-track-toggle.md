---
change_id: 20260825-2115-acc-rel-track-toggle
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Restore Galaxy relation-track aggregation

## Before and after

The prior Galaxy projection left same-CRM members permanently visible in a compact arc, while other
collapsed communities used a synthetic circular anchor. Neither behavior matched the relationship
track model: one relation set must be represented by its star-track, with detail shown only on demand.

## Change

Each multi-member Galaxy relation group now starts collapsed on its existing relation band. The band
shows the relation label and account count, but no member account node, member edge, aggregate circle
or centroid connector. Clicking its widened boundary expands the real member accounts in that same
track; clicking the expanded boundary collapses them again. The immutable click frame gives visible
nodes priority, then uses the same boundary for both directions.

Same-CRM components remain relation-family scoped. Shared LastIP, IB, EA, Copy and other evidence
continues to be displayed as overlapping band segments on the existing star-track rather than as a
new circle, lane or duplicate account node.

## Impact

This is a Galaxy presentation and interaction correction only. Relationship discovery, propagation,
scores, source coverage, read-only data access, routes and API payloads are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Updated the Galaxy page regression first; it failed before implementation and passes afterward.
- Full verification and production browser acceptance are required before release.

## Deployment and rollback

Promote the verified dev commit using `scripts/promote_dev.ps1` and deploy through
`scripts/release_prod.ps1`. Rollback restores the preceding application release; no data migration
or external-state rollback is required.
