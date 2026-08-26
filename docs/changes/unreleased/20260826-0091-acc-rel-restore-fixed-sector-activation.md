---
change_id: 20260826-0091-acc-rel-restore-fixed-sector-activation
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Restore fixed-area relationship renderer activation

## Before and after

The graph-type route accepted `graph_type=fixed-sector`, including account links opened from the
home page, but the shared relationship page no longer injected the fixed-area asset or delegated
canvas clicks to it. The URL therefore rendered the legacy Galaxy star tracks.

## Change

- Load the fixed-area projection asset in the shared relationship page.
- Give the existing capture-phase click dispatcher first refusal to the fixed-area projection.
- Keep the helper guarded by the explicit `fixed-sector` parameter, leaving `graph_type=galaxy`
  on its existing star-track renderer.
- Add a route contract that proves a real account URL contains the fixed-area renderer, activation
  guard and click dispatcher hook.

## Impact

Presentation routing and browser interaction only. Expansion, propagation scores, query parameters,
evidence IDs, profiles and read-only source access are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- API route contracts cover both explicit Galaxy and fixed-area activation.
- Canvas script syntax and the existing immutable Galaxy click-dispatcher contracts remain checked.
- Standard Fast, Full, promotion and 8777 deployment checks are required before handoff.

## Deployment and rollback

Deploy via the controlled release flow. Rollback is a normal service revision rollback; no data
migration or remote source action is involved.
