---
change_id: 20260824-kln-nearest-m1-order-alignment
features: ["KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

Second-level order timestamps previously selected the first M1 candle at or after the order time.
This could move a buy/sell node and the corresponding Profit bar one minute to the right of the
trade's matching candle. The renderer now uses the nearest cached M1 minute, as the legacy canvas
renderer does, for all order-related x coordinates.

## Impact

Only display-time M1 matching changes in the isolated K-line HTML artifact. Execution prices,
quotes, financial results, API contracts and production services are unchanged.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the shared nearest-bar coordinate rule.

## Verification

For the `33305774` sample, 144 of the first 300 orders had a different next-minute versus nearest-
minute match; M1 high/low envelope matches improved from 192 to 246 with nearest matching. Focused
renderer, K-line timeline and Worker tests pass (26 tests), and the regenerated sample has no
browser console errors or warnings.

## Deployment and rollback

Development-only change on `feature/kln-live-demo`; production services were not restarted.
Reverting this commit returns to next-minute display matching.
