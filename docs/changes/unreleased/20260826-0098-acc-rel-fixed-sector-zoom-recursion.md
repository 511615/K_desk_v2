---
change_id: 20260826-0098-acc-rel-fixed-sector-zoom-recursion
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Keep recursive fixed-sector maps uniformly zoomable and inside their host

## Before and after

Nested sector geometry was reduced visually without an explicit regression that measured the
rendered relation lines and sector strokes. A tightly packed IB identity/trading-account pair could
also consume the clearance needed for the trading account's next child map. After this change each
nested direct instance receives a separate radial band; all nested geometry has one scale factor;
and an ancestor return is treated as a selectable graph cycle rather than an infinite visual drill.

## Change

- Apply each nested projection's geometry scale to account nodes, sector strokes, evidence-line
  widths and their click tolerances.
- Expose rendered radius/stroke/line measurements in the fixed-sector browser frame for acceptance
  checks; use a safe, node-free sector hit position in the browser regression.
- Allocate one radial band per nested direct instance, including IB identity instances, preserving
  host clearance for further eligible account drills.
- Keep a selected ancestor account profile available but prevent root-to-child-to-root visual cycles
  from creating unbounded nested maps.

## Impact

Presentation-only. Existing relationship discovery, propagation score, threshold, account profile,
raw relation-detail request parameters, global-locator de-duplication, routes and read-only data
access are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- The fixed-sector Playwright regression opens two nested direct layers and requires all layers to
  remain in their host sectors.
- It performs five pointer-centred zoom steps and asserts equal scaling for child-node radius,
  sector stroke and raw evidence-line width before drilling the next eligible account.
- Browser acceptance uses account 216056 and confirms the three-layer path, no page errors and
  outer-layer retention.

## Deployment and rollback

Deploy through the governed release workflow. Rollback is revision-only; it changes no database,
remote read route, MT4/MT5 Manager setting, account or trade state.
