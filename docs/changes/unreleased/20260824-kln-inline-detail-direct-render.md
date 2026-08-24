---
change_id: 20260824-kln-inline-detail-direct-render
features: ["ACC-DETAIL-001", "KLN-DB-001", "KLN-RENDER-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

## Before and after

The legacy account page automatically submitted a recent-order K-line job and waited for the
durable K-line service. It now places a direct Lightweight Chart immediately above `所有订单` after
the selected source has completed orders. The original manual `生成 K 线图` flow is unchanged.

## Impact

8777 reads at most 300 selected-source completed buy/sell orders and the matching read-only M1
quotes, serializes terminal IPC, and returns an inline document. It uses only a bounded local quote
cache. It creates no job, generated HTML artifact, output URL or remote write and does not call
8766.

## Documentation updated

Updated the legacy account detail, durable database-generation, Lightweight renderer and ports/API
feature documents.

## Verification

Focused API and legacy-page tests verify the direct endpoint and absence of automatic task
submission. A read-only `647773 / MT5 / AC GB MT5` check fetched ETHUSD, NAS100Roll and XAUUSD M1
bars and produced a Lightweight Charts document.

## Deployment and rollback

This change is verified on `dev` before promotion. Reverting its commit restores the previous
automatic recent-order task behavior; existing durable jobs, manual generation and chart artifacts
are unaffected.
