---
change_id: 20260731-1217-aut-copy-pool-mt5-batch-terminal-state
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Execute the terminal MT5 Position state once per poll batch

## Before and after

MT5 Deals were applied and executed one at a time. When one 500 ms poll returned both a Position
opening and its completed close, the Producer opened 0.01 Demo lot and closed it about 52 ms later,
paying a spread for a source trade that had already ended.

The Producer now applies the full MT5 batch to source cursor, P/L and Position state first, then
executes one transition per account/product/Position. A pre-batch-flat and post-batch-flat round trip
emits `batch_terminal_flat` evidence without a Demo order. Residual exposure executes once, and a
same-batch reversal measures entry latency from the first opposite risk-increasing Deal. Terminal
transitions are persisted before broker execution, reductions run before additions, failed items
remain pending and coalesce with later events during the process, and independent siblings continue.
After restart only risk reductions resume; unfilled opens are monitor-only and reversal entries are
not chased. Invalid pending state hard-stops startup.

## Impact

Short source round trips already completed before observation no longer create guaranteed spread
loss. Cursor advancement, source realized P/L, dynamic weights, close management and exact Ticket
ownership remain intact. No remote database or MT Manager write is introduced; the only order path
remains the authorized MT5 Demo client API.

## Verification

Regressions cover a complete same-batch round trip with no execution call and correct source P/L,
two opening Deals with one residual execution, a close-plus-opposite-open reversal using the opposite
entry timestamp, reduction-before-addition ordering, failure continuation/pending recovery and the
distinct expired-residual disposition. Restart tests cancel new risk, retain reversal risk release
and reject malformed pending journals.
Full verification covers application, legacy, Producer and frontend suites plus production build.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing authority, business rules, operations and test
strategy.

## Deployment and rollback

Keep the Producer stopped while deploying. Promote only after Full verification on `develop` and
`main`, confirm the Demo is flat, then restart from clean `main` without `-ForceRebuild`. Rollback
stops the Producer and returns to the prior code, but the prior version must not run with live Demo
authorization because it can copy an already completed MT5 round trip.
