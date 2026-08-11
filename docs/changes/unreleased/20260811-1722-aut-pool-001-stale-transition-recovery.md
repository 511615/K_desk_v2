---
change_id: 20260811-1722-aut-pool-001-stale-transition-recovery
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: discard unmanaged stale restart transitions

## Before and after

After the exit-only Ticket recovery fix, a persisted close transition from a client that had no
owned Demo Ticket and was removed by the new account hard gates could remain in the restart journal.
The Producer correctly excluded the client from its source subscription, but the stale transition
still attempted a current-client lookup and repeatedly raised `KeyError`.

Bootstrap now drops a pending restart transition only when its account is absent from the rebuilt
subscription set. Accounts with an owned Demo Ticket have already been restored as exit-only and
remain eligible for reduction/close processing, so their transitions are retained. The discarded
case has no broker-owned position and cannot create an order.

## Impact

The change prevents an unmanaged monitor-only journal row from blocking the live polling loop. It
does not relax account profitability gates, alter source cursors, or remove any owned Ticket
mapping.

## Documentation updated

Updated the AUT-POOL-001 current-state document with the bounded stale-transition cleanup rule.

## Verification

Regression coverage verifies that an absent filtered account's stale transition is dropped, while
owned-Ticket accounts remain subscribed through exit-only recovery. The full Producer suite and
K_desk Full verification remain required before promotion.

## Deployment and rollback

Deploy from the tested main revision with exactly one Producer. If rollback is required, stop the
single Producer and restore the preceding main revision; do not delete private state or manipulate
orders through MT4/MT5 Manager.
