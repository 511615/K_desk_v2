# K_desk v2

K_desk v2 is the isolated modular successor to the active services in `D:\risk\K_desk_ai_dev`.
Production ports `8777` and `8766` are not modified during development. The v2 development services use:

- Account workbench: `http://127.0.0.1:8877`
- K-line service: `http://127.0.0.1:8866`
- Persistent worker: no listening port

## Architecture

```text
Vue/TypeScript -> FastAPI interfaces -> application use cases -> domain
                                      -> infrastructure adapters
                                      -> SQLite authoritative local state
                                      -> read-only MySQL / MT4 / MT5 sources
FastAPI -> persistent job table -> worker -> K-line / Toxic / AI adapters
```

The current implementation is retained under `legacy/` and can only be imported through
`LegacyBridge`. This is the strangler boundary: each analytics use case moves into `domain/`
and `application/` without changing the public URL or response contract.

## Development Setup

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_dev.ps1
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\snapshot_production_ledger.ps1
.venv\Scripts\python.exe -m kdesk.cli import-preview runtime\dev\import\problematic_accounts.xlsx
.venv\Scripts\python.exe -m kdesk.cli import-excel runtime\dev\import\problematic_accounts.xlsx
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\start_dev.ps1
```

The snapshot command only reads the production workbook. Development writes remain under
`runtime\dev`. Remote trade databases and MT5 integrations are read-only.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\health_check_dev.ps1
```

Use `?legacy=1` on v2 pages to compare against the complete legacy UI while panels are migrated.
The rollback script is guarded by the literal `ROLLBACK-KDESK` confirmation and must not be run
until an explicitly approved production cutover.
