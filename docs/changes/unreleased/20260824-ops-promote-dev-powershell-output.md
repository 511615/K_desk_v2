---
change_id: 20260824-ops-promote-dev-powershell-output
features: ["JOB-RECOVERY-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

`promote_dev.ps1` indexed a scalar PowerShell string returned by Git, producing a single `Char` and
failing before verification or branch movement. It now selects the first command-output line before
calling `Trim()`.

## Impact

No production service behavior or Git promotion policy changes. The controlled promotion script can
again validate worktree identity and proceed with its existing full-verification and fast-forward
steps.

## Documentation updated

Updated `docs/features/jobs/job-progress-recovery.md` to declare the controlled promotion script
and its PowerShell output handling contract.

## Verification

The controlled promotion command is executed as part of this release after the change.

## Deployment and rollback

Reverting this script change only restores the PowerShell invocation failure; it does not alter any
deployed application revision.
