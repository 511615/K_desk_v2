---
change_id: 20260825-1022-kln-compact-bar-time-axis
features: ["KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Compact K-line bar pane and time axis

## Before and after

The Lightweight Charts stage used 720px of vertical space and its lower bar pane occupied about one
third of the plot, making the Profit/volume/position bars and time labels look too tall. The stage is
now 620px high, the lower pane uses a 0.6 stretch factor, and the time scale has a 24px minimum height.

## Impact

The main candlestick pane retains approximately its former height while the lower bar and time area
becomes visibly slimmer. Order evidence, prices, time mapping, filters, payloads and APIs are unchanged.

## Documentation updated

Updated `KLN-RENDER-001` with the compact chart-stage, lower-pane and time-axis sizing contract.

## Verification

The renderer regression suite asserts the 620px stage, 0.6 lower-pane stretch factor and 24px time
scale minimum, followed by browser measurement of the production-shaped inline chart.

## Deployment and rollback

No schema, data-routing, MT provider or remote state change is involved. Reverting this change restores
the former 720px stage and default pane ratio; existing generated HTML artifacts remain unchanged.
