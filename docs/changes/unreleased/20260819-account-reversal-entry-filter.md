---
change_id: 20260819-account-reversal-entry-filter
features: ["ACC-SEARCH-001", "ACC-DETAIL-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Include MT5 reversal entries in account lookup

## Before and after

The MT5 trade query filtered the source rows to `Entry` 0/1 before conversion. Accounts whose
available evidence consisted of an out-by/reversal entry could therefore be reported as having no
orders even though the read-only deal table contained a trading event. The source query now includes
entries 2/3 and the converter retains them as zero-duration factual rows when no ordinary pair exists.

## Verification

Focused reversal conversion and source-query tests pass. No remote data is written.

## Impact

Only read-only MT5 account lookup and conversion coverage changes. Existing response fields and
selected-source routing remain compatible.

## Documentation updated

Updated `docs/features/account/account-search.md` and `docs/features/account/account-detail-legacy.md`.

## Deployment and rollback

Deploy with the normal clean production release. Rollback is the preceding commit and controlled
restart; no remote or trading state is modified.
