---
change_id: 20260821-acc-rel-galaxy-route-cache
features: ["ACC-REL-003"]
change_type: modification
status: unreleased
compatibility: compatible
---

# ACC-REL-003 — Galaxy route index cache and final path projection

- Change ID: ACC-REL-020
- Feature: `ACC-REL-003`
- Scope: `D:\risk\K_desk_v2_rel_dev` (8977 test clone only)
- Date: 2026-08-21

## Problem

Selecting an account could show no complete route to the investigation subject. The renderer
was also recomputing a breadth-first search while multiple draw layers were being evaluated,
which made large galaxy views visibly sluggish.

## Change

- Build a deterministic predecessor index once for each response data snapshot, traversing
  relationship entities (EA/CRM/IB/etc.) as hidden path intermediates and returning the
  compressed account/IB route for rendering.
- Reuse the cached route for `parent`, `route`, branch classification and selection filtering.
- Draw the selected account's subject route at the final render boundary after community
  aggregation, using presentation-only `focus-route` edges when a collapsed group would hide
  the path.
- Keep route traversal restricted to account and IB identity nodes; evidence and scoring are
  unchanged.

## Verification

- `python -m py_compile src/kdesk/api/kuzu_risk_page.py`
- `git diff --check`
- 8977 page/static check contains `galaxyBuildRouteCache`, `galaxyDrawSelectedRoute` and
  `focus-route`.
- Read-only relationship API route check: `239067 -> 235938 -> 245014`.
- Production service on 8777 was not edited or restarted.

## Before and after

Before, path ancestry could be recomputed repeatedly and selected routes could disappear behind aggregation.
After, one deterministic route index is reused and selected routes are projected at the final render boundary.

## Impact

Improves client-side route correctness and responsiveness without changing discovery scores or database reads.

## Documentation updated

Updated `ACC-REL-003` current-state behavior and this change record.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back to the previous release snapshot to remove
the route cache and final projection.
