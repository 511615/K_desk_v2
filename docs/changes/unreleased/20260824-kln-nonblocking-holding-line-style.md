---
change_id: 20260824-kln-nonblocking-holding-line-style
features: ["KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

## Before and after

The contrast fix used a solid foreground and dark halo, which could obscure dense candlesticks.
Holding evidence now uses the requested legacy-style narrow lavender dashed line with density-aware
opacity and no halo.

## Impact

The overlay remains above the chart canvas, so it cannot disappear behind the background. Only its
stroke presentation changes; execution times, prices, marker positions, quote data and APIs are
unchanged.

## Documentation updated

Updated KLN-RENDER-001 current state for the non-blocking holding-line style and overlay layer order.

## Verification

Renderer tests assert the dashed lavender stroke, absence of the halo and the explicit overlay order.

## Deployment and rollback

No data, job, API or stored-artifact change is required. Reverting this commit restores the prior
solid/halo presentation only.
