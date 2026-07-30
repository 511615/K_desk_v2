---
change_id: 20260722-1704-tox-cross-account-hedge-query
features: ["TOX-HEDGE-001", "ACC-DETAIL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Implement the platform cross-account hedge query

## Before and after

The `平台内多账户对锁` Toxic item previously scored opposite legs inside the selected account and
explicitly stated that cross-account lookup was unavailable. It now queries every configured AC/DBG
MT4 and MT5 physical trade source and returns only cross-account opposite orders whose opening and
closing are both synchronized within five seconds and whose smaller lot size is at least 80% of the
larger lot size. The same 80% gate now applies to opposite suspected-hedge evidence in platform
heavy-position discovery; same-direction coordination remains unchanged.

The account dialog displays physical-source coverage, suspected account routing, pair counts, lots and
exact subject/peer order, position and deal identifiers. It does not mix heavy-position, penetration,
same-direction coordination or other Toxic evidence into this result.

## Correctness and performance

The target account uses its selected route and bounded analysis history. Only fully closed target
entries are queried. Existing indexed opening/closing windows, physical-source deduplication, at most
four concurrent source reads and 500-pair detail bounds are reused. All remote statements remain
SELECT-only. Partial failures stay explicit and never become a clean no-match result.

## Impact

The existing type ID, account URL and Toxic job endpoints remain compatible. Completed results add
`evidence.hedgeQuery` and `result.internalLock`. The copied internal reverse-leg row remains available
only as rollback behavior.

## Documentation updated

Added `TOX-HEDGE-001`; updated the legacy account detail feature and API, routing, business-rule and
test authorities. Regenerate the feature registry and OpenAPI snapshot with the governance script.

## Verification

Focused domain, application, Worker and legacy-page source tests cover the inclusive 80% lot boundary,
below-threshold rejection, opposite-only projection, target-order provenance, partial coverage and the
dedicated result tables. Fast and Full verification are required
before production deployment, followed by browser QA on the account detail dialog.

## Deployment and rollback

Rebuild the frontend and restart the account service plus interactive Worker. Rollback restores the
copied account-internal reverse-leg result; no database migration or state rollback is required.
