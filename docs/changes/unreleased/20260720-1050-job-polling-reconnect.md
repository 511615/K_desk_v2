---
change_id: 20260720-1050-job-polling-reconnect
features: ["TOX-PUSH-001", "JOB-RECOVERY-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Recover discovery polling after a service restart

## Before and after

One failed polling request replaced a running discovery job with a terminal `Failed to fetch`
screen and discarded its durable job ID. The workbench now preserves the ID, progress and events,
shows a temporary reconnect status and retries with a delay capped at five seconds. It also stores
the latest job ID so account navigation or page reload resumes the same task. Worker subprocess
output is read independently, allowing cancellation checks even while no progress line is emitted.
When browser storage has no ID, a read-only active-job endpoint restores the running or queued
discovery job from SQLite.
When that job finishes or is cancelled, the page advances to the next active discovery job instead
of leaving queued work invisible.
The Vue index is served without caching, and open workbench pages compare the deployed entry hash
every 15 seconds and on focus so a service deployment cannot leave the old terminal fetch behavior
running indefinitely.

## Impact

Workbench discovery polling and deployment-version state, additive active-job API, index cache
headers, worker cancellation responsiveness and related tests. Scoring is unchanged.

## Documentation updated

Market-pushing and persistent job recovery current-state documents.

## Verification

Frontend tests cover job identity/progress preservation, navigation storage and bounded retry timing.
Worker tests cover cancellation of a silent child process; governed Full verification covers
production compilation and existing contracts.

## Deployment and rollback

Compatible change with no migration. Roll back the workbench helper/component/styles and worker
together; running durable jobs remain in SQLite.
