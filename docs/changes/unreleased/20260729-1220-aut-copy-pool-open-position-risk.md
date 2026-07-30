---
change_id: 20260729-1220-aut-copy-pool-open-position-risk
features: ["AUT-POOL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Include current open-position risk

## Before and after

The all-route producer now includes current open-position count, gross/net XAUUSD exposure,
all-symbol gross lots, floating P/L, oldest open age, margin usage and hedge ratio in pool selection
and ten-second dynamic evaluation. Closed historical profit can no longer hide current floating
loss. Positive realized or floating P/L does not increase a base weight or offset a negative risk
component.

The localhost dashboard additively projects those values, distinguishes realized, floating and
dynamic P/L, shows a dedicated open-risk visualization and uses position count for the current-
position filter so zero-net hedges remain visible.

## Impact

All AC/DBG reads remain bounded and read-only. MT4/MT5 Manager is not used. Existing dashboard
fields, ports and account-detail links remain compatible. The producer cache version changes to
`copy-pool-multisource-v2-open-risk`, forcing a complete rebuild instead of accepting a snapshot
without current-risk fields.

## Documentation updated

Updated AUT-POOL-001 plus business-rule, data/routing, API, operations and test authorities. The
generated feature registry and OpenAPI snapshot are refreshed with the implementation.

## Deployment and rollback

Only the existing localhost 8777 service and external copier snapshot producer are affected. No
new service or port is added. Rollback restores the previous producer and dashboard files, removes
the additive fields and forces another all-route pool rebuild. It does not migrate local databases
or alter any MT account.

## Verification

- Producer unit tests: 15 passed, covering open-risk thresholds, positive-profit behavior,
  floating-loss dynamic reduction, zero-net hedge gross risk and restart persistence.
- Forced read-only preflight: 30 clients, 11/11 logical routes, 9/9 physical sources, 25% total
  base weight, maximum pool floating-loss ratio 0.1344% and maximum margin/equity 3.7825%.
- Main-output Shadow: four consecutive zero-drift reconciliations, no pending snapshot, no duplicate
  event, 0.234-second poll P95, zero strategy position and complete risk state for all 30 clients.
- K_desk focused tests: 4 backend and 20 frontend passed. Full verification passed with 301 Python/
  legacy tests, 20 frontend tests and the production build.
- Localhost browser acceptance passed at 1440 and 375 CSS-pixel widths with no page-level overflow,
  five current-position rows, local table scrolling and zero console warning/error entries.
