# Migration Status

## Implemented

- Isolated development ports, runtime directories and Git repository.
- FastAPI account and K-line services with health and metadata endpoints.
- Vue/TypeScript workbench with independent account panels and legacy-page fallback.
- SQLite WAL schema, Alembic baseline, account/history/quick-action repositories.
- Excel preview, audited import, export and compatibility snapshot.
- Persistent jobs, events, cancellation, retry and restart recovery.
- Read-only legacy analytics bridge and read-only legacy chart discovery.
- Unit, API, safety, frontend, legacy regression and live contract checks.

## Required Before Production Cutover

- Extract finance, trade metrics, automation and Toxic calculations from `LegacyBridge` into domain/application modules.
- Complete Vue parity for Toxic controls, order paging, charts and all workbench tools.
- Add AI analysis jobs to the persistent worker and verify provider timeout/retry behavior.
- Run the representative MT4/MT5/USD/USC contract matrix and an approved rollback rehearsal.
- Obtain explicit human approval for the guarded production cutover script.
