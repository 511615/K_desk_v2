---
change_id: 20260807-1845-job-recovery-active-job-precedence
features: ["JOB-RECOVERY-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Prefer running jobs in active-job lookup

## Before and after

`get_active_job` ordered active rows only by timestamp. SQLite rows created and claimed in the same
clock tick can have equal or empty `started_at` values, allowing a newer queued job to be returned
instead of the job already running.

The lookup now orders by explicit status precedence before timestamps: `running` is always selected
before `queued` for the same job kind.

## Impact

This affects only the read-only active-job projection used by K-line, Toxic and discovery polling.
Job creation, claim, cancellation, persistence and worker execution semantics are unchanged.

## Documentation updated

- `docs/features/jobs/job-progress-recovery.md`

## Verification

The existing active-job regression was reproduced by the release suite before the fix. The targeted
job-ledger suite then passed twenty consecutive runs, covering same-tick running and queued rows.
Full repository verification is required before release.

## Deployment and rollback

The change is an SQLite query-order adjustment with no migration. Rollback restores the former
timestamp-only ordering; no job, queue or account data needs conversion.
