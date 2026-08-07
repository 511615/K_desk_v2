---
change_id: 20260807-1045-aut-pool-source-latency-isolation
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Copy-pool live source latency isolation

## Before and after

Live polling previously allowed only four source workers, although the selected MT5 route set has
five physical sources. One source was therefore always queued, every poll waited for every worker,
and MT5 Deals were not applied until the later MT4 snapshot poll also completed. Runtime connections
also inherited the 30-second historical-read timeout.

Every selected physical source now starts in the same platform wave. MT5 and MT4 waves start
together, ready MT5 Deals are applied before waiting for MT4, and the accepted pool switches source
connections to a two-second live connect/read/write profile. Historical builds keep their existing
complete-read timeout. A source failure closes only its connection, preserves its cursor and retries
through the normal next poll.

## Impact

The change bounds live database stalls below the five-second new-risk signal cap and removes the
fixed fifth-source queue. Pool selection, weights, Ticket ownership, order sizing, public CSV/API
contracts and MT Manager state are unchanged.

## Documentation updated

AUT-POOL-001, `BUSINESS_RULES.md`, `DATA_AND_ROUTING.md`, `OPERATIONS.md` and `TEST_STRATEGY.md` now
define the live polling concurrency, timeout separation, cursor behavior and regression coverage.

## Verification

Focused Producer tests cover five-source simultaneous entry, live-timeout activation and MT5-first
application while MT4 is blocked. Fast and Full repository verification plus read-only all-route
preflight are required before promotion.

## Deployment and rollback

Promote only from a clean verified development branch, merge to clean `main`, then restart the sole
Producer without starting another 8777 service. Rollback restarts the prior verified main commit;
runtime snapshots and source cursors remain compatible.
