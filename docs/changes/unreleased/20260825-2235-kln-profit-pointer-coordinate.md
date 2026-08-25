---
change_id: 20260825-2235-kln-profit-pointer-coordinate
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Correct Profit crosshair coordinates for multi-pane charts

## Before and after

The Profit crosshair callback treated every Y coordinate as chart-local. In a multi-pane chart the
underlying event can instead report a pane-local Y, which caused a lower-pane crosshair to be
discarded. The renderer now also measures the host pointer position and converts it with the exact
Profit-pane offset, while accepting either native event coordinate form.

## Impact

Hovering or clicking within the Profit pane now consistently updates the signed two-decimal value
at the right price-axis edge. Main-pane pointer movement clears the transient Profit value; data,
filters, bars and the native crosshair remain unchanged.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the host-pointer coordinate behavior.

## Verification

`tests/test_lightweight_trade_kline.py` requires the host-pointer conversion, the compatible native
event conversion and the pointer-down subscription used to pin a clicked crosshair value.

## Deployment and rollback

No API or data change. Reverting this change restores the previous event-coordinate-only handling.
