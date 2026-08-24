---
change_id: ACC-REL-019
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Repair galaxy ancestry when primary evidence is reciprocal

## Problem

The galaxy renderer used the first `scoreLedger` entry as a node's parent. Reciprocal evidence
such as same-CRM links can point two accounts at each other, creating a cycle. `graphNodes()` then
could not prove that the account reached the investigation subject, so the selected account's
complete path back to the centre was absent or its edges were filtered out.

## Change

The compatibility renderer now resolves ancestry with a deterministic breadth-first search over
the returned account/IB evidence graph. Ledger contributions are used only to order equivalent
neighbours; they are no longer an unconditional parent pointer. Relationship labels for path
segments use the evidence edge that actually connects the two route accounts.

This is presentation-only. Discovery scores, source queries, database schemas and the legacy
relationship API contract are unchanged.

## Verification

- Python compilation of `kuzu_risk_page.py` passed.
- Clone `8977` restarted from `K_desk_v2_rel_dev` and galaxy HTTP response returned `200`.
- The route search is bounded by the already returned snapshot and uses a visited set, so reciprocal
  same-CRM links cannot loop or add database work.

## Rollback

Revert this change record and the corresponding route override in the clone; production `8777` was
not changed or restarted.

## Before and after

Before, reciprocal evidence could create parent cycles and hide the route to the centre. After, bounded breadth-first
ancestry resolves a deterministic acyclic path over the returned snapshot.

## Impact

Presentation-only route correction with no new database work or API change.

## Documentation updated

Updated `ACC-REL-003` current-state route behavior and this change record.

## Deployment and rollback

Promote through dev to main and restart the account service. The production release snapshot is the rollback unit.
