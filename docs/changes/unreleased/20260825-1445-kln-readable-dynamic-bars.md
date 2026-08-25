---
change_id: 20260825-1445-kln-readable-dynamic-bars
features: ["KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Readable dynamic lower-pane K-line bars

## Before and after

At wide chart ranges the native Lightweight Charts Profit and Volume histogram columns could collapse
to one-pixel lines. A chart-host SVG presentation layer now groups the visible lower-pane values by
time bucket and draws each column at no less than 5px wide, expanding with the current time spacing
up to 12px.

## Impact

Profit remains symmetric around zero and Volume remains positive. The overlay is recomputed after
filters, symbol or pane changes, pan, zoom and resize, so bar width is readable at dense ranges while
continuing to follow the live viewport. No trade values, time mapping, endpoints, jobs, quote sources
or data routes change.

## Documentation updated

Updated `KLN-RENDER-001` with the fixed minimum width and dynamic redraw behavior for lower-pane
Profit and Volume columns.

## Verification

A renderer regression first failed because the chart document had no fixed-width dynamic bar layer,
then passed after adding the 5px-to-12px overlay renderer and its viewport redraw hook.

## Deployment and rollback

No schema, data-routing, provider or remote-state change is involved. Reverting this change removes
only the display overlay and restores native histogram-width rendering.
