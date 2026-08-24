---
change_id: 20260824-acc-rel-memory-pressure-guard
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

Relationship investigations kept every distinct completed graph for ten minutes, accepted an unbounded
number of distinct queued accounts, deep-copied the complete graph on each UI poll and rebuilt a full
presentation graph after every expanded account. The focus and Galaxy pages polled every 0.5 and 1.2
seconds even when hidden. Under broad graphs this produced large transient allocations and amplified
machine-wide commit pressure.

The coordinator now admits at most three resident jobs, returns a lightweight retry snapshot when full,
expires completed snapshots after 90 seconds and returns a shallow response envelope. Progress graph
snapshots are generated at most every two seconds. Both pages poll every two seconds and pause while
hidden; Galaxy also aborts its request when the page is unloaded. Final graph scoring, evidence and
expansion thresholds are unchanged.

## Impact

The relationship API response is compatible and adds `revision`, progress timing and an optional
`retryAfterSeconds`. `/health/ready` adds `relationshipExpansion` counters. Remote AC/DBG and MT sources
remain read-only and no source schema changes.

## Documentation updated

Updated ACC-REL-003 current behavior, operations incident triage and the relationship regression matrix.

## Verification

Unit tests cover admission pressure, shallow polling, progress throttling, readiness counters and hidden
page polling. Fast and Full repository verification are required before deployment.

## Deployment and rollback

Deploy from clean `main` through the controlled release script. Rollback restores the previous polling and
cache behavior; no database or artifact migration is required.
