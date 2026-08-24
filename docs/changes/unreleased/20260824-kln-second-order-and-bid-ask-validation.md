---
change_id: 20260824-kln-second-order-and-bid-ask-validation
features: ["KLN-RENDER-001", "KLN-DB-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

Trade markers and holding lines previously shared one horizontal M1-bar center even when source
orders had different seconds. M1 OHLC validation also compared every source endpoint against Bid
high/low, incorrectly treating normal Ask-side buy openings and sell closings as quote deviation.

The Lightweight renderer now lays nodes and SVG holding lines out at their original second fraction
within the containing M1 interval. Bid candles and M1 aggregation remain unchanged. Calibration now
uses a direction-aware executable envelope: buy opens and sell closes may use the M1 Bid high plus
the recorded spread, while sell opens and buy closes remain Bid endpoints. Fallback sources are
explicitly labelled in the rendered metadata.

## Impact

No endpoint, port, job, database schema or remote write behavior changes. Existing M1 cache files
remain usable. Inline detail charts additionally include read-only current positions; a position is
shown from its actual opening price to the latest cached M1 close and is excluded from realised
Profit bars.

## Verification

Focused domain and renderer tests prove an Ask-side buy entry is accepted without accepting the same
price as a Bid-only close, and prove the emitted HTML contains second-fraction node placement plus
the SVG holding overlay. The existing renderer and legacy detail suites remain green.

## Documentation updated

- `docs/features/kline/lightweight-renderer.md`
- `docs/features/kline/database-generation.md`
- `docs/features/account/account-detail-legacy.md`
- `docs/DATA_AND_ROUTING.md`

## Deployment and rollback

The change is additive and production deployment requires the governed development promotion and
release process. Reverting this change restores minute-center nodes and Bid-only validation; it does
not alter cached quotes, source orders, jobs or MT state.
