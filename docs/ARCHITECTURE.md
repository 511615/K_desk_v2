# K_desk v2 Architecture

## Dependency Rule

Dependencies point inward:

```text
api / cli / worker -> application -> domain
                          ^
                          |
                    infrastructure
```

- `domain` contains deterministic business rules and data models.
- `application` coordinates use cases and transaction boundaries.
- `infrastructure` implements SQLite, Excel, MySQL, MT5, files, IP and AI providers.
- `api`, `cli` and `worker` are composition roots. They do not implement risk calculations.
- `LegacyBridge` is the only module allowed to import the copied monolith.

## Runtime Processes

| Process | Development | Production after cutover | Responsibility |
| --- | ---: | ---: | --- |
| Account web | 8877 | 8777 | Vue assets, account APIs, ledger commands |
| K-line web | 8866 | 8766 | Uploads, artifacts, K-line job APIs |
| Worker | none | none | K-line, AI and Toxic long-running tasks |

All processes share the authoritative SQLite database. Web processes never create anonymous
background threads. Jobs and events remain visible after a restart.

## Data Ownership

- SQLite owns accounts, account history, quick actions, IP observations and jobs.
- Excel is an import/export format. `runtime/*/legacy_compat/problematic_accounts.xlsx` is a generated compatibility snapshot, not an authority.
- Remote MySQL and MT4/MT5 sources are read-only. No write method exists in v2 adapters.
- Development writes are restricted to `runtime/dev`; legacy chart output is mounted read-only.

## Migration Slices

1. Ledger, history and quick actions: native v2, completed.
2. Account API composition and Vue panel shell: native v2 with legacy analytics adapters, completed.
3. Finance, trade metrics and automation rules: covered by compatibility tests, extraction pending.
4. Toxic, hierarchy and copy analysis: covered by legacy tests, extraction pending.
5. K-line and AI internals: persistent v2 orchestration completed; generator internals remain behind the worker adapter.

No production cutover is allowed while a required slice is still marked pending.
