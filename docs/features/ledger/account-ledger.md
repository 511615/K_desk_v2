---
feature_id: LED-ACCOUNT-001
title: Account ledger and history
module: ledger
status: active
apis: ["GET /api/accounts", "POST /api/accounts/mark", "PUT /api/accounts/{record_id}", "GET /api/accounts/{record_id}/history"]
code: ["src/kdesk/domain/ledger.py", "src/kdesk/application/ledger_service.py", "src/kdesk/infrastructure/database.py"]
tests: ["tests/test_ledger.py", "tests/test_api.py"]
depends_on: []
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Account ledger and history

## Purpose and user entry

Maintain problem-account marks, status, action, group, tags, notes and ownership with immutable
history. Workbench and legacy detail page share this authority.

## UI and behavior

Users can mark, edit, batch mark and remove records; quick actions provide reusable values.

## API contract

Stable Chinese aliases are preserved in JSON while internal models use typed English fields.

## Data, routing and read-only constraints

SQLite is the sole authority. Excel is imported/exported with preview and audit; it does not
automatically synchronize back into SQLite.

## Business rules and units

Each update increments record version and appends history. Stable `record_id` identifies a record.

## Loading, empty and failure behavior

Conflicts and invalid imports fail explicitly without partial writes. Empty ledger state is valid.

## Code and dependencies

Domain models are persistence-independent; application coordinates repository and compatibility export.

## Tests and acceptance

Temporary SQLite tests cover create/update/history/delete, imports, aliases and API behavior.

## Compatibility and deprecation

Existing Chinese fields and workbook export shape remain supported.
