---
change_id: 20260805-1615-aut-copy-opening-time-range
features: ["AUT-COPY-001", "AUT-FOLLOWER-001", "ACC-DETAIL-001"]
change_type: addition
status: unreleased
compatibility: compatible
---

## Before and after

The legacy account-detail Copy dialog now exposes shared start/end datetime controls for CPT and
Signal results. The opening-time range is validated, included in the page-memory cache key, passed to
CPT source/follower discovery and Signal trade/rebate aggregation, and reused verbatim by Excel
export. Empty dates preserve the previous full-history behavior.

## Impact

Existing endpoints and response fields remain compatible; `start` and `end` are optional query
parameters. All MySQL reads remain read-only. No MT4/MT5 Manager action, local-data migration or
financial formula changes are introduced.

## Documentation updated

Updated `AUT-COPY-001`, `AUT-FOLLOWER-001`, `ACC-DETAIL-001` and the account API reference with
the shared range behavior, cache scope and Excel parity.

## Verification

Focused legacy detail tests cover range forwarding, opening-time filtering, Signal aggregation and
UI/export wiring. Governance Fast and Full verification are required before production restart.

## Deployment and rollback

Restart only the local account service on port `8777` after Full verification. Reverting this change
removes the controls and range behavior without changing remote read-only data or local authoritative
storage.
