---
change_id: 20260730-1616-aut-copy-pool-versioned-runtime
features: ["AUT-POOL-001"]
change_type: operations
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Versioned copy-pool Producer runtime

## Before and after

- The Producer source and its offline regression tests are now stored under
  `services/copy_pool_runtime` instead of being selected from the mutable `D:\risk` root.
- The repository launcher resolves Producer modules from `$PSScriptRoot` and prepends that path to
  `PYTHONPATH`.
- Existing external Terminal, Input, Output and `D:\risk\pydeps` paths remain unchanged.

## Impact

This is an operational source-layout change. It does not alter selection, risk, order-routing,
database or API behavior. No service or MT terminal is started or stopped, and no root Producer
source file is changed.

## Verification

The copied files are hash-compared with their root sources before launcher-only edits. The copied
tests must collect from the repository runtime directory, and the PowerShell launcher must parse
without errors. Missing optional Python dependencies are reported separately from collection
failures.

## Documentation updated

Updated the AUT-POOL-001 source ownership and operations runbook to make the worktree-local Producer
entry point authoritative.

## Deployment and rollback

Deployment is not part of this change. A future production restart from `main` uses the versioned
launcher. Rollback restores the prior launcher path; external runtime data and MT terminal state are
not migrated or modified.
