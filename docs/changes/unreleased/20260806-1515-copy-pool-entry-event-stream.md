---
change_id: 20260806-1515-copy-pool-entry-event-stream
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Copy-pool entry event stream

## Before and after

The scheduling event stream displayed every source Position transition, including closes for
positions that had never owned a Demo Ticket. Operators could therefore interpret a source exit as
an un-followed opening. The stream now shows source opening entries only. The dashboard API still
retains the complete event ledger, and source closes remain visible in current-copy/history views
where they are meaningful.

Source events also expose a sanitized `decision` code so the UI distinguishes active execution,
monitor-only, expiry and risk rejection instead of using the generic “source position updated” text.
When a new Demo entry is blocked, the persisted position state now records a bounded sub-reason
(`stale_quote`, `spread`, `database_stale`, `external_position_conflict`,
`operational_gates` or `manual_or_terminal`) so a missed entry can be diagnosed without exposing
private runtime data.

The Demo minimum-lot override no longer restricts a product-direction to one source Position. Each
eligible source Position may receive its own minimum lot while the total portfolio, product-direction
cluster and margin constraints remain available.

## Impact

The 8777 dashboard response adds an additive sanitized `decision` field on event rows. The producer
continues to read all sources and preserves complete events on disk. In the Demo-only override mode,
independent same-direction source Positions can now open their own minimum lots when shared risk
capacity is available.

## Documentation updated

Updated the AUT-POOL-001 feature state and the production operations runbook to define the
entry-only event stream and the cluster-limited, per-source Demo minimum-lot behavior.

## Verification

Focused backend snapshot tests and the CopyPoolPage Vitest suite cover the additive decision field
and suppression of source-only close events. Independent-execution tests cover multiple
same-direction minimum-lot owners and stable reconciliation.

## Deployment and rollback

The change is prepared on the `develop` worktree only. The running 8777 service and Producer are
unchanged until the develop Full verification and controlled promotion to `main` complete. Rollback
is the previous `AUT-POOL-001` build; no snapshot or Demo state migration is required.
