---
change_id: 20260819-1730-gov-small-project-promotion-flow
features: ["GOV-LIFECYCLE-001"]
change_type: hardening
title: Adopt the main dev back small-project release flow
status: unreleased
compatibility: compatible
---

## Before and after

Before, development used a stale `develop` branch and historical feature branches remained visible
after their commits had entered production. There was no single command that preserved the previous
production revision before promoting development.

After, active development uses `dev`, production remains `main`, and `back` records the `main`
revision immediately before promotion. `promote_dev.ps1` requires clean fixed worktrees, runs Full
verification, rejects divergent histories, updates `back`, and fast-forwards `main` to `dev`.

## Impact

The workflow supports frequent small deployments without accumulating unrelated changes. It adds
Git and release guardrails only; API and database contracts are unchanged.

## Documentation updated

- `AGENTS.md`
- `docs/OPERATIONS.md`
- `docs/features/governance/feature-lifecycle.md`
- `skills/kdesk-maintenance/SKILL.md`

## Verification

- PowerShell parser validation covers the promotion script.
- Production-versioning tests assert Full verification, previous-main preservation and
  fast-forward-only promotion.
- Fast and Full repository verification remain required.

## Deployment and rollback

Run `scripts\\promote_dev.ps1`, then deploy from clean `main` with
`scripts\\release_prod.ps1`. To investigate or roll back, use `back` and the immutable production
release tag or release manifest; do not develop directly on `back`.
