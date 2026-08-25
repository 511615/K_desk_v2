---
change_id: 20260825-2315-kln-profit-stack-axis
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Keep the Profit axis consistent with the selected bar mode

## Before and after

The custom visible Profit overlay always grouped orders by their opening M1 bucket. The native
histogram respected `Profit柱：单独`, so the lower pane could display an individual-mode control
while its visible bars, axis maximum and crosshair instead used a grouped total. The renderer now
uses one mode-aware Profit-bar helper for both the native scale and the visible overlay.

## Impact

In `单独` mode each closed order keeps its own Profit value even when several orders open in one
minute. In `合并` mode those orders are summed by M1 bucket. The bars, symmetric axis labels and
crosshair value always use the same selected representation.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the individual-versus-merged Profit
bar, axis and crosshair rule.

## Verification

`tests/test_lightweight_trade_kline.py` requires the mode-aware helper to supply both the native
Profit series and the custom overlay used for axis and crosshair geometry.

## Deployment and rollback

No API, routing or data changes. Reverting this change restores the former grouped overlay behavior.
