---
change_id: 20260826-0099-acc-rel-fixed-sector-proportional-recursion
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Make recursive fixed-sector worlds proportional at every depth

## Before and after

The fixed-sector renderer reused the Galaxy-scale node painter and retained absolute minimum sizes
for nested account points, badges, local-centre halos and collision gutters. A deeply drilled child
could therefore fit mathematically while its visible symbols consumed most of the child sector,
producing overlapping circles and leaving no practical space for the next eligible expansion.

## Change

- Use a fixed-sector-local shape painter instead of the Galaxy painter that doubles legacy node
  sizes.
- Make nested node size, sector/edge stroke, account badge and local-centre halo proportional to
  the local projection; hide sub-pixel detail until the continuous canvas is zoomed.
- Replace absolute sibling/evidence clearances with parent-scale-relative clearances and remove the
  visual layout minimum from child world radius selection.
- Focus the continuous camera on a newly drilled child world, with a broad precision-only zoom
  range, while retaining all ancestors in the same pan/zoom coordinate system.
- Bound sector, evidence, node-outline and badge stroke widths at a readable screen maximum once
  deep camera zoom is reached; geometric positions and node radii still scale with the local world.
- Add a browser regression which opens three recursive levels, requires every child to fit its host,
  and bounds each nested direct-node radius to seven percent of its local world before checking the
  shared zoom transform.

## Impact

This is a client-side `graph_type=fixed-sector` presentation correction only. It preserves the
existing read-only snapshot, propagation, score, account-profile selection, locator deduplication,
raw relation IDs and relationship-detail requests. Galaxy and focus-force renderers are unchanged.

## Documentation updated

- `src/kdesk/api/fixed_sector_page.py`
- `frontend/e2e/relationship-fixed-sector.spec.ts`
- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Fixed-sector Playwright opens the 216056 recursive path, checks host fit and proportional node
  radius for every nested level, verifies node, sector-stroke and evidence-line zoom ratios, and
  confirms that a child-camera focus remains stable after a snapshot-poll redraw.
- Fast and Full governed verification run before release; deployed browser verification captures
  both the overview and a zoomed recursive child world.

## Deployment and rollback

Deploy through the governed release workflow. Rollback is revision-only; it changes no database,
remote read route, MT4/MT5 Manager setting, account or trade state.
