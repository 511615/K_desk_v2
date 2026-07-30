---
change_id: 20260730-2330-aut-copy-pool-multisource-csv-schema
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Canonicalize multi-source public CSV streams

## Before and after

The initial CSV schema repair gave `LiveService` fixed single-source event and order columns.
`MultiSourceLiveService` inherited those columns during `super().__init__`, which could rotate an
otherwise valid multi-source snapshot on restart. Its MT5 and MT4 events, and its independent and
product-level order paths, also had intentionally different field sets that could repeatedly rotate
a file between writes.

The base service now resolves public schemas through overridable class attributes. The multi-source
service supplies fixed event and order supersets before base initialization. Every append normalizes
absent allowed fields to empty cells and rejects unexpected fields. Header and row-width migration
continues to archive only genuinely incompatible historical files.

## Impact

Multi-source event/order snapshots remain column-aligned across MT5, MT4, independent execution and
product flattening. Existing correct multi-source files remain in place across restart. A legacy
16-column header with wider rows rotates once to the preserved timestamped archive and starts one
canonical live file. No remote write, MT operation, API contract, port or runtime deployment occurs.

## Verification

Focused regressions cover restart validation, MT5-to-MT4 event appends, independent-to-flatten order
appends and one-time legacy rotation. Full verification covers all application, Producer and frontend
tests plus the production build.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing authority and test strategy.

## Deployment and rollback

The change is source-only on `develop`; no runtime output was modified. The next multi-source
Producer start retains correctly headed canonical files and archives only incompatible files.
Rollback preserves archives and current snapshots; do not merge streams with different schemas.
