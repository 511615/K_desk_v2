---
change_id: 20260826-0086-acc-rel-pin-production-source
features: ["ACC-REL-001", "ACC-REL-003", "GOV-LIFECYCLE-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Pin the production relationship page to its promoted source tree

## Before and after

The relationship-page deployment could appear to retain an earlier renderer when a Uvicorn worker
was inherited from an older process tree. The release launcher now starts the promoted production
source as one explicit service process.

## Change

- Launch the account and K-line web processes without a Uvicorn worker supervisor.
- Retain the production `PYTHONPATH` and no-user-site guards so pages import only from the promoted
  `main` worktree.

## Impact

Operations-only process startup change. Public routes, relationship evidence, scoring and all remote
data access remain unchanged and read-only.

## Documentation updated

- `docs/features/governance/feature-lifecycle.md`

## Verification

- Production launcher tests assert that the worker supervisor is not requested.
- Post-release `/api/meta` must report the promoted main SHA and production source root.

## Deployment and rollback

Standard release restart only. Rollback restarts the prior promoted release; no database repair is
required.
