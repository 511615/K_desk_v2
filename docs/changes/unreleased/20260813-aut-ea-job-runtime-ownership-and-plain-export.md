---
change_id: 20260813-aut-ea-job-runtime-ownership-and-plain-export
features: ["AUT-EA-001", "JOB-RECOVERY-001", "KLN-DB-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Keep visible EA Comment evidence and bind K-line workers to production runtime

## Before and after

Meaningful MT5 Expert-order Comments could disappear from EA analysis when the exact Comment had no
second routed account. The EA workbook also contained presentation sheets and styling beyond a
plain data export. Separately, production startup could accept a listener based on its module and
partial readiness state without proving its runtime SQLite file and main-worktree supervisor.

## Current behavior

The EA query retains a current-account Comment group with `peerAccounts=0` and an explicit no-peer
limitation. The export now has only unstyled `EA汇总` and `EA明细` data sheets. Production startup and
health checks validate 8777's production profile/database, 8766's `workerQueue` database, and the
current main `.venv` Uvicorn supervisor before accepting an existing listener.

## Impact and compatibility

All existing API paths, filters, payload fields, ports and read-only data access remain compatible.
`peerAccounts` is additive. The EA workbook intentionally changes to the requested simpler shape.
Mismatched old/dev K_desk listeners are replaced only after their expected service module is proven;
unrelated port owners remain a startup error.

## Documentation updated

Updated the AUT-EA-001, JOB-RECOVERY-001 and KLN-DB-001 feature documents, the production
operations authority and the ports/API authority.

## Verification

Focused EA grouping/export tests and production ownership tests pass. PowerShell launcher scripts
are parser-validated. Governed Fast and Full verification plus a controlled production restart are
required before handoff.

## Deployment and rollback

Deploy through `scripts/start_prod.ps1` after a clean main commit. Rollback is the preceding commit
and controlled restart; no database migration or remote source modification is involved.
