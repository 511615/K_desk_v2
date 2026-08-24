---
change_id: 20260824-kln-holding-line-overlay-layer
features: ["KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

The holding-line SVG used a lower stacking level than the Lightweight Charts canvas. Segments
inside the price plot could be covered by the chart background, while edge segments remained
visible. The SVG is now explicitly above the canvas, and trade markers remain one layer above it.

## Impact

Only visual stacking changes. Order time, execution price, quote data, holding-line geometry and
marker coordinates are unchanged.

## Documentation updated

Updated KLN-RENDER-001 current state with the canvas/holding-line/marker layer order.

## Verification

The renderer regression test asserts the explicit holding-overlay and marker z-index order.

## Deployment and rollback

No API, stored artifact, data route or job behavior changes. Reverting this commit restores the
prior stacking order only.
