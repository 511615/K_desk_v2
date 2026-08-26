---
change_id: 20260826-0097-acc-rel-fixed-sector-boundary-clearance
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Constrain fixed-sector child maps to their mother-sector space

## Before and after

Before, a local child map used a conservative but approximate mother-sector radius. It could still
visually approach a sector boundary or a nearby outer-layer point. After, every child map is capped
by its exact annulus and ray clearances, along with the clearance to rendered parent edges and sibling
account instances; its local account size is derived from the closest pair of child positions.

## Change

- Compute the drilled account's actual angle inside the host sector and use exact radial and ray
  distances as circle-boundary limits.
- Reserve space for outer-layer sibling accounts and currently painted parent evidence lines.
- Remove the artificial minimum child-map size that could force a boundary crossing; constrained
  maps shrink and remain inspectable through the continuous canvas zoom.
- Scale every local account from the closest pair of projected account positions, preventing node
  overlap across adjacent business sectors as well as within one sector.

## Impact

Presentation-only constraint. The relationship snapshot, propagation, score, query, profile,
global locator and raw relation-detail IDs remain unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Browser regression exposes the child projection's host-fit result and requires it to be true.
- Candidate and deployed browser checks drill a real direct account, require a zero centre/anchor
  delta, retain the outer layer and inspect the rendered screenshot.

## Deployment and rollback

Deploy through the governed release workflow. Rollback is revision-only and changes no source data,
database schema, remote query route, MT4/MT5 Manager setting or account state.
