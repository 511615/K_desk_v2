---
change_id: 20260825-1320-acc-detail-inline-kline-page-scroll
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Account-detail K-line uses the page scrollbar

## Before and after

The direct K-line document was constrained to a 680px iframe inside the account detail, leaving a
second scrollbar in the embedded content. The K-line now reports its document height to the parent,
which accepts messages only from the embedded frame and expands it within bounded limits. The account
page is therefore the single scroll container for the K-line section. The separate bottom `所有订单`
expandable table is removed from the legacy detail HTML.

## Impact

The inline chart still requests the same bounded 300 completed orders and current positions from the
existing read-only endpoint. No API, query parameter, quote source, stored data or MT4/MT5 state
changes. The compatible read-only orders JSON endpoint remains available; only its redundant legacy
page presentation is removed.

## Documentation updated

Updated `ACC-DETAIL-001` and `KLN-RENDER-001` with the parent/child height contract, single-page
scroll behavior and the removed bottom order-table UI.

## Verification

Focused legacy-page and renderer tests first failed for the missing height-reporting behavior, then
passed after implementation. The full legacy detail and renderer suites verify the iframe attributes,
source validation, removed order section and renderer height notification.

## Deployment and rollback

No schema, data-routing, provider or remote-state change is involved. Reverting this change restores
the fixed-height iframe and legacy expandable order section; the existing endpoint contracts remain
compatible throughout.
