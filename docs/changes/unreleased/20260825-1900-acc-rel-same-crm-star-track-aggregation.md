---
change_id: 20260825-1900-acc-rel-same-crm-star-track-aggregation
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Preserve same-CRM communities on a shared Galaxy star track

## Before and after

Before this repair, same-CRM accounts could be emitted by discovery and evidence correctly but rendered on their
individual logical-depth rings. The visual split made one confirmed same-name community look like
unrelated scattered nodes. Reverse source evidence could also create duplicate pair records, and a
visible node moved by the aggregated layout could miss the frozen click target.

## Change

The presentation graph now computes connected components from `same_crm_user` account evidence
alone and assigns the resulting component key only to that relation family. Reverse-direction
same-CRM pair evidence is canonicalized before it reaches the presentation graph. Galaxy places a
component that spans discovery layers on the nearest existing star-track ring and labels that band
with its complete account count. Its members remain separate visible and selectable account nodes;
no centroid circle, synthetic enclosing ring or data/score change is introduced. The click dispatcher
has a no-relayout fallback against the current visible-node coordinates.

## Impact

This is a presentation and evidence de-duplication correction for `ACC-REL-001` / `ACC-REL-003`.
Relationship discovery, propagation thresholds, source-query routing, APIs and read-only database
access remain unchanged. LastIP, IB, EA and Copy evidence may intersect a same-CRM community but no
longer changes its membership or visual placement.

## Documentation updated

Updated the `ACC-REL-001` relationship-network current-state document and the
`ACC-REL-003` score-propagated Kuzu investigation document with the relation-family component
boundary, shared star-track placement and visible-node click fallback.

## Verification

Targeted graph, risk-composition and API/UI regression tests verify same-CRM component isolation,
reverse-pair canonicalization and the Galaxy shared-band helpers. The embedded page JavaScript is
syntax-checked. Full repository and production visual checks are required before release.

## Deployment and rollback

Promote the verified dev commit using `scripts/promote_dev.ps1` and deploy with
`scripts/release_prod.ps1`. Rollback moves `main` back to the preceding promotion and restarts 8777;
there is no migration or external-state rollback.
