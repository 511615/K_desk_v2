---
change_id: 20260806-1110-fin-history-001-mt5-daily-anchor-fallback
features: ["FIN-HISTORY-001", "ACC-DETAIL-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# FIN-HISTORY-001 MT5 daily-anchor timeout fallback

## Before and after

DBG GB MT5 account 3066617 could read its deal ledger but returned HTTP 503 because an unindexed
`mt5_daily_view` history query timed out. The endpoint now avoids that online full-view scan, keeps
the complete indexed deal ledger and current account state to calibrate balance/Credit, and marks
historic equity snapshots as unavailable.

## Impact

No remote or local data is written. The response adds explicit daily-anchor coverage fields and a
current-account reconstruction mode. A genuine source failure remains HTTP 503 but now returns a
sanitized `error` field, so the legacy page does not show only a raw HTTP status.

## Documentation updated

Updated FIN-HISTORY-001 plus the data-routing, finance-rule, API and test authorities.

## Verification

Domain fixtures cover current-account calibration; API fixtures cover safe 503 responses. Production
read-only acceptance uses DBG GB MT5 3066617 and confirms a complete timeline without daily equity
history.

## Deployment and rollback

The change is additive and requires only an account-service restart. Rollback restores the prior
daily-snapshot-required behavior; it has no data migration or persisted feature state.
