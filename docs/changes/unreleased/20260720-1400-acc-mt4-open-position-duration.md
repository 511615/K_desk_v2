---
change_id: 20260720-1400-acc-mt4-open-position-duration
features: ["ACC-DETAIL-001", "FIN-COMP-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Exclude MT4 open-position sentinels from closed analytics

## Before and after

MT4 uses `1970-01-01 00:00:00` as the close time for an open market position. The closed-trade
loader accepted those rows and subtracted the real open time from the sentinel. Account 5013015
therefore displayed a negative average holding duration, a `01-01` daily P/L bar, an inflated
closed-order count and current floating P/L duplicated into closed profit.

Previously, the loader counted these open-position rows as closed trades. It now requires a real
close time later than the open time, so only the account's 45 completed trades enter closed-order
analytics.

## Impact

MT4 closed-trade queries now require `CMD IN (0,1)` and `CLOSE_TIME > OPEN_TIME`. Row conversion
repeats the time-order validation so an adapter or fixture cannot reintroduce an invalid duration.
Current positions, position count and holding P/L continue to come from the current MT4 account
state and are unchanged.

## Documentation updated

`BUSINESS_RULES.md`, `DATA_AND_ROUTING.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md` and
`comprehensive-profit.md` document the sentinel rule and regression sample.

## Deployment and rollback

API field names, routes and the legacy page are unchanged. Values change only where an MT4 open or
invalid-time row was previously counted as closed. Rollback is the code-only removal of the query
predicate and converter guard; no local or remote data migration is involved.

## Verification

- Unit regression supplies one valid closed MT4 trade and one `1970-01-01` open-position row and
  requires only the closed trade to be returned.
- Live read-only acceptance for account 5013015 requires 45 closed orders, average holding 10.18
  minutes, winning average 8.31 minutes, losing average 25.19 minutes and no `01-01` daily bar.
- Full verification passed 162 Python/legacy tests, 9 frontend tests and the production build.
  After restarting only account web 8777, both services reported ready. The cold risk-panel read
  completed in 3.439 seconds with all expected duration values, 3 current positions and no 1970
  daily bar; the detail payload contained six daily bars from 2026-07-13 through 2026-07-20.
