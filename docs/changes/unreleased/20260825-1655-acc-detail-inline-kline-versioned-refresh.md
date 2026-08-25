---
change_id: 20260825-1655-acc-detail-inline-kline-versioned-refresh
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Version each account-page inline K-line fetch

## Before and after

The account page used browser `no-store` for its inline K-line document, but the embedded document
could still be supplied from an older cache entry in the observed browser environment after a renderer
release. Each page-load request now adds an ignored `inlineVersion` query parameter, creating a fresh
document cache key while retaining the existing account/platform/server/order parameters.

## Impact

This is a browser presentation freshness correction. The inline endpoint ignores the additive query
parameter, and chart data, API payloads, jobs, artifacts, database writes and read-only routing remain
unchanged.

## Documentation updated

Updated `ACC-DETAIL-001` with the versioned no-store inline-document request behavior.

## Verification

The legacy account-detail test first failed while it required the page-load version parameter, then
passed after the request was versioned. The direct renderer regression continues to pass; browser
acceptance reloads the account page and confirms its document contains the latest renderer options.

## Deployment and rollback

No remote state or MetaTrader Manager operation is involved. Reverting this change removes only the
cache-key version parameter and restores the former cache behavior.
