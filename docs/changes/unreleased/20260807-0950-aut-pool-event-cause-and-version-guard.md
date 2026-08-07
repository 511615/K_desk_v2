---
change_id: 20260807-0950-aut-pool-event-cause-and-version-guard
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Copy-pool event cause and production version guard

## Before and after

The event stream previously assigned historical events to an account-product sleeve's current
tier and collapsed an empty execution result into a generic point-spread, delay or external-position
message. It now uses the event-time phase and decision. A `pool_rebuild_failed + monitor` event is
shown under execution suspension with the explicit zero-target rebuild-failure reason.

Production previously served the mutable `frontend/dist` under whichever worktree started 8777,
and the launcher did not validate its Git branch or dirty state. Startup now requires a clean `main`
checkout and pins the frontend to `runtime/prod/frontend-releases/<full-git-sha>`.

## Impact

The event change is presentation-only and uses existing compatible API fields. The deployment
change affects startup and static-asset selection only; API routes, databases, Producer execution
and MT state are unchanged.

## Documentation updated

AUT-POOL-001 now defines event-time failure labeling and tier placement. `OPERATIONS.md` defines
clean-main startup and SHA-pinned frontend releases, and `TEST_STRATEGY.md` records the associated
regression gates.

## Verification

Frontend regressions cover the exact rebuild-failure wording and event-time tier. Python regressions
cover the frontend path override and launcher guards. PowerShell parsing, Fast/Full verification and
the production frontend build are required before promotion.

## Deployment and rollback

Promote the verified commit to `main`, build once and restart 8777 through the guarded launcher.
Rollback selects the prior main commit and its SHA-pinned frontend release. No database or Demo
position migration is required.
