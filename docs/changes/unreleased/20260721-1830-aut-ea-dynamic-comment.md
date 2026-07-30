---
change_id: 20260721-1830-aut-ea-dynamic-comment
features: ["AUT-EA-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Resolve dynamic numeric EA comments

## Before and after

EA grouping treated every complete comment as a stable name. Account 2013674 uses comments such as
`@8@44968558@7`, where the middle number changes for every position. Every seed therefore matched
only its own account and the API returned a valid but incorrect empty result.

Strict `@number@number@number` comments now retain both fixed outer numeric segments and normalize
only the middle per-position number to `*`. Account 2013674 therefore resolves the `@8@*@7` group
across accounts 2010861, 2011815 and 2013674. Named EA comments and all existing copy/signal/origin
exclusions remain unchanged.
The current-account summary in each group is now sourced from the complete reconstructed member,
so it reconciles with the account detail row even when some matching positions export ExpertID 0.

## Impact

No route, request parameter, response field, local schema or remote data changes. Dynamic lookup
uses the indexed fixed prefix in MySQL and validates every returned comment against the complete
strict pattern before grouping. MT5 positions are still reconstructed from all execution deals so
realized profit includes closing rows whose displayed comment changed.

## Documentation updated

`BUSINESS_RULES.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md` and `ea-comment-profit.md`.

## Verification

Focused tests cover dynamic normalization, TP suffix normalization, the indexable query plan and
current-summary/detail reconciliation.
Fast verification passed governance validation, Python compilation and Ruff. Full verification
passed 227 Python/legacy tests, 11 frontend tests and the production Vue build. The post-restart
read-only production request completed in 1.455 seconds with no errors: `@8@*@7` contained 3
accounts and 1,406 closed positions; account 2013674 reconciled at 202 positions, 10.47 lots and
4,274.96 USD in both the group header and detail row. Browser acceptance confirmed the same values.

## Deployment and rollback

No migration is required. Deployment restarts only account service 8777; K-line service 8766 and
workers remain untouched. Rollback restores the previous EA grouping module and account-service
process; all SQLite and remote read-only data remain unchanged.

Production account service was restarted to PID 7216. K-line service retained PID 14072; both
readiness endpoints remained ready.
