---
change_id: 20260720-1130-fin-rebate-platform-scan
features: ["FIN-REBATE-SCAN-001", "FIN-REBATE-AUDIT-001", "JOB-RECOVERY-001", "TOX-PUSH-001"]
change_type: addition
status: unreleased
compatibility: compatible
---

# Add persistent platform rebate-churning discovery

## Before and after

Rebate churning could only be audited from one trading account, while the legacy global prototype
used process-local threads and broad range aggregation. The workbench now has a durable discovery
tab that finds actual recipient IBs through sharded rebate reads, deep-reads exact deals/tickets,
pairs different customers in memory and ranks recipient IBs with the governed score model.

## Impact

Finance rules, read-only CRM/trade routing, discovery worker kinds, additive APIs, workbench tabs,
IB ranking/tree drill-down and score-free SVG export.

## Documentation updated

New finance feature plus rebate audit, persistent jobs, shared discovery UI, architecture, API,
data routing, business rules, operations and test authorities.

## Verification

Focused domain/API/worker tests, Ruff, Vitest, production frontend build, and Fast/Full governance checks.

## Deployment and rollback

No schema migration, scheduler or port is added. Deploy account web and discovery worker together.
Roll back those files together; existing audits and prior durable jobs remain compatible.
