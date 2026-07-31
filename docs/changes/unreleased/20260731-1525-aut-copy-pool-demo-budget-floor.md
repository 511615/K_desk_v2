---
change_id: 20260731-1525-aut-copy-pool-demo-budget-floor
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Align Demo minimum-lot and client loss budgets

## Before and after

The explicit Demo minimum-lot override could open 0.01 lot for a tiny-weight active client while
that client's stop allowance remained only a few cents. Normal client-risk refresh could therefore
close the copied Ticket long before the source position closed, turning a valid natural signal into
an artificial early-loss sample.

Under the existing explicit `ACCMGlobal-Demo` and `StagedLive` minimum-lot switch, an active
client's loss allowance is now floored at the existing 20% per-client share of the 1.5% cycle
budget. Default execution, other servers or modes and zero-weight monitor clients are unchanged.
Portfolio cycle/daily stops, margin, cluster, spread, quote, source-health and ticket-ownership gates
remain authoritative.

## Impact

Minimum-lot Demo samples can remain open long enough to follow their source lifecycle, so copied
performance is not dominated by a sub-dollar client stop created by lot quantization. The change is
limited to the already explicit Demo experiment path. Remote databases and MT Manager remain
read-only; only the authorized MT5 Demo client execution path may write orders.

## Verification

Focused regressions cover a tiny active weight, default compatibility, a 0.69 USD copied loss and
server/mode scoping. Fast and Full governance verification are required before promotion.

## Documentation updated

Updated AUT-POOL-001 current state, business rules, operations and test strategy.

## Deployment and rollback

Deploy only from verified `main` while the Demo account is flat and has no pending orders. Keep the
8777 service running, restart only the Producer, confirm the same-day all-route pool is restored and
verify that restart creates no replacement order for an old source position. Rollback stops the
Producer, restores the prior main commit and restarts only after another flat-account check.
