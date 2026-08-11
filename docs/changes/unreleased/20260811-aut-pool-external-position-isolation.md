---
change_id: 20260811-aut-pool-external-position-isolation
features: ["AUT-POOL-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Isolate non-model Demo positions from copy execution gates

## Before and after

An open manual or other-EA position on a product managed by the copy pool was detected correctly,
but it blocked every new model position on that product and also set a global exposure-conflict
error. The model already read, sized, attributed and closed only its own Magic/Comment positions, so
the gate unnecessarily stopped an otherwise independent hedging-account strategy.

Non-model open positions are now counted and displayed as isolated observation evidence. They do
not participate in model sizing, P/L, Ticket ownership, close/flatten selection or new-risk gates.
Non-model pending orders remain a blocking gate because they can still create future exposure.

## Impact

The Producer status adds `external_position_count`; the dashboard adds
`status.externalPositionCount`. Existing `externalPositionConflict` remains compatible and is false
for isolated positions. No MT account, order, position, Manager state or remote database is changed
by deployment.

## Documentation updated

Updated AUT-POOL-001, business rules, data/routing and test strategy for the isolated ownership and
remaining pending-order boundary.

## Verification

Producer tests cover same-product entry, global conflict refresh, pending-order retention and
strategy-only order ownership. API and Vue tests cover the additive count and healthy isolated UI.
Fast and Full governed verification run before deployment.

## Deployment and rollback

Deploy by restarting the single main-branch Producer and the 8777 account-only service after Full
verification. Roll back to the preceding commit and restart both processes; local runtime state and
MT positions remain intact, and no replacement or repair order is sent during rollback.
