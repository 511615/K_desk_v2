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
`AccountRelationshipNetworkService` is an application-layer composition service that consumes the
existing legacy-backed account, IP, Copy, EA and rebate payloads through that boundary, then returns
typed evidence entities and edges. The legacy detail HTML owns its graph interaction only; it never
calculates relationship risk, strength or a conclusion.
`KuzuRelationshipDemoRepository` is a separate read-only infrastructure adapter for a deliberately
isolated local graph-file trial. It is not a remote-data provider or a replacement for the legacy
relationship service; the standalone API validates its bounded traversal depth before the adapter
opens the local file.
`KuzuRiskGraphRepository` owns both the static local trial and the account-detail request-scoped
projection. The latter serializes only read-only source evidence into a temporary local Kuzu graph,
reads it back, then removes it. `AccountRelationshipRiskService` recursively obtains the next
account's source facts only while its propagated score meets the threshold; pure score propagation
remains in domain code. `AccountRelationshipExpansionCoordinator` owns one bounded background
expansion at a time and returns an in-progress snapshot for polling, so remote evidence discovery
does not occupy an account HTTP request. Discovery continues until the propagated threshold is met
or the existing 2,000-node/10,000-score-expansion safety limits apply; every parallel source has a
six-second wait budget and the MT5 shared-LastIP follow-up has a separately clamped three-second
budget. Accounts already proven to belong to the same current-LastIP cohort do not repeat that
lookup. `AccountRelationshipNetworkService` gives each legacy evidence source one shared execution
lane, so a timed-out EA, Copy or CRM call cannot accumulate a new orphan thread for every expanded
account. Same-CRM evidence uses a mapping-only legacy source; it does not retain complete dashboard
trade history for every expanded account. Relationship-only Copy and EA calls bypass the legacy
dashboard cache, so their per-account payloads can be released after graph evidence is composed.
For accounts already in a current-LastIP cohort, root-account EA/Copy evidence acts as the cohort
representative and sibling nodes skip those duplicate heavy reads while continuing CRM/LastIP
propagation. The explicit skipped coverage records this optimisation.
Kuzu is materialized only once after discovery, avoiding per-hop local graph allocation, but
native Kuzu execution runs in a short-lived, single-concurrency child process rather than 8777. The
parent terminates that child after four seconds and falls back to the same capped pure propagation
projection when it is busy or unavailable. Its request projection is capped at 400 entities / 1,200
relationships before native Kuzu writes. It also has 2,000-node and 10,000-score-expansion safety caps.
Cross-platform Toxic checks are an explicit, bounded high-priority source adapter.

## Compatibility boundary

- `/account/{login}` always renders the legacy account detail HTML.
- Existing URLs, parameters and JSON fields remain compatible.
- The Vue workbench may call native v2 APIs and legacy-backed analytics independently.
- Breaking behavior requires a documented deprecation and replacement before removal.

## Data and process ownership

SQLite is authoritative for ledger records, history, quick actions, observations and jobs. Remote
trade and CRM databases and MT quote terminals are read-only providers. Excel is import/export and
backup compatibility, not a second authority. See `DATA_AND_ROUTING.md`.

The dynamic copy-pool monitor is a read-only projection of local copier snapshots. The separately
executed producer versioned under `services/copy_pool_runtime` normalizes eleven logical routes
onto nine read-only physical trade sources, selects
account-product sleeves and owns independent source Position to Demo Ticket execution state while
remaining outside the 8777 process. Its application port is implemented by a filesystem infrastructure
adapter; the API composition root sanitizes client budgets, Ticket ownership and product exposure,
and limits private route projection to Login/platform/server identity plus an alias-based detail
link. The dedicated monitor does not own copier state and does not call MySQL, MT terminals or MT
Manager; the account-detail page no longer embeds a copy-experiment section.

## Evolution rule

New business behavior is implemented in application/domain code. Existing legacy behavior is
extracted one feature at a time with contract parity; no big-bang rewrite is allowed. Architecture
decisions are immutable records under `docs/ADR/`.

Platform rebate-churning keeps pure scoring and cross-account pairing in domain code, scan
orchestration behind an application repository protocol, and indexed read-only CRM/MT access in
infrastructure. Worker and API modules remain composition roots.

Platform bonus discovery follows the same boundary: application code owns candidate/deep
orchestration, infrastructure groups physical sources and validates CRM routes, and the existing
bonus-arbitrage domain service remains the sole scoring authority.

K-line symbol normalization, validation gates, partial-success semantics and gap segmentation are
pure domain/application behavior. The credential-free quote-source registry is infrastructure.
Legacy K-line scripts remain compatibility adapters for statement parsing, read-only MT5 M1 access
and standalone HTML generation; they consume native decisions and retain existing entry points.
