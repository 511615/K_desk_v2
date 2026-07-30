---
change_id: 20260729-1100-aut-copy-pool-all-route-runtime
features: ["AUT-POOL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Connect the dynamic copy pool to every verified route

## Before and after

The Demo copier built its pool from fixed local TSV files for one DBG MT5 Live2 schema. Runtime
state used bare Login keys and one deal cursor, so adding shared physical schemas would have caused
cross-server identity and restart ambiguity.

The external producer now scans all eleven verified logical routes across nine read-only physical
trade sources. It uses composite account identity, route-backed ambiguity exclusion, indexed time
shards with recursive timeout subdivision, risk-history batches, independent source cursors, MT5
execution increments and MT4 current-position snapshots. A versioned accepted pool supports safe
same-day restart; an incomplete build cannot enter Demo execution. MT5 ledger actions advance the
physical-source cursor but cannot be interpreted as sell executions or change trading P/L.
Effective weights are persisted by composite account key; the dashboard no longer reuses a stale
same-alias event weight after the daily pool is rebuilt.
The mobile all-source grid now fits the page viewport while the wide account table remains locally
scrollable.

The K_desk dashboard additively shows the all-source funnel and runtime health, joins private
positions/P&L by composite key and preserves existing alias redirects and single-source snapshots.

## Impact

No listening port or remote write is added. AC/DBG credentials remain process-only. Rebates are not
queried, confirmed Cent money is normalized to USD, and MT/CRM adapters remain read-only. Demo order
authority is unchanged and still requires staged shadow gates plus the explicit launcher switch.

## Documentation updated

Updated AUT-POOL-001 and architecture, data/routing, business-rule, API, operations and test
authorities. Generated governance and OpenAPI artifacts are refreshed with the implementation.

## Verification

- External unit and failure-simulation suite: 37 passed.
- Forced read-only preflight: 30 clients, 11/11 logical routes, 9/9 physical sources, total weight
  0.25, maximum client weight 0.012511 and maximum route weight 0.049002; MT5 was not initialized.
- Short all-source Shadow: five consecutive zero-drift reconciliations, zero duplicate events, all
  nine sources healthy, maximum source age 0.156 seconds and poll-latency P95 0.313 seconds.
- Shadow strategy position remained zero and no order was added; Fast/Full and browser results are
  recorded before deployment completion.
- K_desk Fast passed. Full passed with 300 Python/legacy tests, 20 frontend tests and a successful
  production Vue build.

## Deployment and rollback

Deployment replaces only the external copier process and the account-service build on port 8777.
The prior single-source producer remains available as a code rollback target. Rollback stops the
multi-source copier only while the strategy is flat, restores the prior launcher/producer and
restarts the account service; no database, MT account or K-line migration is required.
