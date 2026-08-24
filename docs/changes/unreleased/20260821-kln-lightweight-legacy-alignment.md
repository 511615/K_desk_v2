---
change_id: 20260821-kln-lightweight-legacy-alignment
features: ["KLN-RENDER-001"]
change_type: compatibility
status: unreleased
compatibility: compatible
---

## Before and after

The first Lightweight sample used text-labelled markers and a simplified lower layout. The
renderer now follows the legacy evidence chart: black directional triangles without `开/平` ticket
labels, blue close squares, purple dashed holding lines, the original toolbar wording, overlay panel
switcher, position snapshot cards and the legacy order-table columns.

## Impact

Only the development renderer HTML changes. The normalized quote/trade payload and production
services remain unchanged.

## Documentation updated

The renderer feature documentation remains the source of truth for the compatibility contract.

## Verification

Focused renderer, K-line and Worker tests pass. The real cached-account sample was regenerated and
opened at the isolated `8899` service; browser console warnings/errors were empty.

## Deployment and rollback

This is isolated to `feature/kln-live-demo`. Production `8777/8766` is not restarted. Revert the
alignment commit to return to the previous development renderer.
