---
change_id: 20260807-1500-aut-pool-001-open-path-safety
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: preserve safe source ownership and opening evidence

## Before and after

An MT4 partial close can replace its remaining open Ticket. Treating that replacement as a new
source Position could duplicate a Demo ticket or falsely reject a timely residual as stale. A
COMMENT-proven `from #<Ticket>` smaller same-direction residual now rekeys the existing private
ownership mapping and retains the original signal time.

Initial operational qualification also caused a healthy live loop to de-arm on an ordinary
short-lived reconcile drift. It now remains live after it has qualified once, while current route
coverage, duplicate-event and selected-source freshness failures continue to block new risk.
Each physical source retains its own connection, cursor and failure state, so one source's timeout
or residual-ticket migration cannot advance, merge with or authorize a sibling source.

Missing/deferred historical delay evidence now has the explicit conservative five-second runtime
budget. Cross-currency product spread gates use the selected Demo terminal's account-currency
one-lot profit calculation rather than assuming quote difference times contract size is USD.
Hourly discovery now collects through a separate read-only database object and connection set, so
its SQL work cannot hold the real-time poller's source locks. Results are generation-checked before
main-thread commit, and public status serialization is limited to one normal write per second.

The event stream retains its bounded event-time no-copy reason codes, and the explicit
`ACCMGlobal-Demo`/`StagedLive` minimum-lot override remains the only mode that disables the ordinary
same-direction product cap across supported products. Whole-portfolio stress, margin, ownership,
quote, delay and stop gates still apply.

## Impact

The change preserves customer-owned Demo Ticket isolation across MT4 residual Ticket replacement,
avoids a false live-state withdrawal during a transient reconcile drift, and keeps delayed or
cross-currency openings fail-closed under their corrected evidence. Remote trading/CRM reads remain
read-only. MT Manager is not used; only the separately authorized Demo execution path can send an
order.

Explicit Demo fast activation no longer imposes a timed entry-shadow observation window; a sleeve
can activate at the next healthy risk check. Daily rebuilding likewise has no fixed recovery wait
in that mode, while startup reconciliation and current hard health checks remain mandatory.

## Not included

This change does not claim a deep SQLite WAL/persistence redesign. Full private-state snapshots
remain the recovery authority around broker actions; a smaller WAL/checkpoint redesign remains
separate work.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing, business-rule, operations and test-strategy
authorities. Regenerated feature-registry and OpenAPI governance artifacts remain compatible.

## Verification

Producer regressions cover partial-close rekeying without a second Demo entry, post-qualification
reconcile-drift retention with current hard health gates intact, missing-delay five-second behavior,
account-currency spread conversion, source-isolated staleness, detached hourly collection, precise
event reasons and explicit-Demo minimum-lot behavior. Fast and Full verification are required
before promotion.

## Deployment and rollback

Promote from a clean verified development branch, then restart only the single Producer from clean
`main` while the Demo account is flat. Rollback restores the prior verified Producer commit; private
ownership state, public snapshots and the bounded event-reason contract remain compatible. No
database migration or MT Manager action is required.
