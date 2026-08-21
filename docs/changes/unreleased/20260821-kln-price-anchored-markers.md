---
change_id: 20260821-kln-price-anchored-markers
features: ["KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

Before, Lightweight Charts used native `aboveBar`/`belowBar` markers, which placed buy/sell
arrows above or below a candle and made them diverge from the execution quote. After, a transparent
overlay converts each order's normalized open/close plot price with the candle series
`priceToCoordinate` method and its time coordinate. Small directional triangles and close squares
are therefore anchored to the exact quoted price and remain attached during pan, zoom and resize.

## Impact

Only the isolated K-line HTML renderer and development sample change. Trade payloads, quote caches,
API paths, production ports `8777/8766`, remote databases and MT read-only boundaries are unchanged.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the exact-price marker contract.

## Verification

`tests/test_lightweight_trade_kline.py`, `tests/test_kline.py` and `tests/test_worker.py` pass (23
tests). The real cached account sample was regenerated and opened on `8899`; browser console errors
and warnings were empty, and 600 overlay nodes were present for the 300 displayed orders.

## Deployment and rollback

The change is isolated to `feature/kln-live-demo`; production services were not restarted. Revert
this development commit to restore native marker placement while retaining the prior renderer.
