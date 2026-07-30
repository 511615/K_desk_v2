---
change_id: 20260720-1230-fin-rebate-tree-lineage
features: ["FIN-REBATE-AUDIT-001", "FIN-REBATE-SCAN-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Correct rebate tree exposure and lineage

## Before and after

Cent-account lots were shown as raw platform lots, formal IB-owned trading accounts were excluded,
and account audit discarded supervisory CRM ancestors before the first `user_type=1` IB. The audit
now normalizes Cent lots by `0.01`, keeps IB-owned accounts on their owner node, and retains the
complete upstream relationship path. Risk-colored nodes and an empty-descendant display toggle make
the tree easier to review.

## Impact

Rebate tree financial totals, lot-dependent evidence and scoring, account/ancestor membership,
Vue node styling, display filtering and related tests. CRM rebate amounts and API field names do
not change.

## Documentation updated

Rebate audit/discovery current state, finance rules, routing/unit authority and test strategy.

## Verification

Tests cover Cent lot normalization, upstream supervisory display, IB-owned target accounts, risk
severity propagation and the empty-node predicate. Fast/Full verification and production browser
acceptance cover the complete change.

## Deployment and rollback

No migration, remote write or new port. Roll back the legacy rebate service and Vue tree files
together to restore the prior raw-lot and truncated-lineage behavior.
