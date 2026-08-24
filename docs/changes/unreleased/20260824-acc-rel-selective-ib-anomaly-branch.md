---
change_id: 20260824-acc-rel-selective-ib-anomaly-branch
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: change
status: unreleased
compatibility: compatible
---

# Selective direct-IB anomaly branch

- Replaced full direct-IB downline expansion with a two-stage, bounded anomaly projection.
- Includes database status `P/T/A/TA` regardless of rebate economics, plus rebate-dominated profitable
  accounts selected from the IB cohort.
- Applies one USD/USC money scale to both rebate and trading P/L before calculating combined profit
  and rebate share.
- Adds `异常 n / 直属返佣账户总数`, selected period, inclusion reasons and financial evidence to the
  IB/member graph contract.
- Preserves the auditable account → CRM owner → direct IB → selected member route; selected members
  continue normal score-based relationship expansion.
- Adds selector and graph-contract regressions; remote sources remain read-only and API fields are
  additive.

## Before and after

Before, an IB branch could expand every direct member. After, the branch first counts the cohort and projects only
status-significant or rebate-dominated profitable members, while retaining the auditable IB path.

## Impact

Reduces query and graph volume. Selected-member evidence is additive and the source databases remain read-only.

## Documentation updated

Updated both relationship current-state documents, business rules, routing, test strategy and this change record.

## Verification

Selector economics, status inclusion, money scaling, cohort counts and graph-contract regression tests cover the change.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back the release snapshot to restore the previous IB branch.
