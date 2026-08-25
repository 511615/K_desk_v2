---
change_id: 20260825-2330-kln-local-chart-runtime
features: ["KLN-RENDER-001", "ACC-DETAIL-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Serve the direct K-line chart runtime from the local account service

## Before and after

The inline chart document loaded Lightweight Charts directly from a public CDN. When the embedded
browser could not reach that CDN, its controls appeared but script execution stopped before the
canvas was created. The document now requests a same-origin vendor route served by the account
service.

## Impact

Direct account-page K-lines create their canvas without browser public-CDN access. The service
fetches the pinned 5.0.8 artifact once, verifies its SHA-256 digest, caches verified bytes in
process and returns a long-lived immutable response to the browser. If the pinned artifact cannot
be obtained and verified, the route returns an explicit 503 error instead of executing unknown code.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the same-origin runtime rule.

## Verification

`tests/test_lightweight_trade_kline.py` requires the local script source. `tests/test_api.py`
requires the same-origin vendor route, JavaScript content type and immutable cache contract.

## Deployment and rollback

No trade or account data changes. Reverting restores the public-CDN script source.
