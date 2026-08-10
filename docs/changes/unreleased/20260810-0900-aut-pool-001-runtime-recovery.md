---
change_id: 20260810-0900-aut-pool-001-runtime-recovery
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: bounded in-process Producer recovery

## Before and after

The stale copy-pool monitor had no governed recovery handshake. `POST /api/copy-pool/runtime/recovery`
now accepts only the local same-origin `reconnect_and_sync` action and atomically writes a bounded
local request for the already-running Producer. It neither starts, stops nor kills a Producer.

The Producer consumes that request in-process. It resets only its read-only physical-source database
connections, retains source cursors and source-Position-to-Demo-Ticket ownership, polls to catch up,
then requires three successful reconciliations without a pending source snapshot before normal live
gates can complete. Recovery remains stale/running until the Producer reports `synchronized`.

Complete pool construction now retries only classified connection loss or timeout, with no more than
two retries per source. Query, schema, data-quality and business/eligibility errors are not retried.
While retrying or failed, the Producer heartbeat explicitly retains
`runtime_snapshot_stale=true` and `data_fresh=false`.

## Impact

Operators can request a bounded reconnect-and-sync without creating a second copier or changing
process state from port 8777. Existing runtime state remains the ownership and cursor authority.
Stale evidence cannot become apparently current solely because a rebuild heartbeat advances.
Remote data access remains read-only; no MT Manager operation is involved.
The synchronized result counts successful physical sources from their verified health `state`.
The production `-AccountOnly` launcher path also passes its health-check switch by name, so deploying
only port 8777 no longer fails after startup or touches the unrelated 8766/workers.

## Documentation updated

Updated AUT-POOL-001 current state, ports/API contract, data/routing, operations and test strategy.
The feature registry and generated OpenAPI contract are regenerated from the documented/API source.

## Verification

Focused tests cover strict loopback/same-origin request validation, atomic request reuse, sanitized
status projection, unavailable Producer behavior, source-connection reset with cursor preservation,
three-reconciliation recovery gating, retry classification/count and explicit stale heartbeat state.
Fast and Full verification remain required before promotion.

## Deployment and rollback

Promote from a clean verified development branch. Deploy the normal single Producer and 8777 service;
the recovery endpoint must not be used as a process supervisor. Rollback restores the prior verified
application/Producer revision. No database migration, private-state deletion or MT Manager action is
required.
