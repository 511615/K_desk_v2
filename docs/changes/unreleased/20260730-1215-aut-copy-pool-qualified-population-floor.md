---
change_id: 20260730-1215-aut-copy-pool-qualified-population-floor
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Treat monitor size as a target, not a risk gate

## Before and after

The all-source producer previously rejected an otherwise valid pool whenever fewer than ten unique
clients survived every product, profitability, drawdown, holding and open-risk gate. That arbitrary
floor contradicted the ranking domain, which already treats 30 monitor clients as an upper target.

Preflight, cache restore and route loading now accept any non-empty fully qualified monitor
population. Zero qualified clients still fails closed. The producer reports the actual monitor,
reserve, sleeve and product counts; it never fills a shortfall by weakening hard gates. The
preflight completion message also states accurately that deferred V0.1 historical Tick replay does
not initialize the MT5 terminal.

## Impact

Small but genuinely qualified cross-product pools can reach Shadow validation. The public dashboard
continues to show actual counts and source coverage. No profitability, MDD, negative-equity,
stop-out, holding-period, margin, floating-loss or execution gate changes. No database, MT account,
order or Manager state changes.

## Verification

Producer tests cover acceptance of a non-empty eight-client population and rejection of an empty
population. Full read-only all-source preflight, K_desk Full verification and localhost dashboard
checks remain required before Shadow starts.

## Documentation updated

Updated the AUT-POOL-001 current-state feature document, business rules and architecture wording.
The execution-quality plan records the read-only preflight result and keeps Shadow as the next gate.

## Deployment and rollback

Deploy the producer and 8777 snapshot reader together. Rollback restores the ten-client process
floor but requires no data or MT migration. Shadow and Demo Live remain stopped until the current
preflight and Shadow acceptance chain succeeds.
