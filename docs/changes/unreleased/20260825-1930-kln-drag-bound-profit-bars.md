---
change_id: 20260825-1930-kln-drag-bound-profit-bars
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Repaint readable Profit bars while the chart scale is dragged

## Before and after

The readable SVG bars recalculated for time-scale changes and window resizing, but not while a user
dragged the lower-pane separator or vertical price scale. The dashed zero line could therefore move
while the bars retained their previous coordinates. Pointer movement and release inside the chart
host now schedule the existing frame-coalesced overlay redraw.

## Impact

The Profit/Volume values and rendering width are unchanged. During and after a drag, each bar takes
its baseline again from the visible zero-line series, keeping red and green bars fixed to the dashed
zero axis.

## Documentation updated

Updated `KLN-RENDER-001` with the drag-time overlay refresh rule.

## Verification

The dynamic-bar regression first failed because the chart-host pointer refresh listeners were absent,
then passed after both move and release listeners were added. The complete renderer suite passes.

## Deployment and rollback

No API, data, remote state or MetaTrader Manager operation is involved. Reverting only returns the
stale overlay position after interactive vertical chart changes.
