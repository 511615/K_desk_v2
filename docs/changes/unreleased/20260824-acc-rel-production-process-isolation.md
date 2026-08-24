---
change_id: 20260824-acc-rel-production-process-isolation
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

Job-count and snapshot limits stopped unbounded queue growth, but production relationship discovery still
ran inside the long-lived 8777 process. Timed-out MySQL/legacy worker threads and Python/native allocation
arenas could remain committed after the visible task and cache had completed.

Production now runs each admitted investigation in a disposable spawned process. The account service keeps
only normalized progress/final snapshots; Windows reclaims the child's source-query, parser and native
allocations at exit. A 45-second hard deadline terminates stuck work and preserves the latest partial graph
when one exists. Non-production profiles keep the injectable in-process path for deterministic tests.

## Impact

No public route or result field is removed. Investigation startup gains process-spawn overhead, traded for
deterministic memory reclamation and isolation from stale source threads. AC/DBG and MT reads remain
read-only.

## Documentation updated

Updated ACC-REL-003 implementation ownership, production behavior, operations triage and test coverage.

## Verification

Tests cover production runtime selection, progress forwarding, final-result transfer and forced termination
of a stuck child. Full and Release verification plus a real-account memory comparison are required.

## Deployment and rollback

Deploy from clean `main`. Rollback restores in-process relationship execution; no data migration is involved.
