---
change_id: 20260722-2130-tox-position-evidence-modal
features: ["TOX-POSITION-001", "TOX-POSITION-SCAN-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Clarify heavy-position account evidence

## Before and after

The platform ranking showed exposure ratios but not the concrete peak position, mixed all peer
accounts into one list, did not state whether the event penetrated account equity and clipped the
conclusion to one line. Results now show peak lots/order count/notional, a four-state penetration
decision, separate same-direction and opposite-direction suspected hedge lists, and a wrapped
conclusion. Every row opens an analysis modal with full evidence and the exact peak orders.

## Correctness

MT5 history retains real Order IDs and Position IDs; MT4 retains ticket IDs. Actual event loss above
reconstructed event equity produces `是`. A recognized negative-balance reset/clear ledger comment
without that calculation produces only `疑似`. Completed events without either produce `否`; open
events or unreliable historical-equity reconstruction produce `数据不足`. Same-symbol entries within
five seconds are split by direction. Opposite-direction peers are explicitly labeled suspected and
do not add same-direction coordination points.

## Impact

Existing request parameters, endpoints and compatibility fields remain unchanged. Completed result
rows add peak-position, penetration, order-detail and direction-split peer fields while retaining
`peerAccounts` as the same-direction compatibility alias. Remote reads remain indexed and SELECT-only;
no schema migration is required.

## Documentation updated

Updated both position-risk feature documents plus business-rule, data-routing, API and test-strategy
authorities.

## Verification

Domain and discovery tests cover the new evidence and state distinctions. Frontend tests/build plus
desktop/mobile browser QA verify readable conclusions, the analysis modal and scrollable order detail.
Fast and Full governance verification are required before deployment.

## Deployment and rollback

Restart the discovery and interactive workers plus the account service after rebuilding the frontend.
Rollback removes the additive fields/modal and restores the combined peer column; existing completed
job snapshots remain readable and show the modal's historical-result fallback when order details are absent.
