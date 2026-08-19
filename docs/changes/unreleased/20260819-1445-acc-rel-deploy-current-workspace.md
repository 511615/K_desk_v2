---
change_id: 20260819-1445-acc-rel-deploy-current-workspace
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
title: Deploy the current relationship workspace instead of the legacy galaxy default
status: unreleased
compatibility: compatible
---

# Change

The `/kuzu-risk` route now defaults to the current center-constrained relationship workspace.
The original galaxy renderer remains available only through explicit `graph_type=galaxy`, while
unknown or stale graph-type values also resolve to the current workspace.

The current workspace is integrated with the production single-flight relationship expansion. It
polls the existing partial snapshots instead of issuing staged synchronous scans. The relationship
response adds a presentation-only relation-entity projection so repeated account pairs can be shown
as one auditable group. Account nodes preserve `databaseStatus`; only blank status is displayed as
`B`.

## Before and after

Before, a bare `/kuzu-risk` request returned the galaxy renderer because production loaded an older
`main` checkout. After, the bare route and unknown graph-type values return the current focus
workspace; the galaxy page requires `graph_type=galaxy`.

## Cause

The running 8777 process loaded `D:\risk\K_desk_v2_main` at a revision whose route still returned
`kuzu_risk_page.py` unconditionally. The newer workspace files existed only in a separate unmerged
worktree, so restarting production from `main` redeployed the legacy galaxy renderer.

## Compatibility and safety

- The existing relationship GET response fields remain unchanged; `presentationGraph` is additive.
- The galaxy URL remains available for explicit compatibility use.
- Existing background timeouts, single-flight expansion and read-only database behavior are retained.
- No AC/DBG, MT4/MT5, CRM or K_desk business data is written.

## Impact

The change affects account relationship page routing and presentation only. Existing API fields,
background expansion controls and read-only source adapters remain compatible.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`
- `docs/changes/unreleased/20260819-1445-acc-rel-deploy-current-workspace.md`

## Verification

- API tests pin focus as the default and unknown-value fallback.
- API tests pin explicit `graph_type=galaxy` compatibility.
- Presentation tests pin grouped edges, paths and database-status preservation.
- Deployment verification checks both route markers against the live 8777 process.

## Deployment and rollback

Deploy only after Full verification from the clean `main` checkout. Restart the account service from
that checkout and verify `/kuzu-risk` plus explicit `graph_type=galaxy` online. Roll back by
restarting the previous clean production revision. No schema or data rollback is required because
this change affects routing and presentation only.
