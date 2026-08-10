---
feature_id: ACC-REL-003
title: Score-propagated Kuzu relationship investigation
module: account
status: active
apis: ["GET /kuzu-risk", "GET /api/kuzu-risk/graph", "GET /api/accounts/by-login/{login}/relationship-network"]
code: ["src/kdesk/api/account_app.py", "src/kdesk/api/kuzu_risk_page.py", "src/kdesk/application/relationship_risk.py", "src/kdesk/domain/relationship_propagation.py", "src/kdesk/infrastructure/kuzu_risk_graph.py", "src/kdesk/settings.py"]
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
its aggregate reaches the threshold. The seed account is bright red, expandable accounts progress
from red to lighter orange as score falls, and a retained non-expandable clue is green. A
relation-aware force layout uses wide node separation and combines multiple facts between a pair
into one edge; the relation label is displayed when the graph is zoomed in. The graph initially fits
the complete result, then supports pointer-centred mouse-wheel zoom and drag-to-pan. Selection shows
score, hop count, expansion status and evidence ledger. Scores are investigation priority, not a
fraud or trading conclusion.

## API contract

The primary path is `GET /api/accounts/by-login/{login}/relationship-network?threshold=1..100`.
The screen defaults to `include_toxic=false`; operators explicitly select the checkbox before the
high-cost cross-platform order match. It returns entities with `score`,
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
recursively reads relations while a node remains at or above the selected threshold. It is limited
to 100 discovered accounts and 12 seconds; each account evidence source has a six-second budget.
Toxic runs only for nodes at least 30 and has a two-check budget. The fixed 2,000-node and
10,000-score-expansion caps, source timeout or discovery budget set `truncated=true` rather than
claiming complete coverage.

## Loading, empty and failure behavior

The page shows Kuzu loading status and aborts browser waiting after 45 seconds with actionable retry
guidance. Low-score nodes remain inspectable but do not expand. Missing static trial data does not
trigger a remote scan. Invalid graph shape and Kuzu failures do not expose internal paths or exceptions.

## Code and dependencies

`relationship_propagation.py` is pure scoring, `relationship_risk.py` composes source facts, and
`KuzuRiskGraphRepository` owns temporary/static Kuzu reads. Canvas uses DOM `textContent` for data
and never injects evidence as HTML.

## Tests and acceptance

Unit tests cover recursive source expansion, one final Kuzu materialization, source timeout handling,
threshold stopping, noisy-OR, de-duplication, cycles, same-IP and Toxic evidence ledger construction,
and risk colour. Repository tests cover request-scoped Kuzu materialization/readback. API tests cover
account-route replacement, page request targeting and invalid thresholds. Source tests use mocks; they
make no live writes.

## Compatibility and deprecation

The former relationship button view/response is replaced at the user's request. The standalone
Kuzu demo, account route, Copy, EA and Toxic contracts remain available.
