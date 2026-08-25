---
change_id: 20260825-1515-kln-thicker-dynamic-bars
features: ["KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Thicker lower-pane K-line bars

## Before and after

The first readable-bar presentation used a 5px minimum and 12px maximum width. At dense ranges this
still looked too thin. The fixed minimum is now 8px and the zoom-responsive maximum is 18px.

## Impact

Profit and Volume values, colours, baseline, time mapping and dynamic redraw triggers remain
unchanged. Only the visual column width is increased so compact views remain legible.

## Documentation updated

Updated `KLN-RENDER-001` with the 8px-to-18px lower-pane column-width range.

## Verification

The renderer regression first failed while it expected the new width range, then passed after the
renderer constants were updated.

## Deployment and rollback

No API, data, provider or remote-state change is involved. Reverting this change restores the prior
5px-to-12px display range.
