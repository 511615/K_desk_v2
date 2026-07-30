---
change_id: 20260730-2300-aut-copy-pool-public-csv-schema
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Version public append-only CSV schemas

## Before and after

The Producer appended rows using each row's current field list without validating an existing CSV
header. A prior `events_public.csv` header could therefore retain fewer columns after a producer
upgrade, causing dashboard `DictReader` values to shift by position. The generic helper exposed the
same risk to `orders_public.csv` and `status_timeline_public.csv`.

The Producer now validates each ordered public CSV header and every row width at startup before
restoring event counters or latency samples, and before every append. A non-empty mismatch is
atomically renamed in the same directory to a UTC-timestamped `schema-mismatch` archive. A new
current file receives the producer's exact header and subsequent row. The archived file is not
parsed as the live dashboard feed.

## Impact

The local public-snapshot format is self-healing across additive, removed or reordered columns.
Historical data is preserved byte-for-byte under the output directory for audit/recovery, while the
live UI reads only rows aligned to the current schema. No MT4/MT5 Manager operation, remote query,
order, account, API contract or port changes.

## Verification

Focused Producer tests cover header mismatch rotation, original-content preservation, a clean new
header/data file and current-file row counting. Fast verification runs the governed compile, lint,
documentation and focused Producer suite.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing authority and test strategy.

## Deployment and rollback

The change is source-only on `develop`; no runtime output file was modified. On first upgraded
Producer startup, only incompatible public CSVs rotate. Rollback retains the archived and newly
created files; restoring an old producer requires explicitly choosing which schema file it should
consume rather than merging files with different headers.
