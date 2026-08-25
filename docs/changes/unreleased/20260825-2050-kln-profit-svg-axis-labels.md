---
change_id: 20260825-2050-kln-profit-svg-axis-labels
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Render Profit values inside the lower pane

## Before and after

The browser did not visibly render the custom Profit axis. The existing SVG overlay now draws
positive maximum, zero and negative maximum values at the same live coordinates as the bars.

## Impact

Values remain derived from the current filtered Profit data; no trading data changes.

## Documentation updated

Updated `KLN-RENDER-001` with the SVG fallback labels.

## Verification

The renderer suite passes after adding the fallback labels.

## Deployment and rollback

No API or data change. Reverting removes only the visible fallback labels.
