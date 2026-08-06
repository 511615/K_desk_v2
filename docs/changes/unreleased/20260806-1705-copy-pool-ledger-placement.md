---
change_id: 20260806-1705-copy-pool-ledger-placement
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Copy-pool ledger placement

## Before and after

The Demo account ledger was rendered before the scheduling cadence panel and the independent
current-copy table was rendered much later in the page. Both now appear directly below scheduling,
with the account positions/history first and source-to-Demo mappings immediately after.

## Impact

This is a presentation-only layout change. API payloads, Producer state, execution behavior and
the complete event ledger are unchanged.

## Documentation updated

The AUT-POOL-001 current-state document now defines the scheduling-to-ledger order.

## Verification

The CopyPoolPage layout regression asserts scheduling, Demo ledger and current-copy order. Existing
history, event-tier and current-copy tests remain in scope.

## Deployment and rollback

Deploy the updated 8777 frontend bundle. Rollback is the previous frontend bundle; no data or Demo
state migration is needed.
