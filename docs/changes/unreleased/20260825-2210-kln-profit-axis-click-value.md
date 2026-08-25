---
change_id: 20260825-2210-kln-profit-axis-click-value
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Keep the Profit axis value visible when the crosshair is clicked

## Before and after

The Profit-axis value was subscribed to crosshair movement only. The chart click callback now uses
the identical pane-local conversion, so a clicked crosshair also updates the exact signed Profit
value at the right price-axis position.

## Impact

The inline K-line contract and underlying Profit data are unchanged. The existing click behavior
that updates the position snapshot remains registered; this adds a second independent listener for
the visible Profit-axis value.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` to document click-pinned Profit values.

## Verification

`tests/test_lightweight_trade_kline.py` asserts both the crosshair-move and chart-click
subscriptions use the Profit-axis conversion.

## Deployment and rollback

No API or data change. Reverting this record's paired code change removes only the click-pinned
Profit-axis refresh.
