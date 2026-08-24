---
change_id: 20260824-kln-batched-viewport-overlay
features: ["KLN-RENDER-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

## Before and after

Every pan or zoom event rebuilt the complete selected order overlay. A dense account therefore
created and positioned a line plus up to two marker elements for every selected order even when
most of those orders were outside the viewport.

The renderer now rate-limits drag refreshes to 50 ms, performs one final settled refresh, filters
overlay evidence to the visible bar range with a small boundary buffer, and batches holding lines,
open markers and close markers into three SVG paths.

## Impact

K-line data, quote source, time mapping, execution prices, filters, display limits and public APIs
are unchanged. Panning and wheel zoom retain exact final coordinates while avoiding repeated
off-screen rendering. The page remains usable if an overlay refresh is delayed briefly during a
continuous drag; it is corrected once interaction stops.

## Documentation updated

Updated KLN-RENDER-001 with viewport-scoped batched overlays and interaction refresh behavior.

## Verification

Renderer regression tests assert the bounded refresh interval, visible-row selection, one-path
holding-line batching, one-path opening-marker batching and settled refresh scheduling.

## Deployment and rollback

No data, task, API, quote-provider or stored-artifact contract changes are required. Reverting the
release restores the prior full-overlay-per-pan implementation only.
