---
change_id: 20260722-2359-tox-position-filters-and-complete-hedge-queries
features: ["TOX-POSITION-SCAN-001", "TOX-POSITION-001", "TOX-HEDGE-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Add position filters and complete dense synchronized-order queries

## Before and after

The full-platform heavy-position page previously exposed only time, environment, deep limit, result
level and handled-account controls. Operators can now optionally require a minimum position percentage,
peak lots and event net profit, then reorder the returned rows by profit, position or score. Blank
thresholds retain the prior behavior.

Dense synchronized-order sources previously failed coverage when one 25-target opening query reached
20,000 rows even if each target window was individually safe. The adapter now recursively splits only
equivalent target windows, then recursively splits only the saturated target batch and merges its
complete de-duplicated result. The existing opposite-direction
80% lot-similarity rule remains unchanged in both account and full-platform queries.

MT5 now checks candidate openings against the target symbol, five-second window and applicable
direction/lot rules before loading complete Position deal histories. This preserves the final matcher
while avoiding expensive completion reads for candidates that cannot possibly qualify.
The dedicated query also pushes canonical symbol prefix, opposite direction and the equivalent
80%-125% peer-lot interval into each indexed opening-time SQL clause, so non-qualifying rows are not
transferred from MySQL before the same in-memory and domain checks.

## Correctness and performance

Final filters use reconstructed event evidence and never alter scoring. Cheap candidate position and
lot estimates only prioritize likely matches within the configured deep queue. Sorting is client-side
over the completed task snapshot and causes no database request. Recursive query splitting is activated
only at the row ceiling and preserves the existing indexed five-second predicates and SELECT-only access.

## Impact

The scan submission payload adds three nullable fields, and completed results add filter metadata and
filter-count summaries. Existing payloads, jobs, account URLs, ports and result fields remain compatible.
No local or remote schema migration is required.

## Documentation updated

Updated the position-scan and cross-account-hedge feature documents plus business rules, data routing,
API and test authorities. Governance registry and OpenAPI snapshots are regenerated in the same change.

## Verification

Focused tests cover recursive saturation splitting, option validation, inclusive exact filters and the
three result sort modes. Final Full verification passed 276 Python/legacy tests, 18 frontend tests,
Ruff, Python compilation and the production Vue build, with the existing Starlette deprecation warning
only. Production browser QA confirmed the optional controls and client-side sort changes with no console
errors. AC GB MT5 account 639631 checked 2,619 closed target orders across 8/8 physical sources and
returned the same 13 suspected accounts/order pairs in about 28 seconds; the pre-SQL-constraint version
took about 581 seconds and returned the same result.

## Deployment and rollback

Rebuild the frontend and restart the account service and discovery/interactive workers. Rollback removes
the three optional controls and recursive split helper; no persisted job or database rollback is needed.
