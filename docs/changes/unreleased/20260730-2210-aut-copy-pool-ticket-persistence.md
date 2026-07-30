---
change_id: 20260730-2210-aut-copy-pool-ticket-persistence
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Preserve independent Ticket ownership across broker comments

## Before and after

The Demo server retained only 16 characters of an 18-character deterministic independent-order
comment. A valid fill therefore could not be found by the exact-comment reconciliation that followed
the order. The source-to-Ticket state was not persisted and later loops correctly stopped on unknown
strategy Tickets.

Independent comments now use a six-character digest and fit the retained limit exactly. Restored
state recomputes the deterministic comment, migrating older overlong values. Source ownership is
atomically persisted before and after execution. Mapping validation may adopt an actual Ticket only
when its comment and product match exactly one persisted source position; ambiguity and unmatched
Tickets still hard stop.

## Impact

The change affects only independent Demo order identity, local private-state durability and exact
mapping recovery. It adds no remote database writes, does not weaken Ticket ownership, does not adopt
foreign positions and does not change customer selection, sizing or risk limits.

## Verification

Producer tests cover the exact broker-safe comment, legacy migration, pre/post persistence, unique
recovery, unknown Ticket rejection and missing Ticket rejection. Existing independent open, reduce,
close, reverse, restart and customer-isolation regressions remain required.

## Documentation updated

Updated AUT-POOL-001 current state, business rules, operations and test strategy.

## Deployment and rollback

The fix is promoted through `develop` and `main` before the Producer is restarted. The current two
Demo Tickets are repaired only from independently verified source Position evidence. Rollback to the
older comment format is unsafe while any repaired Ticket remains open; rollback first flattens all
strategy Tickets and preserves the private state backup.
