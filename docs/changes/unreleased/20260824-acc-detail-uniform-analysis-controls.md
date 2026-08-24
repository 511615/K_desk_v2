---
change_id: 20260824-acc-detail-uniform-analysis-controls
features: ["ACC-DETAIL-001", "AUT-COPY-001", "AUT-EA-001", "ACC-REL-001", "FIN-HISTORY-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

## Before and after

The legacy detail page hid Copy, EA and relationship controls, and disabled chart, Toxic and
historical-funds controls, when the selected confirmed account had no completed order. It now
always renders the complete analysis control set in the same toolbar layout.

## Impact

No API, route, data source or calculation changes. Empty accounts retain their confirmed platform
and server identity and each invoked analysis reports its own factual empty result.

## Documentation updated

Updated ACC-DETAIL-001, AUT-COPY-001, AUT-EA-001, ACC-REL-001 and FIN-HISTORY-001 current-state
documents to specify uniform control visibility and the corresponding empty-result behavior.

## Verification

The legacy-detail UI test asserts that all analysis control IDs stay present and no longer use the
zero-order visibility or disabled-state gates.

## Deployment and rollback

This is a legacy page presentation-only change. Reverting its commit restores the prior conditional
visibility without affecting account data, jobs, or saved ledger records.
