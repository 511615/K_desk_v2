---
change_id: 20260825-2015-kln-close-marker-and-profit-scale
features: ["KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Make close markers and Profit magnitude immediately readable

## Before and after

Close squares used the generic blue marker colour, and the Profit pane intentionally hid its price
scale. Close squares are now red, while the visible Profit right axis displays numeric values using
the existing actual symmetric Profit range.

## Impact

No trade, price, Profit calculation, filter or data route changes. The numeric axis changes only
the presentation of the existing raw/aggregated bar values.

## Documentation updated

Updated `KLN-RENDER-001` with red close-square semantics and the visible actual-Profit axis.

## Verification

The renderer regression first failed without the visible Profit scale and red close marker, then
passed after both presentation options were added. Full renderer and inline account-page regressions
pass.

## Deployment and rollback

No API, data, remote state or MetaTrader Manager operation is involved. Reverting restores blue
close squares and hides the Profit numeric axis.
