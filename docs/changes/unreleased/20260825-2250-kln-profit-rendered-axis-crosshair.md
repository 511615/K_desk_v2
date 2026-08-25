---
change_id: 20260825-2250-kln-profit-rendered-axis-crosshair
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Derive crosshair Profit from the rendered axis

## Before and after

The crosshair label used the Histogram series' reverse coordinate conversion. In the lower pane it
could report a value that did not match the visible `+max / 0 / -max` Profit scale. The renderer
now retains the exact rendered maximum, zero, positive and negative coordinates and linearly
interpolates the crosshair value from that same scale.

## Impact

The highlighted Profit number now agrees with the horizontal crosshair position and the visible
right-side Profit axis. It remains signed and rounded to two decimals. Trade data, aggregation,
filters and bar rendering are unchanged.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the rendered-axis interpolation rule.

## Verification

`tests/test_lightweight_trade_kline.py` requires the captured rendered-axis geometry and the
crosshair conversion that consumes it.

## Deployment and rollback

No API or data change. Reverting restores the prior series reverse-coordinate conversion.
