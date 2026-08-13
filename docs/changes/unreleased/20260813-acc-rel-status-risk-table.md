---
change_id: 20260813-acc-rel-status-risk-table
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Add database-status risk table to the relationship graph

## Before and after

The graph required visually finding every node with a handled risk-system status. The overview now
has a left-side `风险表` containing every rendered account whose routed database `Status` is `T`,
`TA` or `A`. It displays account, status, discovery layer and propagated score. Selecting a row
selects and highlights the corresponding existing node and path in the graph.

## Impact

This is the first, status-only risk item. It does not assign a new score, alter propagation, add
relationships, make extra database reads or write any local or remote system. An explicit empty state
is rendered when no current graph account has a `T`/`TA`/`A` status. The table is an extensible UI
container for later risk items.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- API page contract test verifies the risk-table container, T/TA/A status filter, renderer and
  selection integration are present.
- Inline JavaScript parsing and complete K_desk verification run before deployment.

## Deployment and rollback

Restart only the verified production account-service process bound to port 8777. Rollback is a
tracked-revision restart; no migration or data rollback is necessary.
