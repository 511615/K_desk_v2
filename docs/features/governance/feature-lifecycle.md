---
feature_id: GOV-LIFECYCLE-001
title: Feature documentation lifecycle
module: governance
status: active
apis: ["GET /api/meta", "POST /scripts/promote_dev.ps1", "POST /scripts/release_prod.ps1", "POST /scripts/verify_deployed_release.ps1"]
code: ["src/kdesk/__init__.py", "src/kdesk/build_info.py", "scripts/governance.py", "scripts/verify_change.ps1", "scripts/verify_deployed_release.ps1", "scripts/verify_live_matrix.py", "scripts/backup_sqlite.py", "scripts/generate_governance_artifacts.ps1", "scripts/install_git_hooks.ps1", "scripts/install_maintenance_skill.ps1", "scripts/promote_dev.ps1", "scripts/publish_change.ps1", "scripts/release_prod.ps1", "scripts/start_prod.ps1", "scripts/stop_prod.ps1", "scripts/health_check_prod.ps1", "skills/kdesk-maintenance", "frontend/playwright.config.ts", "frontend/vite.config.ts", "frontend/pnpm-lock.yaml", "runtime/prod/contracts", ".githooks", ".github/workflows", "AGENTS.md"]
tests: ["tests/test_governance.py", "tests/test_architecture.py", "tests/test_production_versioning.py", "tests/test_verify_live_matrix.py"]
depends_on: []
last_verified_version: 2.1.1
last_verified_date: 2026-08-25
---

# Feature documentation lifecycle

## Purpose and user entry

Make every independently changeable feature traceable from current behavior to code, APIs, tests,
immutable changes and releases.

## UI and behavior

There is no end-user panel. Developers and AI use AGENTS, the version-controlled/installed maintenance Skill and verification scripts.

## API contract

`/api/meta` publishes version, Git/build/schema metadata, registry version, feature count,
compatibility level, source root, Python executable, branch and default route contracts. Production
release acceptance compares these values with the release manifest; readiness alone is not a version
identity check.

## Data, routing and read-only constraints

Feature metadata lives in version-controlled Markdown and generated JSON. Governance never reads
or changes remote business state.

## Business rules and units

Every functional change requires a Feature ID, current-state feature document and immutable change
record. System authorities update when their domain changes.

## Loading, empty and failure behavior

Duplicate IDs, missing fields, stale registry/OpenAPI, invalid change references or unrecorded code
changes fail verification with actionable messages.

## Code and dependencies

The Python governance CLI is cross-platform; PowerShell composes local Windows verification.

## Tests and acceptance

Tests validate parsing, registry determinism, change records, architecture boundaries and metadata.
Build-metadata verification accepts the governed `main`, `dev` and named `feature/*` worktrees, as
well as detached execution, so an isolated feature branch can complete Full verification before its
controlled promotion.
Production release is pinned to `D:\risk\K_desk_v2_main` on `main`; ad-hoc deployment worktrees are
prohibited. After restart, `verify_deployed_release.ps1` checks Git SHA, version, source root,
branch, profile and critical route contracts.
The production stop script terminates the Uvicorn supervisor as well as its listening worker. This
prevents a worker-only stop from being immediately respawned with the previous in-memory release.
The production web launchers do not request a one-worker Uvicorn supervisor; the single service
process keeps the promoted checkout's explicit `PYTHONPATH` and cannot silently import a sibling
development worktree.
The verifier accepts the abbreviated Git SHA exposed by `/api/meta` only when it prefixes the
intended release commit.
The relationship-network isolation pilot may use a named `feature/acc-rel-*` branch from `dev`,
but it must merge back into `dev` before promotion and must not be deployed directly. Legacy
relationship routes remain the rollback path while the v2 feature flags are disabled.
The shared verifier also compiles and safety-lints the versioned copy-pool Producer in Fast mode and
runs its complete offline regression suite in Full mode. Release verification checks every configured
live server route and requires each declared volatile finance field to be numeric. Exact finance
formulas are verified with deterministic offline fixtures; moving live-account balances are never
treated as an immutable release baseline. Production remains on `main`; changes are verified in the
separate `dev` worktree. `promote_dev.ps1` runs Full, records the old production revision in `back`,
and fast-forwards `main`; Release verification still runs before restart.

## Compatibility and deprecation

Feature documents and archived change records are never silently deleted; deprecated features retain history.
