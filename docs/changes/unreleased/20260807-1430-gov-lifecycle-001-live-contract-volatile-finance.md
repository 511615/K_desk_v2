---
change_id: 20260807-1430-gov-lifecycle-live-contract-volatile-finance
features: ["GOV-LIFECYCLE-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Keep release contracts valid for moving account balances

## Before and after

The release matrix compared active-account balance, net deposit, rebate and derived P/L to a
July snapshot. Normal live activity therefore blocked every release even while routing and API
responses were correct. The matrix now calls the finance panel whenever volatile fields are declared
and requires each declared field to be numeric. Stable, explicitly recorded values continue to use
the existing tolerance comparison.

## Impact

`GOV-LIFECYCLE-001` release verification only. No account API, business formula, SQLite data,
remote source or MT4/MT5 state changes. Deterministic test fixtures continue to protect exact
funds and profit calculations.

## Documentation updated

- `docs/features/governance/feature-lifecycle.md`
- `docs/TEST_STRATEGY.md`

## Verification

- Unit tests cover a volatile-only sample and a missing volatile value.
- Fast, Full and Release verification remain required before production restart.

## Deployment and rollback

Deployment uses the normal release script with its SQLite snapshot and health checks. Rolling back
restores the previous code and runtime snapshot; this change has no schema migration.
