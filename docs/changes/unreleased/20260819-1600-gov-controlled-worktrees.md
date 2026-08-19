---
change_id: 20260819-1600-gov-controlled-worktrees
features: ["GOV-LIFECYCLE-001"]
change_type: hardening
title: Enforce the controlled K_desk worktree policy
status: unreleased
compatibility: compatible
---

## Before and after

Before, the production identity checks existed in release documentation, but the repository
instructions did not make the three-worktree policy explicit. A future operator could create or
deploy from an untracked ad-hoc checkout.

After, `AGENTS.md` and the maintenance skill explicitly bind production to
`D:\\risk\\K_desk_v2_main` on `main`, development to `D:\\risk\\K_desk_v2_dev` on `develop`, and
the preserved user feature checkout to `D:\\risk\\K_desk_v2`. Temporary worktrees require a
named branch and an explicit merge or cleanup decision.

## Impact

This is an operational guardrail only. It does not change API, database, or source data contracts.
It prevents accidental deployment from stale or anonymous worktrees.

## Documentation updated

- `AGENTS.md`
- `skills/kdesk-maintenance/SKILL.md`
- `docs/features/governance/feature-lifecycle.md`

## Verification

- Governance validation and Fast verification pass with the controlled paths declared.
- The final worktree list contains only the production, development, and preserved user feature
  checkouts.

## Deployment and rollback

No service restart is required for the policy text itself. If rollback is needed, revert this
documentation-only change; production deployment remains controlled by `scripts\\release_prod.ps1`.
