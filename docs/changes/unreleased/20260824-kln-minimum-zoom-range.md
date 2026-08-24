---
change_id: 20260824-kln-minimum-zoom-range
features: ["KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

## Before and after

The default Lightweight Charts minimum bar spacing prevented users from zooming out far enough to
inspect longer M1 histories. The renderer now applies a `0.12` minimum bar spacing and refits the
initial content after applying it.

## Impact

No quote, trade, timeline, marker or API data changes. Users can see a larger time range while the
existing viewport-scoped batched overlay protects drag and zoom performance.

## Documentation updated

Updated KLN-RENDER-001 with the minimum zoom range and interaction guarantee.

## Verification

Renderer tests assert the configured `minBarSpacing` value alongside the batched-overlay tests.

## Deployment and rollback

No schema, task, data-route or compatibility change. Reverting restores the library default zoom
floor only.
