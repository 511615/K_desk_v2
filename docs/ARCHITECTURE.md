# K_desk architecture

## Runtime

```text
Vue workbench / legacy account page
                 |
        Account FastAPI :8777       K-line FastAPI :8766
                 |                         |
                 +---- application -------+
                           |
                         domain
                           ^
                           |
                    infrastructure
                           |
       SQLite / files / read-only MySQL and MT quote providers

FastAPI -> SQLite job queue -> interactive/discovery workers -> governed adapters
```

K_desk is a modular monolith. It deliberately remains a single-host system and is not split into
microservices. Web services use one Uvicorn worker each; durable jobs are executed by separate
worker processes.

## Dependency rule

Dependencies point inward: `api|worker|cli -> application -> domain`; infrastructure implements
ports required by application/domain. API and worker composition roots may use infrastructure but
must not contain financial calculations. Domain code must not import HTTP, SQLAlchemy, filesystem,
MySQL or MT libraries.

`src/kdesk/infrastructure/legacy_bridge.py` is the only v2 module permitted to load code under
`legacy/`. This strangler boundary preserves the old account page and response contracts while
vertical features move into application/domain modules.

## Compatibility boundary

- `/account/{login}` always renders the legacy account detail HTML.
- Existing URLs, parameters and JSON fields remain compatible.
- The Vue workbench may call native v2 APIs and legacy-backed analytics independently.
- Breaking behavior requires a documented deprecation and replacement before removal.

## Data and process ownership

SQLite is authoritative for ledger records, history, quick actions, observations and jobs. Remote
trade and CRM databases and MT quote terminals are read-only providers. Excel is import/export and
backup compatibility, not a second authority. See `DATA_AND_ROUTING.md`.

## Evolution rule

New business behavior is implemented in application/domain code. Existing legacy behavior is
extracted one feature at a time with contract parity; no big-bang rewrite is allowed. Architecture
decisions are immutable records under `docs/ADR/`.
