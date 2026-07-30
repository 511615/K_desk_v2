---
change_id: 20260730-1440-aut-copy-pool-executable-weight-contract
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Align displayed and executable sleeve weights

## Before and after

Monitor-only sleeves could retain provisional source weights even when they were not activity
eligible or their dynamic sleeve state was zero. Producer status and the dashboard therefore showed
106% active weight and six active clients while the independent executor correctly refused every
new position.

Non-activity sleeves now contribute zero source and target weight. Hourly monitor-only entrants
receive zero execution base weight, producer status uses the final executable sleeve weight, and
the dashboard applies the same dynamic-sleeve cap before client loss-budget reduction.
`activeCopyClients` now counts clients with an actually active dynamic sleeve; the additive
`riskManagedClients` field retains the separate risk-ledger count.

## Impact

The 8777 page now matches the independent executor. No database query, customer selection hard
gate, Demo risk threshold, order behavior, MT account or Manager state changes.

## Verification

Producer tests cover non-activity source weights, targets and hourly monitor allocation. Dashboard
tests cover a positive private source weight capped to zero by a monitor dynamic sleeve. Producer
full verification passed 137 tests. K_desk Full passed 304 backend tests, 20 frontend tests, Ruff,
Python compile and the production frontend build.

A fresh Capital10k Shadow ran from 15:05 through 15:37 Beijing with 313 recorded status samples,
zero strategy lots, zero Demo Tickets, zero duplicate events and no runtime error. Reconciliation
reached 156 consecutive checks, all seven selected sources remained healthy, and both the 15-minute
rank and hourly discovery schedules completed. The post-discovery pool retained a 100% active base-
weight total and zero non-activity weight. Continuous Shadow was restarted after acceptance to keep
the 8777 dashboard current; Demo Live remained disabled.

## Documentation updated

Updated the AUT-POOL-001 current-state weight and active-client contract.

## Deployment and rollback

Rollback restores overstated UI/runtime weight labels and is not suitable for Shadow acceptance.
No migration exists; Demo Live remains disabled.
