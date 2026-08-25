---
change_id: 20260825-2035-kln-enable-profit-price-axis
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Explicitly show the custom Profit price axis

## Before and after

Setting the Histogram series scale as visible did not make Lightweight Charts render the custom
`profit` axis. The chart now explicitly enables that named price-scale API after the series is
created, so numeric Profit values appear beside the lower pane.

## Impact

The existing symmetric Profit value range, filters and bars are unchanged. This only exposes their
numeric axis labels.

## Documentation updated

Updated `KLN-RENDER-001` with the explicit custom Profit-axis enablement.

## Verification

The renderer regression first failed without the named price-scale API call, then passed after it
was added. The full renderer suite passes.

## Deployment and rollback

No API, data, remote state or MetaTrader Manager operation is involved. Reverting only hides the
numeric Profit price axis again.
