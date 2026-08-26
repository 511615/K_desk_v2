---
change_id: 20260826-0085-gov-stop-uvicorn-supervisor
features: ["GOV-LIFECYCLE-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Stop the Uvicorn supervisor during production release

## Before and after

`stop_prod.ps1` stopped only the process owning port 8777/8766. With Uvicorn worker mode that
process is a child of a supervisor, which immediately respawned it using the previous in-memory
application. A release could therefore report the new Git revision while serving old page code.

## Change

- Resolve the highest parent process that still belongs to the expected K_desk Uvicorn module.
- Stop that supervisor, then clear an already-verified listener child if one briefly remains.
- Keep the existing refusal to stop a process that is not the expected account or K-line module.

## Impact

Release control only. No account, trade, MT4/MT5 Manager, database or remote business data is
modified. The next versioned launcher starts both services from the promoted source tree.

## Documentation updated

- `docs/features/governance/feature-lifecycle.md`

## Verification

- `tests/test_production_versioning.py` asserts supervisor resolution and termination.
- Release verification must confirm a post-restart browser page contains the promoted source
  contract, not a process-resident predecessor.

## Deployment and rollback

Deploy through the normal clean-main release flow. Rollback is the preceding launcher commit and a
controlled restart; no data migration or data restoration is required.
