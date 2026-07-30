---
change_id: 20260730-1515-aut-copy-pool-idle-hourly-unknown
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Copy-pool idle source and hourly-evidence projection

## Before and after

- A physical source with zero selected customers and a successful complete-build state now projects
  as `idle/unsubscribed`, is counted as available coverage, and is shown as
  `已接入，当前无订阅账号` instead of a connection failure.
- Missing hourly current-comprehensive P/L, hard-eligibility and activity-eligibility values now
  remain `null`. The monitor no longer substitutes daily values as a fabricated hourly result.
- The pool table visibly distinguishes pending hourly refresh from a hard-gate rejection and shows
  the daily-build comprehensive value with its basis while refresh is pending.
- All visible copy-pool account labels, events, mappings and filters now use the actual trading
  Login; aliases remain internal to the snapshot mapping and redirect route.
- Successful hourly rotation now persists the accepted same-day pool, so restart does not roll back
  source subscriptions to the initial daily-build membership. Missing hourly evidence schedules an
  immediate bounded refresh instead of waiting on the previous process timestamp.
- The Producer and its tests are versioned under `services/copy_pool_runtime`; its launcher resolves
  code from the deployed worktree rather than mutable files in `D:\risk`.
- An explicit Demo-only minimum-lot switch permits one test lot per product/direction when portfolio
  stress and margin permit it; all operational and hard-stop gates remain active.

## Impact

The dashboard remains read-only and additive. Existing aliases and redirect paths are retained for
internal mapping compatibility. Database and Manager access remain read-only. Producer deployment
occurs only after Full verification and a recorded `main` commit.

## Verification

Backend snapshot and API regressions cover idle source health, unknown hourly fields and Login
projection. Frontend presentation regressions cover the Chinese idle/error states. Versioned
Producer regressions cover restart persistence and the bounded Demo minimum-lot exception.

## Documentation updated

Updated the AUT-POOL-001 current-state monitor contract for source subscription health, nullable
hourly evidence and real-account UI labels.

## Deployment and rollback

Rollback returns 8777 and the Producer to the previous recorded `main` commit. Runtime snapshots and
Demo Tickets remain local state and must be reconciled before an older Producer is started.
