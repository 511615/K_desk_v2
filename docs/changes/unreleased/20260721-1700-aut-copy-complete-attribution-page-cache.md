---
change_id: 20260721-1700-aut-copy-complete-attribution-page-cache
features: ["AUT-COPY-001", "AUT-FOLLOWER-001", "AUT-EA-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Complete CPT attribution and page-local automation cache

## Before and after

MT5 reconstructed trade comments combined opening and closing CPT identifiers. The Copy query treated
both as source Position IDs, stopped after 1,000 identifiers, and scanned only the first 200 source
orders for follower profit. Account 641903 therefore showed only part of source 640598, failed to find
632824, and displayed a follower total that differed after per-position rounding.

The opening comment is now authoritative, origin IDs are resolved in complete batches, and follower
discovery uses exact indexed comments with complete Position aggregation by account. Independent
sources run concurrently and money remains at source precision through aggregation. Account 641903
now maps all 895 copy positions: 640598 has 625 positions and 439.89 USD; 632824 has 270 and 64.43 USD.

Successful Copy and EA dialog requests are also cached by normalized filters in the current browser
page. Closing and reopening a dialog causes no new request. Explicit account refresh clears both
caches; filter changes use a different key, page reload clears memory, and failures are retryable.

## Impact

No API path, required request parameter, response field or database schema changed. `copyChannels`
and `queryStrategy` are additive diagnostic fields. Remote MySQL remains read-only. The faster MT5
path returns account-level follower aggregates instead of transferring per-Position aggregate rows,
while preserving follower counts, source coverage, samples, symbols, times and profit components.

## Documentation updated

`BUSINESS_RULES.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md`, `copy-origin-query.md`,
`follower-profit.md` and `ea-comment-profit.md`.

## Verification

Focused tests cover opening/closing comment parsing, more than 1,000 origin IDs, batched source
lookup, more than 200 complete source orders, exact-comment SQL, the 625/270 assignment fixture,
profit reconciliation and Copy/EA page-cache reuse/invalidation. The live read-only cold benchmark
for 641903 returned 895 mapped, zero unresolved, no errors and complete follower summaries in 7.524
seconds; a second independent cold acceptance completed in 7.206 seconds with every invariant true.
Fast verification passed. Full verification passed 225 Python/legacy tests, 11 frontend tests and
the production Vue build. The production API cold request completed in 8.058 seconds with the same
895/625/270 counts and profits. Browser acceptance confirmed the legacy dialog values; after closing
and reopening, Copy origin/group request counts remained 2/1 and the EA request count remained 1.

## Deployment and rollback

No data migration is required. Deployment restarts only account service 8777; K-line service 8766
and workers remain running. Rollback restores the prior account-service code; SQLite and all remote
trade/CRM data are unchanged.

Production account service was restarted from PID 3912 to 16724. K-line service retained PID 14072;
both readiness endpoints remained ready.
