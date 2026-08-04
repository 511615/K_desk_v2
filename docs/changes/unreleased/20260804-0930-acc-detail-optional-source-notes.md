---
change_id: 20260804-0930-acc-detail-optional-source-notes
features: ["ACC-DETAIL-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# ACC-DETAIL-001: Make optional source notes non-blocking

## Before and after

The production account-detail endpoint could fail for every account when the optional legacy
`local_data/source_notes.txt` file was absent. The exception escaped during ledger loading and
returned HTTP 500, even though the persisted compatibility workbook remained available.
`read_source_text()` now returns an empty source text only for a missing file. It does not create
or modify the source file during a read request, and other filesystem failures remain visible.

## Impact

The existing account detail URLs and JSON response structure do not change. The change only
prevents an optional local source artifact from blocking read-only account detail access; it does
not write SQLite, Excel, remote databases, or MT4/MT5 state.

## Documentation updated

Updated the ACC-DETAIL-001 failure behavior to define the source-notes file as optional after
workbook initialization. The generated governance registry and OpenAPI contract are refreshed.

## Deployment and rollback

Deploy the one legacy registry module through the controlled localhost account-service restart.
Rollback restores the preceding module revision; no data migration or local-data restore is needed.

## Verification

The regression test replaces the configured source-notes path with a missing temporary file and
asserts that the read returns empty text. Production acceptance verifies account-detail API success
for representative accounts after restart.
