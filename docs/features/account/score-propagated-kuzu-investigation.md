---
feature_id: ACC-REL-003
title: Score-propagated Kuzu relationship investigation
module: account
status: active
apis: ["GET /kuzu-risk", "GET /api/kuzu-risk/graph", "GET /api/accounts/by-login/{login}/relationship-network"]
code: ["src/kdesk/api/account_app.py", "src/kdesk/api/kuzu_risk_page.py", "src/kdesk/application/relationship_expansion.py", "src/kdesk/application/relationship_risk.py", "src/kdesk/domain/relationship_propagation.py", "src/kdesk/infrastructure/kuzu_risk_graph.py", "src/kdesk/settings.py"]
tests: ["tests/test_api.py", "tests/test_kuzu_risk_graph.py", "tests/test_relationship_propagation.py", "tests/test_relationship_risk.py"]
depends_on: ["ACC-REL-001", "ACC-REL-002", "TOX-POSITION-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-10
---

# Score-propagated Kuzu relationship investigation

## Purpose and user entry

`/kuzu-risk?account={login}` is the account-detail relationship investigation screen. It reads the
replaced relationship endpoint, materializes returned evidence in a temporary Kuzu projection, and
renders scored relationships. Without `account`, it still supports the separate static local-file
trial.

## UI and behavior

There is no fixed hop limit: a node is visible when it has a contribution, but forwards only when
its aggregate reaches the threshold. The overview projects account nodes only into concentric rings
by their logical account-depth and keeps each strongest evidence family in an angular sector. It
shows the selected account's ancestry path rather than all edges. The lower detail view exposes that
account's relationship families, evidence and peer accounts. It explains each layer as an account-to-
account business route from the problem account. A direct subject-to-account evidence edge takes priority
over a longer ledger route in that presentation. For `直属上级 IB 本人交易账户`, the peer list is
strictly the selected account's immediate `ib_direct_account` peers; accounts that merely share the
same parent IB remain in their actual evidence family. Each evidence-family selector carries a
relationship-specific explanation instead of a generic secondary-clue label. The seed account is bright red,
expandable accounts progress from red to lighter orange as score/depth falls, and a retained
non-expandable clue is green. The overview supports pointer-centred mouse-wheel zoom and drag-to-pan.
Scores are investigation priority, not a fraud or trading conclusion.

## API contract

The primary path is `GET /api/accounts/by-login/{login}/relationship-network?threshold=1..100`.
The screen defaults to `include_toxic=false`; operators explicitly select the checkbox before the
high-cost cross-platform order match. It returns `inProgress` and processed/pending account counts
while the single-flight background expansion runs, then entities with `score`,
`hops`, `expandable`, `riskLevel`, `riskColor`, and
`scoreLedger`, alongside coverage and truncation. `GET /api/kuzu-risk/graph?threshold=1..100`
remains a static local-file trial. Invalid thresholds are rejected and Kuzu failures are sanitized.

## Data, routing and read-only constraints

Account requests reuse the governed read-only payloads and briefly write only a temporary Kuzu
projection, which is closed and removed before response. The static trial path is selected by
`KDESK_KUZU_RISK_DB`, defaulting to `runtime/<profile>/relationship_risk_graph.kuzu`. Neither path
writes AC, DBG, MT4, MT5, CRM or K_desk SQLite. Projections exclude authentication fields, API
blobs and unnecessary contact/KYC data.

## Business rules and units

Seed score is 100. An edge forwards `residual × relation strength × 0.96`; duplicate evidence in a
family retains its maximum, while independent families combine with noisy-OR. Same CRM is `0.95`,
current LastIP `0.90`, EA and Copy order `0.80`, Copy group `0.75`, rebate `0.70`, Toxic same/open
close sync `0.78`, Toxic opposite sync `0.82`, same name `0.35`, unknown `0.30`. The live path
recursively reads relations while a node remains at or above the selected threshold. It has no
request-wide timer or shallow-hop limit; the 2,000-node and 10,000-score-expansion safety caps are
the only graph-wide stops. Each account evidence source has a six-second wait budget.
Toxic runs only for nodes at least 30 and has a two-check budget. Each evidence read has its own
six-second source timeout; a source failure is retained in coverage but does not stop later eligible
accounts. A started same-server `LastIP` follow-up has a separate three-second maximum wait. The
result is produced by one local background expansion and equivalent page polls join it instead of
launching duplicate scans. Accounts in the same current-LastIP cohort skip repeat LastIP reads.
Each legacy evidence family has one shared local execution lane, preventing timed-out sources from
accumulating unbounded worker threads. The fixed 2,000-node and 10,000-score-expansion caps set
`truncated=true` rather than claiming complete
coverage. The final request-scoped Kuzu projection is additionally capped at 400 entities and 1,200
relationships, ordered by subject then propagated investigation score; cap application also sets
`truncated=true`. Kuzu's native temporary graph is executed in one short-lived child process at a time,
with a four-second hard deadline. A busy, failed or timed-out child is terminated and the server returns
the same capped result from the pure propagation scorer with a `kuzuProjection` coverage failure instead
of retaining native Kuzu memory in the 8777 process.
CRM hierarchy adds explanatory ownership/direct-parent/top-group bridges at `0.05`; these preserve
the auditable path without allowing a large distribution tree to amplify risk. The separately verified
direct-IB-owned trading-account edge is `0.60`, so that account may be investigated normally. A top-IB
aggregate never emits all downline accounts: a downline account appears only through a separate
independent evidence family already governed by this scorer.

## Loading, empty and failure behavior

The page shows Kuzu loading status, polls the background snapshot and reports processed/pending
accounts. Low-score nodes remain inspectable but do not expand. Missing static trial data does not
trigger a remote scan. Invalid graph shape and Kuzu failures do not expose internal paths or exceptions.

## Code and dependencies

`relationship_propagation.py` is pure scoring, `relationship_risk.py` composes source facts,
`relationship_expansion.py` bounds the single-flight background job, and
`KuzuRiskGraphRepository` owns temporary/static Kuzu reads. Canvas uses DOM `textContent` for data
and never injects evidence as HTML.
`AccountRelationshipNetworkService` obtains the routed CRM hierarchy payload through the existing
read-only legacy boundary. Same-CRM edges use its mapping-only legacy payload instead of a full
trade-history dashboard read. Relationship-only EA and Copy reads bypass the dashboard result cache,
and its aggregate query runs only for the seed account in one request.

## Tests and acceptance

Unit tests cover recursive source expansion through its score threshold, one final Kuzu materialization,
single-flight pollable progress, redundant same-IP cohort lookup avoidance, bounded same-IP timeout,
Kuzu projection caps and process timeout termination, threshold stopping, noisy-OR, de-duplication,
cycles, same-IP and Toxic evidence ledger construction, and risk colour. Repository tests cover
request-scoped Kuzu materialization/readback.
API tests cover account-route replacement, page request targeting and invalid thresholds. Source tests use
mocks; they make no live writes.

## Compatibility and deprecation

The former relationship button view/response is replaced at the user's request. The standalone
Kuzu demo, account route, Copy, EA and Toxic contracts remain available.
