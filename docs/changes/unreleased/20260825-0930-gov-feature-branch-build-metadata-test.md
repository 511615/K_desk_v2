---
change_id: 20260825-0930-gov-feature-branch-build-metadata-test
features: ["GOV-LIFECYCLE-001"]
change_type: test-only
status: unreleased
compatibility: compatible
---

# Allow governed feature branches in build-metadata verification

## Before and after

Before, the build-metadata test rejected a valid isolated feature worktree even though `/api/meta`
correctly reported its branch. After, the assertion accepts a
named `feature/*` branch as well as `main`, `dev` and detached execution, so the required Full
verification can run in an isolated feature worktree before promotion.

## Impact

This is test-only. The metadata response, relationship APIs, source routing and production
runtime behavior are unchanged.

## Documentation updated

- `docs/features/governance/feature-lifecycle.md`

## Verification

- Fast and Full governed verification are run from the isolated feature worktree.

## Deployment and rollback

No separate runtime deployment behavior is introduced. Reverting the test-only assertion restores
the previous test restriction.
