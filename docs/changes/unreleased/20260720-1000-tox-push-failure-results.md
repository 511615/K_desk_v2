---
change_id: 20260720-1000-tox-push-failure-results
features: ["TOX-PUSH-001", "JOB-RECOVERY-001"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Show partial push-discovery failures

## Before and after

The discovery script persisted partial failures to an artifact, but the worker returned only
successful deep-check rows. Completed workbench results now list every persisted failure with its
stage, account/source, plain-language reason, operational impact and retry count.

## Impact

Discovery worker result serialization, the workbench result panel, related styles and tests.

## Documentation updated

Market-pushing, persistent jobs and the additive push-discovery result contract.

## Verification

Worker tests cover timeout/no-order explanations and loading `failures.json` into the durable result.

## Deployment and rollback

No migration or endpoint removal. Roll back worker and workbench files together; older consumers
continue to use the unchanged `summary` and `results` fields.
