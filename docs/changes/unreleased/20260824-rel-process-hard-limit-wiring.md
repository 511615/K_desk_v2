---
change_id: 20260824-rel-process-hard-limit-wiring
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

Production relationship investigations used a disposable process, but the configured constructor
did not receive the intended 45-second process ceiling. A stuck native or provider-heavy child could
therefore remain resident indefinitely and consume enough memory to make unrelated account work slow
or unresponsive. Production now supplies the fixed 45-second ceiling to every isolated investigation.

## Impact

The relationship endpoint and evidence schema are unchanged. An investigation that cannot complete
within 45 seconds returns its newest available partial evidence with the existing truncation metadata;
the isolated child is terminated and its memory is reclaimed. Other account and job APIs remain
available.

## Documentation updated

Updated ACC-REL-003 current state to describe the production wall-clock ceiling, partial-evidence
behavior and process-memory release.

## Verification

The production composition test verifies that the isolated builder receives the 45-second ceiling.
The isolated-builder timeout tests continue to verify child termination and partial-result behavior.

## Deployment and rollback

No data, API or remote-provider change is required. Reverting this commit removes the outer process
deadline only; it does not alter stored relationship snapshots or account data.
