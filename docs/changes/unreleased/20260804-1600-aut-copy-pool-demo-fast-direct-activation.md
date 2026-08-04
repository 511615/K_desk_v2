---
change_id: 20260804-1600-aut-copy-pool-demo-fast-direct-activation
features: ["AUT-POOL-001"]
change_type: behavior
status: unreleased
compatibility: compatible
---

# Make Demo fast activation direct for fresh eligible sleeves

## Before and after

`-DemoFastActivation` previously shortened entry shadow to one ranking plus two healthy minutes,
but still left a newly ranked sleeve in `ENTRY_SHADOW` and applied the normal gradual weight increase.

When and only when the terminal is `ACCMGlobal-Demo`, mode is `StagedLive`, and the explicit switch is
enabled, a fresh sleeve in the active zone that is hard-eligible, activity-eligible and
minimum-lot feasible now enters `ACTIVE` during that 15-minute rank cycle. Its effective weight is
set to the current `live_base_weight` immediately. An existing entry shadow remains health-gated so
pending reconciliation cannot bypass operational safety; failed eligibility still reduces weight to
zero. Default and formal modes retain the existing shadow and gradual increase policy.

## Impact

This changes only the explicit Demo test activation policy. It does not bypass terminal permission,
quote/database health, signal expiry, margin, portfolio, client-loss, product, ownership or other
execution gates. No API, database routing or MT4/MT5 Manager behavior changes.

## Documentation updated

Updated AUT-POOL-001, Business Rules and Operations to document direct fresh-sleeve activation,
retained entry-shadow safety and unchanged default/formal mode behavior.

## Deployment and rollback

Development testing does not restart a service. Promotion requires the normal controlled Producer
restart. Rollback restores the previous domain and Producer code; persisted dynamic state remains
readable and no MT5 state migration is needed.

## Verification

Domain and Producer tests cover direct first-ranking activation with the explicit Demo scope,
effective-weight assignment, non-executable fallback to zero and retained shadow behavior. Related
copy-pool regression tests remain required before promotion.
