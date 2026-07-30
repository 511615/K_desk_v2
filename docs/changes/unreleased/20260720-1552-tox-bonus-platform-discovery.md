---
change_id: 20260720-1552-tox-bonus-platform-discovery
features: ["TOX-BONUS-SCAN-001", "JOB-RECOVERY-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add platform bonus-arbitrage discovery

## Before and after

Bonus-arbitrage analysis was available only after an operator opened one known account. The
workbench now has a third discovery tab that locates recent positive Credit/Bonus recipients across
all logical servers, then runs the full historical cycle detector on a bounded ranked queue.

## Correctness

Candidate reads are daily and fall back to six-hour shards. Shared physical schemas are scanned
once and candidates are assigned only after CRM route validation. The candidate event never adds
risk score; full funding, trade, extraction, credit-removal and peer evidence remains required.
Handled accounts and minimum normalized grant values are optional pre-deep filters.

## Impact

Adds one durable Worker kind, three API endpoints and one workbench tab. Remote MySQL remains
read-only. No SQLite migration, port change, MT Manager action or existing response removal occurs.

## Documentation updated

Added `TOX-BONUS-SCAN-001`; updated job recovery, architecture, API, routing, business, operations
and test authorities.

## Verification

Focused Python, Ruff, Vitest and Vue build checks cover the new path. A bounded read-only AC GB MT5
query finds account 621928's exact 500 USD grant event before deep-cycle analysis.

## Deployment and rollback

Build the Vue bundle and restart the governed account/Worker processes only when no job is active.
Rollback restores the prior bundle and Worker code; unclaimed bonus-scan job rows can remain safely.
