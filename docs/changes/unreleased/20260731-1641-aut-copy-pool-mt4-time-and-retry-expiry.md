---
change_id: 20260731-1641-aut-copy-pool-mt4-time-and-retry-expiry
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Normalize MT4 source time and expire delayed retries

## Before and after

The Producer treated every raw MT4 `OPEN_TIME` as UTC. DBG CN Live1/Live2 actually use UTC+3, so a
source position could appear three hours in the future. An initially timely but rejected entry could
then be retried after its five-second budget and open a delayed Demo Ticket.

Current MT4 positions now use a physical-source clock mapping: AC remains UTC; DBG CN Live1/Live2
use UTC+3; DBG VN Live3 remains in the full eleven-route/nine-source topology and provisionally uses
UTC+3 pending fresh runtime confirmation. Every no-child reconciliation retry rechecks the original
entry deadline and returns `signal_expired_no_copy` after expiry. Existing owned Demo children remain
manageable for reductions and closes.

## Impact

All-source Demo testing stays enabled while delayed source positions can no longer be chased after a
temporary operational or risk rejection. Remote databases and MT Manager remain read-only; only the
already authorized MT5 Demo execution path may write orders.

## Verification

Regressions cover AC UTC, DBG UTC+3, Live3 route retention, timely two/three-second snapshots, a
40-second rejected retry and continued risk release for an expired position with an owned child.
Fast and Full governance verification are required before promotion.

## Documentation updated

Updated the AUT-POOL-001 current-state document plus data/routing, business-rule, operations and
test-strategy authorities.

## Deployment and rollback

Deploy only from verified `main` while the Demo account is flat with no pending orders. Keep 8777
running and restart only the Producer. Confirm 11/11 logical and 9/9 physical coverage, no old-position
replacement order and a natural timely open/close cycle. Rollback stops the Producer, restores the
prior main commit and restarts only after another flat-account check.
