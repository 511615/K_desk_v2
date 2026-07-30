---
change_id: 20260730-1630-gov-main-develop-promotion
features: ["GOV-LIFECYCLE-001", "AUT-POOL-001"]
change_type: operations
status: unreleased
compatibility: compatible
---

# Protected main/develop promotion workflow

## Before and after

- Production and development previously shared one mutable checkout during active work.
- Production now runs from `D:\risk\K_desk_v2` on `main`; ongoing changes use
  `D:\risk\K_desk_v2_dev` on `develop`.
- Promotion requires Full verification in `develop`, merge to `main`, and Full verification again
  before a controlled service restart.

## Verification

The common Fast gate now compiles and correctness-lints `services/copy_pool_runtime`. Full also runs
the complete versioned Producer regression suite with its local runtime path and external dependency
directory supplied through a scoped process environment.

## Impact

There is no API, database, selection or execution-rule change. Local credentials, MT terminals,
snapshots and logs remain external and untracked. Existing 8777 and copy-pool runtime contracts are
unchanged.

## Documentation updated

Updated `docs/OPERATIONS.md`, `docs/TEST_STRATEGY.md` and the `GOV-LIFECYCLE-001` current-state
document. Regenerated governance artifacts remain part of the same change.

## Deployment and rollback

Stop the verified process, check out the prior known-good `main` commit and restart from that clean
production checkout. No data migration or MT Manager operation is involved.
