---
change_id: 20260825-2140-kln-profit-crosshair-axis
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# KLN-RENDER-001 Profit right-axis crosshair value

## Before and after

The inline Lightweight Charts Profit pane now renders its fallback static labels at the same
right-hand price-axis edge as the candlestick scale.  When the native crosshair enters the Profit
pane, the renderer converts the crosshair's pane-local coordinate to the active Profit scale and
shows the exact signed value to two decimal places in that same price-axis position.

## Impact

The chart keeps the existing `/api/accounts/by-login/{login}/inline-kline` contract, Profit
aggregation, zero baseline, panel switching and native crosshair interaction.  The transient label
is cleared when the pointer leaves the Profit pane, so it does not cover the K-line price scale or
the other lower-panel modes.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the right-axis position and pane-local
crosshair conversion behavior.

## Verification

`tests/test_lightweight_trade_kline.py` covers the right-axis offset, the crosshair subscription and
the pane-local `coordinateToPrice` conversion.  Browser acceptance verifies that the Profit value
appears at the right axis while the crosshair is over the lower pane.

## Deployment and rollback

No API or data change. Reverting this commit restores the inset static labels without the Profit
crosshair value.
