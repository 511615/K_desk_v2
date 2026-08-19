---
change_id: 20260819-1530-gov-release-identity-and-worktree-policy
features: ["GOV-LIFECYCLE-001"]
change_type: hardening
title: Pin production releases to main and verify deployed identity
status: unreleased
compatibility: compatible
---

## Before and after

Before, the repository had production checks and release manifests, but release acceptance did not
compare the live process identity with the intended commit, source root, Python executable or
relationship route. Multiple ad-hoc worktrees made it possible to start an older checkout.

After, production release is restricted to the clean `main` checkout at
`D:\risk\K_desk_v2_main`. `/api/meta` publishes runtime identity fields, and
`verify_deployed_release.ps1` checks the release SHA/version, source root, branch, profile and
critical focus-force/galaxy route contracts after startup.

## Impact

Release and deployment operations become fail-closed. The existing HTTP and database contracts are
unchanged; this adds metadata and operational checks only.

## Documentation updated

- `docs/OPERATIONS.md`
- `docs/PORTS_AND_APIS.md`
- `docs/features/governance/feature-lifecycle.md`
- `C:\Users\amber\.codex\skills\kdesk-maintenance\SKILL.md`
- `C:\Users\amber\.codex\skills\query-ac-dbg-database\SKILL.md`

## Verification

- Production-versioning tests cover release-root and deployed-route checks.
- API metadata tests cover source root, interpreter, branch and default routes.
- Fast and Full verification remain required before production restart.

## Deployment and rollback

Deploy with `scripts\release_prod.ps1 -Version <VERSION>` from the clean production checkout.
Rollback uses the existing release snapshot and prior clean `main` revision; no source database
rollback is required for metadata-only changes.
