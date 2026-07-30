---
feature_id: FIN-REBATE-SCAN-001
title: Platform rebate-churning discovery
module: finance
status: active
apis: ["POST /api/rebate-churning/scans", "GET /api/rebate-churning/scans/{job_id}", "GET /api/rebate-churning/ibs/{environment}/{ib_id}"]
code: ["src/kdesk/domain/rebate_churning.py", "src/kdesk/application/rebate_churning_scan.py", "src/kdesk/infrastructure/rebate_churning.py", "src/kdesk/worker/runner.py", "src/kdesk/api/account_app.py", "frontend/src/components/RebateDiscoveryPanel.vue", "frontend/src/components/RebateTreeNode.vue", "frontend/src/rebateTreeRisk.ts", "frontend/src/pages/WorkbenchPage.vue"]
tests: ["tests/test_rebate_churning_scan.py", "tests/test_api.py", "tests/test_worker.py", "frontend/src/rebateTreeRisk.spec.ts"]
depends_on: ["FIN-REBATE-AUDIT-001", "FIN-REBATE-001", "JOB-RECOVERY-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Platform rebate-churning discovery

## Purpose and user entry

Discover recipient IBs with confirmed rebate income across all four CRM environments from the
workbench's `刷返佣发现` tab. The recipient IB is the risk subject; trading accounts are evidence contributors.

## UI and behavior

Fixed discovery tabs switch between market-pushing and rebate-churning. Rebate discovery defaults
to seven days and all environments, accepts at most 31 days, filters risk levels, shows durable
progress/cancellation/partial failures, and restores the latest job after navigation. The ranking
defaults to score 60 or above. `查看树` loads the expandable IB/customer/account tree. SVG export
contains financial hierarchy data but no score or risk-evidence fields.
The detail tree shares risk-level colors and the empty-descendant display toggle with account audit.
This recent-window discovery contract is independent of the account audit's full-history default:
discovery remains seven days by default and rejects windows longer than 31 days.

## API contract

Submission normalizes `start`, `end` and `environments` into a durable idempotency key. Polling
returns environment summaries, aggregate counts, ranked IBs and additive failure rows. The IB detail
endpoint accepts the same window and returns the reusable audit tree.

## Data, routing and read-only constraints

Candidate discovery reads `rebate_task_detail.create_time` in daily shards and retries a failed day
once as six-hour shards. IB batches use the covering IB/time index without silent truncation. MT5
deep evidence resolves exact deals to `PositionID`; MT4 reads exact tickets. No full-platform
second-level trade grouping runs. Every CRM and trade query is read-only.
Reusable IB detail reads keep bounded account/time predicates and do not force AC-only physical
index names when the selected route is the shared DBG MT5 schema.
DBG MT5 Live2 is an additional independent physical source and is validated through `crm_vn` code 5.

## Business rules and units

Only IBs with actual recipient rebate rows are assessed. Candidate rules only control deep reads and
never add score. Structure is the maximum of within-account pairing, high turnover and cross-account
pairing; economics, coordination, funding and counterevidence retain the 50/30/15/5/-20 model.
Cross-account pairs require different accounts and CRM customers, opposite directions, open/close
differences within two seconds and lot error within five percent. Each trade matches once. Rebate
presence alone is not suspicious. Small samples lower confidence but do not cap score.
Cent volume is normalized to standard-lot-equivalent exposure with a `0.01` multiplier before
candidate ratios and detailed scoring. CRM `rebate_task_detail.rebate_amount` is aggregated unchanged
for candidate economics, recipient-IB totals and hierarchy display; `usd_or_usc` does not scale it.

## Loading, empty and failure behavior

Empty environments contribute zero counts. Environment or IB failures produce a completed partial
result while successes remain available. Cancellation is checked between environments and IB
batches. Restart recovery uses the shared SQLite queue.

## Code and dependencies

Pure candidate, pairing and score rules are domain-owned. Application code orchestrates through a
repository protocol. Indexed MySQL reads are infrastructure-owned. API and worker only compose.

## Tests and acceptance

Tests cover raw USC rebate aggregation, the 31-day limit, all-environment default, no candidate
Top-N cutoff, different-client pairing, low-risk `630830`, partial failure and persistent API
submission. Full verification covers Python, Vue, OpenAPI and architecture contracts.

## Compatibility and deprecation

This is additive. Ports remain `8777/8766`; single-account audit and the legacy detail page remain
compatible. Rollback leaves queued data intact, though an older worker will not claim the new kind.
