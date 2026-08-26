---
change_id: 20260826-0096-acc-rel-fixed-sector-local-centres
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Centre nested fixed-sector projections on the drilled account

## Before and after

Before, nested fixed-sector layers inherited the original investigation centre and divided the
selected mother sector radially. At high zoom, every child sector and account therefore converged
into one crowded wedge. After, a drilled account becomes the local centre, and its child sectors
fan around that account within a radius constrained by the available mother-sector space.

## Change

- Make the clicked direct account the world-space centre of its child projection.
- Allocate all eight child business sectors around that local centre, while calculating the child
  radius from the mother sector's radial and angular clearance.
- Place direct accounts in deterministic sector-local angular columns and radial bands.
- Retain the mother layer, the continuous Canvas transform, existing account selection and raw-edge
  evidence interaction unchanged; the added centre halo is visual only and is not a second account
  hit target.

## Impact

Presentation-only change. It does not alter the read-only expansion request, snapshot entities,
scores, propagation level, coverage, global-locator de-duplication, profile request or relation
detail request IDs.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- The fixed-sector browser regression asserts that a nested layer's rendered centre and anchor are
  the clicked direct account, that the local radius is positive, and that the outer layer remains.
- Browser verification checks the actual 8777 route after deployment, including the nested visual
  artifact and unchanged profile/evidence interaction.

## Deployment and rollback

Release through the governed production workflow. Rollback is revision-only; no schema, worker,
remote query route, AC/DBG database, MT4/MT5 Manager or account state changes are involved.
