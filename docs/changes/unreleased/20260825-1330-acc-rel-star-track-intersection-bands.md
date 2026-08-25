---
change_id: 20260825-1330-acc-rel-star-track-intersection-bands
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Render relationship intersections on star-track arcs

## Before and after

The first overlap presentation drew a complete dashed circle around the geometric centre of every
intersecting relationship component. Those circles were unrelated to the Galaxy depth tracks and
obscured the account/evidence view.

Relationship intersections now render as short, colour-coded arc segments on the existing concentric
star-track ring for the member's discovery depth. Multiple relationship families use parallel radial
lanes on that same ring, so an account can visibly participate in LastIP, same-name, IB, EA or Copy
communities without adding a new enclosing circle.

## Impact

This is a Galaxy presentation-only change. Discovery, propagation score, relation evidence, APIs,
Kuzu projection and all read-only data access stay unchanged. Existing canonical community controls
continue to own expand/collapse interaction.

## Documentation updated

Updated `ACC-REL-001`, `ACC-REL-003` and the architecture current-state wording for cohort evidence
and star-track intersection rendering.

## Verification

Galaxy page regression asserts that the star-track overlap helpers are present and the centroid-circle
renderer is absent. The targeted Galaxy/API tests and embedded JavaScript syntax check pass.

## Deployment and rollback

Promote the verified dev commit and release from clean `main`. Rollback restores the preceding
application commit and restarts 8777; no migration or external-state reversal is required.
