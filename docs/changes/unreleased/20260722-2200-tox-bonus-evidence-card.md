---
change_id: 20260722-2200-tox-bonus-evidence-card
features: ["TOX-BONUS-001", "TOX-BONUS-SCAN-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Make bonus-discovery evidence directly inspectable

## Before and after

The full-platform ranking showed a clipped one-line conclusion and did not identify which orders
formed the heavy-position peak or whether visible opposing orders had been found. The ranking now
shows the 24-hour maximum concurrent position and order count, plus an explicit suspected-hedge
state. `查看详细结论` opens a compact card with the complete conclusion, peak timestamp, exact peak
orders, exact opposing-order pairs, triggered rules and unresolved limitations.

## Correctness

The peak is the first maximum reached while replaying open and close events for orders entered in
the 24-hour preventive window. The full order count and lot total remain authoritative; at most 50
order rows are retained for display. A visible suspected hedge requires the existing same-symbol,
opposite-direction, five-second and 70% lot-similarity match. It is never labelled a confirmed
hedge, and its absence does not reduce risk.

## Impact

Existing requests, scoring, thresholds and compatibility fields are unchanged. Completed scan rows
add peak timestamp/order detail under `bestCycle`; the existing `peerMatch.details` rows are now
visible. No schema migration or additional remote query is required. Older stored jobs remain
readable and prompt a rerun when exact peak-order detail is absent.

## Documentation updated

Updated both bonus-arbitrage feature documents plus business-rule, data-routing, API and test
authorities.

## Verification

Domain tests cover exact overlapping-order peak membership. Discovery and frontend tests cover the
additive projection and suspected-hedge presentation. Fast and Full verification plus desktop and
mobile browser QA are required before deployment.

## Deployment and rollback

Rebuild the frontend and restart the account and worker services. Rollback removes the additive
cycle fields and detail card; existing job snapshots remain compatible.
