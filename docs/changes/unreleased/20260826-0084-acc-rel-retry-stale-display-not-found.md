---
change_id: 20260826-0084-acc-rel-retry-stale-display-not-found
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Retry a stale relation table on first not-found response

## Before and after

During the first live expansion, a visible raw relationship can be drawn from an early snapshot just
before the completed snapshot becomes active. The relation table refreshed on a 404 but immediately
showed “graph updated”, even when the same raw edge remained available after that refresh.

## Change

- Treat the first snapshot-bound 404 like a 409: refresh the graph, update the revision and retry
  the same raw edge once.
- Show the graph-synchronised notice only when the refreshed snapshot still cannot provide that edge.
- Keep all requests read-only and retain the existing bounded retry behavior.

## Impact

Client read-only recovery only. No relationship evidence, graph layout, account score, expansion
rule, API schema, database data or remote state changes.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Static API contracts require the first-404 refresh-and-retry branch.
- The deployed 216056 Galaxy browser regression must open a populated relation display table rather
  than a graph-update card.

## Deployment and rollback

Standard promotion/release. Rollback restores the prior client retry policy and needs no data repair.
