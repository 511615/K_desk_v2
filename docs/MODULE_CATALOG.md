# Module catalog

| Module | Responsibilities | Current implementation | Feature namespace |
| --- | --- | --- | --- |
| Account | Search, source selection, legacy detail page and evidence-only relationship network | FastAPI composition + LegacyBridge | `ACC` |
| Ledger | Account marks, history, quick actions, Excel compatibility | native domain/application/SQLite | `LED` |
| Finance | Balance, deposits, costs, rebates, comprehensive P/L | governed legacy analytics | `FIN` |
| Trades | Orders, metrics, hierarchy and database summaries | governed legacy analytics | `TRD` |
| Automation | Copy origins, follower profit, EA comment groups and dynamic copy-pool execution | governed legacy services + separate versioned Producer | `AUT` |
| Toxic | Detector selection, market-pushing analysis, evidence | persistent job + governed legacy rules | `TOX` |
| Login IP | Latest database IP and local observations | legacy adapter + SQLite | `IP` |
| K-line | Upload and database chart generation | FastAPI + persistent worker | `KLN` |
| AI | Provider-backed analysis of generated evidence | worker adapter, partial | `AI` |
| Jobs | Durable queue, progress, events, retry/cancel/recovery | native SQLite + worker | `JOB` |
| Governance | Feature registry, documentation, contracts and release gates | scripts/tests/docs | `GOV` |

Each independently changeable user behavior receives a Feature ID and a document under
`docs/features/<module>/`. The registry is generated from those documents.
