---
change_id: 20260825-1945-kln-drag-bound-trade-markers
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Repaint buy/sell markers while K-line scale is dragged

## Before and after

The chart-host pointer listeners repainted readable Profit bars, but did not refresh the SVG trade
overlay. After dragging the vertical price scale or pane boundary, buy triangles, close squares and
holding lines could retain their old screen positions while K-lines moved. The same interaction
refresh now schedules both the trade overlay and lower-pane bar overlay.

## Impact

Trade time, execution price, marker shape, holding-line data and filters are unchanged. Markers and
holding lines now recalculate from the current candlestick coordinate on every drag frame and on
release.

## Documentation updated

Updated `KLN-RENDER-001` with drag-time marker/holding-line repositioning.

## Verification

The dynamic-overlay regression first failed without the combined interaction refresh, then passed
after pointer move and release were directed through it. The complete renderer and inline account
page regressions pass.

## Deployment and rollback

No API, data, remote state or MetaTrader Manager operation is involved. Reverting only restores
stale marker positions after an interactive vertical chart change.
