---
feature_id: GOV-LIFECYCLE-001
title: Feature documentation lifecycle
module: governance
status: active
apis: ["GET /api/meta"]
code: ["src/kdesk/__init__.py", "src/kdesk/build_info.py", "scripts/governance.py", "scripts/verify_change.ps1", "scripts/verify_live_matrix.py", "scripts/backup_sqlite.py", "scripts/generate_governance_artifacts.ps1", "scripts/install_git_hooks.ps1", "scripts/install_maintenance_skill.ps1", "scripts/publish_change.ps1", "scripts/release_prod.ps1", "skills/kdesk-maintenance", "frontend/playwright.config.ts", "frontend/vite.config.ts", "frontend/pnpm-lock.yaml", "runtime/prod/contracts", ".githooks", ".github/workflows", "AGENTS.md"]
tests: ["tests/test_governance.py", "tests/test_architecture.py"]
depends_on: []
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Feature documentation lifecycle

## Purpose and user entry

Make every independently changeable feature traceable from current behavior to code, APIs, tests,
immutable changes and releases.

## UI and behavior

There is no end-user panel. Developers and AI use AGENTS, the version-controlled/installed maintenance Skill and verification scripts.

## API contract

`/api/meta` publishes version, Git/build/schema metadata, registry version, feature count and compatibility level.

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
The shared verifier also compiles and safety-lints the versioned copy-pool Producer in Fast mode and
runs its complete offline regression suite in Full mode. Production remains on `main`; changes are
verified in the separate `develop` worktree and pass Full again after promotion before restart.

## Compatibility and deprecation

Feature documents and archived change records are never silently deleted; deprecated features retain history.
