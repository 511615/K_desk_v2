---
change_id: 20260824-kln-detail-autoload-and-overlay-origin
features: ["ACC-DETAIL-001", "KLN-DB-001", "KLN-RENDER-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

## Before and after

Entering a legacy account detail required manual K-line submission. The chart marker overlay was a
sibling of the chart canvas, allowing layout-origin drift beside the price scale. The detail page
now automatically queues one recent-order K-line job after a unique account source with completed
orders loads. Markers overlay the exact chart host.

## Impact

Automatic requests retain only the latest 300 completed buy/sell orders, use the selected read-only
route and run through the persistent worker. They are idempotent by account, route and latest-order
version. Manual full-history generation is unchanged. No port, existing URL or remote write path is
added.

## Documentation updated

Updated the legacy detail, database generation and Lightweight renderer feature documents.

## Verification

Focused detail-page, recent-order selection and renderer tests pass. The chart marker test verifies
that the overlay is attached to the Lightweight Charts host rather than its outer shell.

## Deployment and rollback

This change is verified on `dev` before promotion. Reverting its commit restores manual-only detail
generation and the prior overlay container; durable jobs and existing chart files remain intact.
