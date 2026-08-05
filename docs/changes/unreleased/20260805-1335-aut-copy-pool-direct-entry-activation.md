---
change_id: 20260805-1335-aut-copy-pool-direct-entry-activation
features: ["AUT-POOL-001"]
change_type: behavior
status: unreleased
compatibility: compatible
---

# Remove the normal customer-pool entry observation period

## Before and after

Ordinary sleeves previously required two qualified rankings and ten healthy entry-shadow minutes.
Only an explicit Demo-only switch could activate a fresh qualified sleeve on its first ranking.

A hard/activity/minimum-lot-qualified sleeve in the active zone now enters `ACTIVE` on its first
ranking in every mode and receives its current live base weight. The Producer no longer creates new
`ENTRY_SHADOW` states. A persisted legacy entry-shadow state remains readable and promotes on its
next qualified ranking. The dashboard removes the obsolete entry-observation tab and maps legacy
rows to the monitor presentation.

## Impact

Newly admitted clients can copy only subsequent new source positions without a normal observation
delay. Existing source positions are still monitor-only and are never chased. Loss-limit recovery
shadows, terminal authorization, source and quote health, signal expiry, ownership, margin, client
and portfolio risk gates remain unchanged. No API is removed; status reports one ranking and zero
entry-shadow minutes while retaining compatible fast-activation fields.

## Documentation updated

Updated AUT-POOL-001, Business Rules, Operations and Test Strategy for direct normal activation,
legacy state compatibility and the unchanged recovery/no-chase controls.

## Deployment and rollback

Promotion requires a controlled Producer and 8777 restart after Full verification. Rollback restores
the prior rank transition and front-end tab; persisted active and legacy shadow states remain
readable and no MT5 or database migration is required.

## Verification

Domain, all-source Producer and monitor tests cover first-ranking activation, legacy shadow
promotion, unchanged recovery tiers, status projection and old-position suppression. Frontend tests
cover hiding the entry-observation tab while preserving old-snapshot parsing.
