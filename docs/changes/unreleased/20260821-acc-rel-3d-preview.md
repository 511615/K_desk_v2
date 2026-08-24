---
change_id: ACC-REL-015
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Additive 3D relationship preview

## Before and after

Before, the 8977 relationship clone offered the default center-constrained 2D workspace and the
legacy galaxy view. There was no isolated way to evaluate spatial depth for a dense investigation.

After, `graph_type=focus-3d` renders the existing `presentationGraph` snapshot in a Canvas scene. The
investigation subject is fixed at the sphere origin, each hop is distributed deterministically on a
spherical shell, and relation entities use a distinct diamond shape. A stable 2D top-down X/Z locator
is shown beside the 3D view. Drag rotates the scene, the wheel changes camera distance, and selecting a
node highlights its evidence route in both views. The graph-type selector and 2D workspace expose the
preview without changing their default behavior.

## Impact

- UI projection only; no query, score, expansion, database or API response changes.
- No external JavaScript or network dependency is introduced.
- Production port 8777 is unchanged; deployment is limited to the 8977 relationship worktree.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Deployment and rollback

Restart only the 8977 clone with `scripts/start_clone_8977.ps1`. Roll back by removing the
`focus-3d` renderer and route from the relationship worktree; the default `focus-force` renderer and
production 8777 service remain unchanged.

## Verification

- Compile the Python page modules and syntax-check the rendered inline JavaScript.
- Run the focused API tests for default, selector, galaxy and 3D routing.
- On 8977, verify drag rotation, wheel zoom, node selection and return navigation to 2D/galaxy.
- On 8977, verify the adjacent 2D top-down canvas remains populated while the 3D scene rotates and
  that the subject stays at the center of both projections.
