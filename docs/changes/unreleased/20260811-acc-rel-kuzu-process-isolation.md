---
change_id: 20260811-acc-rel-kuzu-process-isolation
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Isolate native Kuzu relationship projections from the account service

## Before and after

Request-scoped Kuzu materialization ran inside the single 8777 account-service process. Native Kuzu
allocations could remain resident after a relationship response, so repeated broad relationship requests
grew the account process until ordinary account, ledger and workbench APIs lost usable memory.

Kuzu now runs only in one short-lived child process at a time. The parent waits at most four seconds,
terminates a late child and releases its process-owned native memory. When Kuzu is busy, errors or times
out, the relationship endpoint returns the bounded pure-propagation graph with explicit `kuzuProjection`
coverage instead of failing or blocking unrelated account functions.

## Impact

Existing URLs, filters and normal successful Kuzu results remain unchanged. A transient Kuzu failure is
now visibly partial but does not stall 8777. The isolated child reads only the request's already collected
in-memory evidence and writes only its own temporary local Kuzu graph. It has no remote database, CRM,
MT4, MT5, Manager or authoritative K_desk SQLite write path.

## Documentation updated

Updated ACC-REL-001, ACC-REL-003, architecture, data-routing and business-rule authorities with the
single-child, four-second termination and pure-score fallback behavior.

## Verification

Repository tests cover normal child materialization and forced timeout termination. Relationship tests
cover the scored fallback and coverage record. Governed Fast and Full verification run before deployment;
production acceptance checks both relationship response and 8777 resident memory after a request.

## Deployment and rollback

Deploy through the main-branch account-only 8777 launcher. Roll back to the preceding commit and restart
only 8777. No remote source, account, trade or Manager state is changed by deployment or rollback.
