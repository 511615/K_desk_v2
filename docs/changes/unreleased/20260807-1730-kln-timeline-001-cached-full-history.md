---
change_id: 20260807-1730-kln-timeline-cached-full-history
features: ["KLN-TIMELINE-001", "KLN-DB-001"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Cached full-history funds replay for K-line charts

## Before and after

Before this change, every database K-line job always read the selected account's funds/Credit facts
and always embedded the replay. After this change, the default chart remains order-only. A user
selects `包含资金与 Credit 回放` to include it; the first selected use reads complete account history
and writes a local cache, while later selected charts reuse that cache. `刷新全量资金缓存` is the
explicit path for another read-only source refresh.

## Rule and scope

Blank start/end fields retain complete-history chart scope. A visible chart date range only slices
the cached replay for display; it never creates a partial funds cache. Caches are isolated by account,
platform and logical server. Remote MySQL/MT sources remain read-only.

## Impact

- Pages: legacy account detail and the v2 account page K-line controls.
- API: additive `includeTimeline` and `refreshTimelineCache` fields on the existing
  `POST /api/kline/generate-from-db` payload.
- Data: local runtime cache only; no schema migration and no production-account mutation.
- Compatibility: old request bodies continue to produce an order-only chart; chart URLs, ports and
  polling contracts do not change.

## Documentation updated

- `docs/features/kline/funds-and-position-replay.md`
- `docs/features/kline/database-generation.md`
- `docs/DATA_AND_ROUTING.md`
- `docs/PORTS_AND_APIS.md`
- `docs/TEST_STRATEGY.md`

## Verification

- Cache build/reuse/refresh/corrupt-cache unit tests.
- K-line timeline, standalone HTML JavaScript and option-contract regressions.
- Governance Fast and Full verification are required before publication.

## Deployment and rollback

No deployment is performed by this change. Rollback removes the optional payload fields and cache
adapter; existing generated artifacts remain readable. Runtime cache files are disposable derived
read-only data and do not require a database rollback.
