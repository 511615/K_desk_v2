---
change_id: 20260824-ops-stop-prod-waits-for-listeners
features: ["JOB-RECOVERY-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

The production stop phase sent a forced-stop request to an owned Uvicorn listener but did not wait
for the port owner to exit. The immediately following start phase could accept the still-listening
old process, leaving legacy page code in memory despite current file-based release metadata.

## Impact

The controlled stop phase now waits up to ten seconds for each owned web listener. No endpoint,
port, data provider or remote write behavior changes.

## Documentation updated

Updated the persistent-job and operational recovery document with the in-memory release consistency
requirement.

## Verification

The controlled release script is rerun after this change; it must expose the current account-page
script marker as well as the deployed Git SHA.

## Deployment and rollback

Reverting this change only restores the stop/start race. Existing service artifacts and SQLite data
remain unaffected.
