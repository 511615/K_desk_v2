# K_desk mandatory maintenance rules

## Before any change

1. Read `docs/README.md`, `docs/ARCHITECTURE.md`, and the affected feature documents.
2. Inspect `git status`; preserve all user-owned and unrelated worktree changes.

## Worktree and release policy

- Production is deployed only from `D:\risk\K_desk_v2_main` on branch `main`.
- Development and verification use `D:\risk\K_desk_v2_dev` on branch `develop`.
- `D:\risk\K_desk_v2` is a preserved user feature worktree; do not deploy from it or clean it automatically.
- Do not create ad-hoc release or detached worktrees. A temporary feature worktree requires a named branch,
  an explicit merge/retention decision, and removal only after its changes are verified and accounted for.
- A production restart must use `scripts\release_prod.ps1`; readiness alone is insufficient. Verify `/api/meta`
  and the intended graph route after startup.
3. Identify the affected Feature ID in `docs/feature-registry.json`. Create a feature document when no ID exists.
4. Classify impact as architecture, API, data/routing, business rule, operations, UI, test-only, or internal refactor.

## Required records

- Every feature addition, modification, bug fix, deletion, refactor, or UI interaction change requires a new immutable file in `docs/changes/unreleased/`.
- Every behavioral change must update the affected `docs/features/**/*.md` current-state document in the same change.
- Update system documents when their authority changes: API, data/routing, business rules, architecture, operations, or testing.
- API changes require regenerated OpenAPI snapshots. Data/routing and financial-rule changes require contract tests.
- Never defer documentation to a later change.

## Verification

- Run `pwsh -NoLogo -NoProfile -NonInteractive -File scripts/verify_change.ps1 -Mode Fast` for every change.
- Run `-Mode Full` before pushing or production deployment.
- Run `-Mode Release` only when the configured read-only contract environment is available.
- Report code, documentation, tests, deployment impact, and rollback behavior at handoff.

## Safety and compatibility

- MT4/MT5 Manager operations are strictly limited to read-only inspection and export. Never alter accounts, trades, orders, balances, groups, symbols, permissions, or server state.
- All remote database access is read-only. Never add a write method to an MT adapter.
- Keep `8777/8766`, `/account/{login}`, existing query parameters, legacy account detail UI, and existing JSON contracts compatible unless a documented deprecation has completed.
- New business behavior belongs in domain/application code. Only `src/kdesk/infrastructure/legacy_bridge.py` may import the copied legacy monolith.
