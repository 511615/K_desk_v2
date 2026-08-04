---
change_id: 20260804-1400-aut-copy-pool-manual-risk-controls
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: additive
---

# Expose manual copy-pool risk controls

## Before and after

An equity-floor hard stop could remain latched after a transient or previously persisted trigger,
while the dashboard showed only a generic read-only status and did not expose the active gates or
the trigger threshold.

Before, a latched hard stop had no dashboard controls. After, the loopback UI exposes four switches
and a one-shot recovery action backed by an audited atomic file.

## Impact

The producer reads an atomic local control document with independent switches for automatic new
exposure, equity-floor, daily-loss and cycle-loss gates. A separate resume request clears the
current daily hard-stop once and starts recovery shadow. Reductions and flattening remain allowed
when automatic entries are disabled. The 8777 API exposes a loopback-only `PUT /api/copy-pool/controls`
endpoint with strict boolean validation, audit JSONL, and dashboard projection. The Vue page shows
thresholds, current hard-stop state, switch state, save feedback and the recovery action.

The change is additive to the 8777 API and Producer status. It does not mutate remote databases or
MT Manager, and reductions/flattening remain available while entries are disabled.

## Documentation updated

AUT-POOL-001, Ports and APIs, Business Rules and Operations now define the control contract.

## Deployment and rollback

Defaults keep every protection enabled. Invalid or missing controls fail closed. The producer and
8777 processes are not changed by development testing. Rollback removes the additive endpoint and
UI while leaving existing snapshots and private state readable.

## Verification

Backend API, loopback restriction, atomic control/audit write, normalization and Vue interaction
tests pass. Production build and Python compilation pass; full project verification is required
before promotion to main.
