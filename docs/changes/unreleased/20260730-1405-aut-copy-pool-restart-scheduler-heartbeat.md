---
change_id: 20260730-1405-aut-copy-pool-restart-scheduler-heartbeat
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Reconcile accepted build day before the first Shadow loop

## Before and after

After restoring a same-day accepted pool, bootstrap restored an older scheduler record. The first
polling cycle therefore started another complete 60-day build and did not replace the previous
public status file until that build finished.

The producer now carries the accepted cache build day into scheduler state before polling. It never
regresses a newer scheduler date and publishes a fresh status snapshot immediately after bootstrap.
Only a versioned cache with complete eleven-route/nine-source validation can receive this treatment.

## Impact

Shadow restarts no longer repeat the same day's full build or leave yesterday's dashboard status in
place. Old, partial or wrong-version caches still force rebuild. No selection threshold, database,
MT account, order or Manager state changes.

## Verification

Domain tests cover build-day advancement, no regression and the Beijing 05:15 scheduler guard.
Producer tests, K_desk Full verification and a restarted 30-minute Shadow remain required.

## Documentation updated

Updated the AUT-POOL-001 current-state lifecycle and operations restart procedure.

## Deployment and rollback

Rollback removes the scheduler alignment and immediate status publish, then restarts Shadow. It has
no data migration; Demo Live remains disabled.
