---
change_id: 20260717-1820-automation-toxic-ui-details
features: ["ACC-DETAIL-001", "AUT-COPY-001", "AUT-FOLLOWER-001", "AUT-EA-001", "TOX-PUSH-001", "JOB-RECOVERY-001"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Improve automation detail and Toxic progress

## Before and after

Copy results lacked complete follower/source profit detail, EA comments were not independently
grouped, and Toxic progress/evidence could appear stuck. The workbench now opens account links
through the server-rendered legacy page, which exposes these details through durable job polling
and explicit limitations.

## Impact

Old account detail UI, copy/EA APIs, Toxic jobs, worker progress and discovery scripts.

## Documentation updated

Automation, Toxic, jobs, architecture, rules and testing documents.

## Verification

Legacy unit tests, API tests and persistent job tests cover the changed behavior.

## Deployment and rollback

No public endpoint removal. Stop/restart K_desk after code rollback if required.
