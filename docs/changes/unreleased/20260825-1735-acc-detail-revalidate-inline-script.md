---
change_id: 20260825-1735-acc-detail-revalidate-inline-script
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Revalidate the account detail before loading inline K-line

## Before and after

The account detail HTML had no explicit cache policy. A browser could reuse an old parent document
whose inline-K-line loader did not contain the versioned chart request, even after the current
renderer was deployed. `/account/{login}` now responds with `Cache-Control: no-cache, must-revalidate`.

## Impact

The route, HTML structure, parameters and read-only data behavior are unchanged. A normal browser
refresh revalidates the small parent HTML before loading the inline K-line document.

## Documentation updated

Updated `ACC-DETAIL-001` with the parent-document revalidation behavior.

## Verification

An account-page response test first failed while it required the revalidation header, then passed
after the route header was added. Existing legacy inline K-line and renderer regressions pass.

## Deployment and rollback

No API payload, data, remote-state or MetaTrader Manager operation changes. Reverting this change
only restores the former browser HTML-cache behavior.
