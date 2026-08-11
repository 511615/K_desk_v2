---
feature_id: ACC-REL-001
title: Account relationship network
module: account
status: active
apis: ["GET /api/accounts/by-login/{login}/relationship-network"]
code: ["src/kdesk/application/relationship_network.py", "src/kdesk/application/relationship_risk.py", "src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["tests/test_api.py", "tests/test_kuzu_risk_graph.py", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-DETAIL-001", "ACC-SEARCH-001", "AUT-COPY-001", "AUT-EA-001", "AUT-FOLLOWER-001", "FIN-REBATE-001", "ACC-REL-003"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-10
---

# Account relationship network

## Purpose and user entry

The `关系网络` button on the legacy account-detail page now opens
`/kuzu-risk?account={login}` while retaining the current platform, server and symbol filters. The
previous in-dialog fact graph is no longer the visible account relationship interface.

## UI and behavior

The Kuzu page has a linked overview and detail view. The overview renders account nodes in concentric
rings by their logical account-to-account discovery depth, keeping descendants of the same strongest
evidence family in one angular sector. It shows only the selected account's path, instead of a full
edge web. Selecting an overview account updates the detailed account-to-evidence-to-peer view below.
The subject is bright red; other expandable accounts use a score-and-depth red-to-light-orange
gradient. A node retained as a clue but stopped by the propagation threshold is green. Operators can
use the mouse wheel to zoom around the pointer and drag the overview to pan. Scores are investigation
priorities only; they are not a fraud conclusion or an automated action.
For CRM hierarchy, a verified direct-parent IB user's own trading account is a real account peer and
is visible/expandable. A top-IB downline is rendered as one aggregate group with account/customer
counts; its members are not automatically emitted as account nodes or expanded from that group.

## API contract

`GET /api/accounts/by-login/{login}/relationship-network` accepts existing account filters and
`threshold=1..100` and optional `include_toxic=true`. It returns scored `entities`,
`relationships`, `relationTypes`, `summary`, source `coverage` and limitations. Each entity includes
score, colour, hop count, expansion state and score ledger. The former evidence-only response is
replaced by this contract.

## Data, routing and read-only constraints

The service first reads the selected account's bounded CRM, EA, Copy, rebate and login-IP evidence,
then reads each account whose propagated score still meets the threshold. For MT5 it also reads
same-server peers sharing the current `LastIP`. When the Kuzu page asks for it, high-priority nodes
are additionally checked through the existing all-platform Toxic synchronised open/close matcher.
It then writes only a request-scoped temporary Kuzu `Entity`/`Evidence` projection, reads it back
through Kuzu and removes it before returning. It never writes AC, DBG, MT4, MT5, CRM or K_desk SQLite.
The CRM hierarchy read resolves account-to-CRM-user, direct parent IB and accounts owned by that
direct IB user through the exact CRM schema/server route. It performs the potentially broad top-IB
aggregate only for the seed account; later score-eligible account reads retain direct-parent mapping
but omit repeated group aggregation.

## Business rules and units

The Kuzu scorer uses the ACC-REL-003 strength table and evidence-family de-duplication. Returned
money labels retain source currency and existing USD/USC normalization. The request scope has a
100-account and 12-second discovery safety budget. Each parallel source has a six-second budget;
late sources are returned as explicit partial coverage rather than blocking the page.
`discoveryTruncated` and `queryBudgetExhausted` report incomplete discovery. Every account evidence
read uses the lesser of its six-second source budget and the remaining request-wide discovery budget,
so a late source cannot extend a near-complete request by another full source timeout. Toxic checks are
restricted to nodes scored at least 30 and two cross-platform checks per request. A current `LastIP`
is a shared-login clue, not proof of shared device ownership or historical IP use.
CRM ownership and hierarchy bridge edges are explanatory and deliberately weak. The verified direct
IB-owned trading-account shortcut is separately scored and may expand; membership of a top-IB aggregate
alone never creates a downstream account candidate.

## Loading, empty and failure behavior

The destination page shows a Kuzu loading state and has a 45-second browser wait limit. It renders
the verified partial graph when the server query budget is reached. Independent source failure or
timeout does not hide available facts and remains in source coverage. A Kuzu failure returns a
sanitized unavailable response.

## Code and dependencies

`AccountRelationshipNetworkService` retains evidence composition.
`AccountRelationshipRiskService` passes that evidence to the request-scoped
`KuzuRiskGraphRepository`, while the pure domain scorer owns propagation. The legacy page only
navigates to the Kuzu page.

## Tests and acceptance

API and application tests pin recursive expansion, threshold stopping, same-IP and Toxic evidence
ledgers, score/colour output, typed evidence and partial coverage. Repository tests prove temporary
Kuzu materialization/readback. Legacy HTML tests pin button placement and navigation preserving filters.

## Compatibility and deprecation

The button remains at its existing location, but its view and endpoint contract are intentionally
replaced. Copy, EA and Toxic interactions are unchanged.
