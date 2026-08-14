---
change_id: 20260814-job-child-import-root
features: ["JOB-RECOVERY-001", "KLN-DB-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Pin production child import root

## Before and after

The production launcher could start a virtualenv shim whose Windows child interpreter resolved an
older K_desk package from the developer runtime. The health endpoint appeared ready while 8777
submitted K-line jobs to the wrong SQLite file, leaving the production Worker unable to claim them.
The launcher now pins child imports to the current main checkout and disables user-site packages.

## Impact

Only local process startup and job routing are changed. The existing ports, API contracts, SQLite
schema and read-only MT/MySQL access remain unchanged. A controlled restart is required for the
environment variables to reach already-running child processes.

## Documentation updated

Updated `docs/features/jobs/job-progress-recovery.md` and `docs/OPERATIONS.md`.

## Verification

Production process-guard tests and full governed verification are required. A live K-line job for
account `954085` was submitted after recovery and completed successfully with 51 parsed orders and
an accepted XAUUSD.PRO chart.

## Deployment and rollback

Deployed by stopping duplicate K_desk listeners and starting one main-checkout production Web and
Worker set. Rollback is the preceding launcher commit and controlled restart; no remote or trading
state is modified.
