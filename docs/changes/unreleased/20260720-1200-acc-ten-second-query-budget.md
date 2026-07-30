---
change_id: 20260720-1200-acc-ten-second-query-budget
features: ["ACC-DETAIL-001", "ACC-SEARCH-001", "FIN-COMP-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Enforce the ten-second account query budget

## Before and after

The same-name panel synchronously queried the unindexed MT5 daily view to resolve currency. A new
Live1 account without a daily row forced a full view scan and made the five-account risk panel take
more than one minute. Interactive MT5 metadata now uses the indexed users view and group-derived
currency rules, so accounts with and without trades follow the same bounded path.

## Impact

Account lookup, detail finance and same-name risk panels. Response paths and JSON fields remain
unchanged. USC continues to use `0.01`; standard groups use USD unless their group explicitly names
another supported currency. Remote providers remain read-only.

## Documentation updated

`DATA_AND_ROUTING.md`, `BUSINESS_RULES.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md`,
`account-search.md` and `comprehensive-profit.md`.

## Verification

Tests prohibit MT5 metadata from accessing `mt5_daily_view`, cover standard USD and USC groups and
retain the cross-server source checks. Production acceptance clears the process cache and requires
the complete 241003365 five-account risk panel to return correctly in less than 10 seconds. Full
verification passed 158 Python tests, 6 frontend tests and the production build. A restarted
production process returned the complete five-account cold result in 3.424 seconds; ordinary
synchronous lookup/detail checks completed in 0.9 to 1.2 seconds.

## Deployment and rollback

No schema or local-data migration. Restart only account web service 8777. Rollback this code and
restart 8777; local SQLite and remote provider state are unchanged.
