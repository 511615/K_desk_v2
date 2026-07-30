---
change_id: 20260720-1430-fin-rebate-portable-mt5-index
features: ["FIN-REBATE-AUDIT-001", "FIN-REBATE-SCAN-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Use portable MT5 indexes for rebate detail

## Before and after

Detailed rebate-audit trade and cashflow queries forced the AC-specific
`idx_mt5_deals_Login_Time_Comment` index on every MT5 route. DBG account 3066186 routes to the shared
`mt5_export_new.mt5_deals` table, where that index does not exist, so the complete audit failed with
MySQL error 1176. The queries now retain bounded login/time and action/entry predicates while
allowing each physical schema to choose one of its available indexes.

## Impact

Single-account rebate audit and platform-discovery IB drill-down now work on DBG CN/GB MT5 as well
as AC MT5. Response fields, scoring, date semantics, ports and financial calculations are unchanged.

## Documentation updated

The rebate account-audit and platform-discovery feature documents, data-routing authority and test
strategy describe the portable index behavior.

## Verification

A regression executes both DBG MT5 SQL paths against a recording connection and rejects the
AC-only index name. Read-only live `EXPLAIN` for account 3066186 confirms that
`mt5_export_new.mt5_deals` selects its `ui_un` login-leading index instead of scanning the table.
Fast and Full verification cover the compatible change.

## Deployment and rollback

No migration, remote write, API change or new port. Restart `8777` and the rebate discovery worker
after deployment. Rolling back restores the DBG MySQL 1176 failure; local and remote data remain
unchanged.
