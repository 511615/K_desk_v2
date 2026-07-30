---
change_id: 20260729-1600-aut-copy-pool-independent-execution
features: ["AUT-POOL-001", "ACC-DETAIL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Cross-product independent customer execution

## Before and after

The producer previously reduced customer signals to one net target per product. It now selects
account-product sleeves across every supported Demo product and requires 20-day closed trading net
plus current same-product floating P/L to be strictly positive before later quality and risk gates.

Execution ownership is now `account + source Position -> one or more Demo Tickets`. Opening,
increasing, reducing, closing and reversing a source Position affect only its mapped Demo Tickets.
Opposing customers remain open independently. The combination layer may reject or reduce new risk,
but never closes one customer with another customer's event.

## Impact

The existing `8777` customer-pool projection and compatible legacy account page expose the new
account-product detail without adding a port, a public write endpoint, or a remote database write.

## Risk and recovery

Base sleeve weights total 100%. The 1.5% combination cycle-loss budget, 3% daily stop, per-client
loss budget, 20% client risk cap, 40% product-direction cluster cap, 15% soft and 25% hard margin
limits remain separate from weights. Client losses use Demo realized plus floating P/L after
commission, fee and swap. Loss-budget use follows the 20/50/80/100% reduction curve; exhaustion
closes only that client, pauses two hours and requires 15 minutes of recovery shadow.

Existing source positions at startup and positions first observed during shadow are never chased.
Twelve-hour positions cannot add copied risk; 24-hour positions close the client's copies and pause
the client. Restart requires every strategy Ticket to have a persisted owner and every persisted
Ticket to exist in MT5. Exact opposing gross positions remain visible and enter outage, Friday and
hard-risk flatten checks even when their net is zero.
Closed source mappings remain for the current trading day so their realized Demo P/L continues to
consume the originating client's allowance; the next trading day prunes only empty closed mappings.

## UI and API

The existing 8777 dashboard additively exposes account-product sleeves, client budgets,
independent source positions, Demo Ticket mappings and per-product long/short/net/locked exposure.
The legacy account detail page has a `复制实验` section using Login plus platform/server identity.
Its independent execution states and rejection reasons are localized in Chinese.
No new port or write endpoint is added.

## Documentation updated

The AUT-POOL-001 current-state documentation and test strategy record independent account-product
ownership, the dashboard projection, compatibility expectations and the replay/restart acceptance
coverage.

## Deployment and rollback

All AC/DBG database access remains read-only. MT4/MT5 Manager is not used. The old live copier stays
stopped. Deployment starts only the existing 8777 service and the producer in Shadow; Demo order
authorization remains disabled until replay, restart and zero-cross-customer-modification acceptance
passes. Rollback stops the Shadow producer, restores the prior code and snapshots, and does not
alter databases or MT account state.

## Verification

- Producer tests cover old-position suppression, open/increase/reduce/close/reverse semantics,
  exact A/B Ticket ownership, client loss curves, Cent conversion, all-route cursor behavior and
  1.5%/3% risk limits.
- K_desk tests cover sanitized account-product projection, client budgets, Ticket mappings,
  exposure totals, account detail compatibility and Chinese UI labels.
- Full governance and browser acceptance results are recorded at handoff.
