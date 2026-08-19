---
name: kdesk-maintenance
description: Govern every K_desk feature addition, modification, bug fix, deletion, refactor, UI interaction, API, data-routing, business-rule, worker, or release change through Feature IDs, current-state documentation, immutable change records, required tests, and compatibility checks.
metadata:
  short-description: Maintain K_desk features safely
---

# K_desk Maintenance

Use this skill for any code, UI, API, calculation, routing, job, script, documentation, deployment or
operational change under `D:\risk\K_desk_v2`.

## Required reading

1. Read `D:\risk\K_desk_v2\AGENTS.md` completely.
2. Read `docs/README.md` and `docs/ARCHITECTURE.md`.
3. Read `docs/feature-registry.json`, locate the affected Feature IDs, then read every affected
   feature document completely.
4. Read the authority matching the impact: `PORTS_AND_APIS.md`, `DATA_AND_ROUTING.md`,
   `BUSINESS_RULES.md`, `OPERATIONS.md` or `TEST_STRATEGY.md`.
5. Inspect `git status` and preserve all unrelated user changes.

For release or deployment work, also verify the worktree identity before editing or restarting:
the production checkout is `D:\risk\K_desk_v2_main` on `main`; development is
`D:\risk\K_desk_v2_dev` on `develop`. Do not create an ad-hoc worktree for deployment. A feature
worktree must have a named branch and an explicit cleanup/merge decision.

## Feature lifecycle

- Existing feature: update its current-state document and add one new immutable unreleased change record.
- New feature: choose the next unused ID in its module namespace, create a document from
  `docs/features/_template.md`, and add a change record.
- Bug fix: always add a change record; also correct/update the current-state feature document.
- UI detail: record the visible interaction and failure/loading behavior even when architecture is unchanged.
- Removal: mark deprecated, name the replacement and removal version, and retain historical records.
- Refactor: record it; update architecture only when ownership or dependencies change.

Never edit an older change record after it has been released. Documentation and code belong in the same Git change.

## Implementation boundaries

- Keep the modular monolith and existing `8777/8766` contracts.
- `/account/{login}` remains the server-rendered legacy detail page.
- New business logic belongs in application/domain code. Only `legacy_bridge.py` may load copied legacy code.
- Remote MySQL and MT providers are read-only. Never perform MT4/MT5 Manager mutations.
- Preserve old aliases, Chinese JSON fields and compatibility responses unless a deprecation completed.

## Generated artifacts and checks

After documentation/API edits run:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\generate_governance_artifacts.ps1
```

During implementation run Fast verification; before handoff run Full:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\verify_change.ps1 -Mode Fast
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\verify_change.ps1 -Mode Full
```

Before production restart, run the release script from the clean production checkout. It must
verify `main`, the fixed production root and a clean worktree. After startup, compare the release
manifest with `/api/meta` and run `scripts\verify_deployed_release.ps1`; readiness alone does not
prove that the intended commit is running. For the relationship workspace, the default
`/kuzu-risk` route is `focus-force`; `graph_type=galaxy` is explicit compatibility only.

Release mode requires the ignored local read-only ten-server fixture and explicit
`KDESK_ENABLE_LIVE_CONTRACTS=1`.

## Handoff

Report affected Feature IDs, behavior changed, documents/records updated, tests and exact results,
API/data/production impact, deployment performed or not performed, and rollback behavior.
