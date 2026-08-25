---
change_id: 20260825-2030-acc-rel-compact-overlap-band
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Compact same-CRM Galaxy communities and shared-evidence overlays

## Before and after

Same-CRM members were assigned to one relation-family band but retained the base ring's broad
spacing. The result looked like independent scattered accounts rather than one readable community.
When multiple members also shared a second evidence family, the renderer drew separate small
overlays. The 叶 outcome marker inherited the 2× account-node scale and visually dominated smaller
nodes.

## Change

Galaxy now contracts a same-CRM component into a compact, collision-aware segment of its existing
star-track. Each account remains separate, individually selectable and retains its actual evidence
and propagation state. The original relation band remains the primary band.

For an additional common relationship such as LastIP, EA or Copy, one normal-width coloured overlay
covers the compact span of every participating member at the exact same radius. A singleton overlap
remains a short segment. No member is duplicated; no new circular enclosure or synthetic parallel
track is drawn. The 叶 badge is independently scaled to 62% of the unscaled node badge size.

## Impact

This is a Galaxy presentation-only correction. Relationship discovery, scoring, expansion,
read-only data access, routes and API payloads are unchanged. The existing frozen click frame and
visible-node fallback continue to select the account, not its relation band.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Regression test first failed for the required compact-band/overlap helpers, then passed after the
  implementation (`tests/test_api.py -k legacy_galaxy`).
- The inline Galaxy JavaScript compiled through `new Function(...)` without syntax errors.
- Full verification and production visual acceptance are required before release.

## Deployment and rollback

Promote the verified dev commit using `scripts/promote_dev.ps1` and deploy through
`scripts/release_prod.ps1`. Rollback restores the preceding application release; no data migration
or external-state rollback is required.
