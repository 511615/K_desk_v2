---
change_id: 20260825-1530-acc-detail-inline-kline-cache-refresh
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Refresh embedded K-line after renderer deployment

## Before and after

The account-detail browser fetch could reuse an older inline K-line HTML document after a renderer
release, leaving visual fixes such as lower-bar width unavailable until its client cache expired. The
account page now requests its inline K-line document with browser `cache: 'no-store'`. Each
account-page reload therefore receives the current renderer document;
the endpoint's existing private cache policy and all chart data contracts are unchanged.

## Impact

This is a presentation freshness fix only. It adds no endpoint, job, artifact, database write or
MetaTrader Manager operation. It is backward compatible and preserves the read-only data route.

## Documentation updated

Updated `ACC-DETAIL-001` and `KLN-RENDER-001` to document the browser-side refresh behavior.

## Verification

The legacy account-detail unit test asserts the cache directive and the focused account-detail and
Lightweight renderer test suites pass. Release validation performs the normal Fast/Full, production
contract and browser embedded-source checks.

## Deployment and rollback

Revert this change or restore the previous production release. That restores the prior browser cache
behavior without changing stored data or API payloads.
