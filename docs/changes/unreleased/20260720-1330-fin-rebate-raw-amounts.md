---
change_id: 20260720-1330-fin-rebate-raw-amounts
features: ["FIN-REBATE-001", "FIN-REBATE-AUDIT-001", "FIN-REBATE-SCAN-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Keep CRM rebate amounts in source units

## Before and after

Single-account audit and the legacy platform-scan aggregation multiplied CRM rebate rows marked
`usd_or_usc=USC` by `0.01`. This disagreed with the established RiskDash calculation and understated
recipient-IB and hierarchy rebate totals. All rebate-churning paths now sum
`rebate_task_detail.rebate_amount` unchanged. The `usd_or_usc` column remains metadata only.

## Impact

Rebate totals, rebate economics and downstream rebate-churning scores for rows previously marked
USC can increase to their source values. Cent scaling for platform trading P/L, deposits,
withdrawals and standard-lot-equivalent exposure is unchanged. API field names and shapes do not
change.

## Documentation updated

The rebate display, account audit and platform discovery feature documents, finance business rules,
data/unit authority and test strategy now state the distinct CRM-rebate and platform-money units.

## Verification

Regression tests assert that a USC rebate amount is not currency-scaled while the existing Cent
trade-volume and platform-profit normalization remains active. Fast and Full governance checks
cover the complete compatible change.

## Deployment and rollback

No migration, port, API or remote write is introduced. Restart the `8777` account service and
rebate discovery worker after deployment. Rolling back restores the incorrect USC rebate scaling;
local and remote data remain unchanged.
