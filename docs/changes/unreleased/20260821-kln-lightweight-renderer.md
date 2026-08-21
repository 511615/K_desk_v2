---
change_id: 20260821-kln-lightweight-renderer
features: ["KLN-RENDER-001"]
change_type: refactor
status: unreleased
compatibility: compatible
---

## Before and after

Before, generated artifacts used the legacy canvas renderer and the command always entered the
terminal quote path. After, artifacts use Lightweight Charts and the same normalized payload; an
offline-cache mode renders from an external M1 cache without initializing MT5.

## Impact

The change is additive at the API and artifact level. Symbol selection, filters, markers, holding
lines, Profit/volume/position panels, summary, table and funds replay remain available.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` and the K-line database-generation guide.

## Verification

`tests/test_lightweight_trade_kline.py`, `tests/test_kline.py`, `tests/test_kline_timeline_cache.py`
and Python compilation pass. Governance registry and validation pass.

## Deployment and rollback

The implementation is isolated on `feature/kln-live-demo`; production `8777/8766` is not restarted.
Promotion can be rolled back by selecting the prior renderer commit and removing the feature files.
