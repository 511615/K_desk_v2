---
change_id: 20260720-1130-acc-cross-server-same-name
features: ["ACC-DETAIL-001", "ACC-SEARCH-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Route same-name accounts across logical servers

## Before and after

Same-name discovery found the CRM user correctly but then restricted related accounts to the
selected account's `mt_server_code`. Account 241003365 therefore showed only four Live3 accounts
and omitted Live1 account 245856. Discovery now returns all accounts for the CRM user across server
codes and retains the route of every account.

## Impact

The legacy same-name panel count, server label, account finance values and totals. Each account's
trades, status, costs, finance and rebates are queried through its own configured read-only source.
Existing API paths and response fields are unchanged.

## Documentation updated

`DATA_AND_ROUTING.md`, `BUSINESS_RULES.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md` and
`account-search.md`.

## Verification

Unit tests cover cross-server CRM discovery and prove that Live1 and Live3 related accounts use
different trading sources. The full Python suite passed 155 tests, the legacy account suite passed
106 tests, frontend Vitest passed 4 tests and the production Vue build completed. Read-only
production acceptance for account 241003365 returned five same-name accounts: Live1 account 245856
and Live3 accounts 241003362, 241003363, 241003364 and 241003365.

## Deployment and rollback

No schema or local-data migration. Restart only account web service 8777 after Full verification.
Rollback this code and restart 8777; local SQLite and remote provider state are unchanged.
