---
feature_id: ACC-REL-002
title: Kuzu local relationship graph demo
module: account
status: active
apis: ["GET /kuzu-demo", "GET /api/kuzu-demo/graph"]
code: ["src/kdesk/api/account_app.py", "src/kdesk/api/kuzu_demo_page.py", "src/kdesk/infrastructure/kuzu_relationship_demo.py", "src/kdesk/settings.py", "pyproject.toml", "requirements.lock"]
tests: ["tests/test_api.py"]
depends_on: ["ACC-REL-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-03
---

# Kuzu local relationship graph demo

## Purpose and user entry

`/kuzu-demo` is an isolated operator trial that demonstrates a persisted local Kuzu evidence graph
without changing the legacy account-detail page or its relationship-network implementation.

## UI and behavior

The page initially displays the two-hop graph and supports one, two and three-hop views. Operators
can hide individual relation types, pan/zoom, drag nodes and select a node or edge to inspect its
typed evidence. The page presents facts only and has no risk score, strength label or conclusion.

## API contract

`GET /api/kuzu-demo/graph?depth=1|2|3` returns only entities and evidence edges reachable from the
single graph subject in the local file. The depth is a whitelist, not an arbitrary graph-query input.
`GET /kuzu-demo` is a standalone no-store HTML page and does not appear in the existing workbench.

## Data, routing and read-only constraints

The local file is selected by `KDESK_KUZU_DEMO_DB`, defaulting to
`runtime/<profile>/relationship_graph_demo.kuzu`. It is a non-authoritative, operator-created
projection of existing read-only evidence. Reading the demo never contacts or writes AC, DBG, MT4,
MT5, CRM, SQLite ledger or MT Manager. A missing or unreadable file returns a local unavailable
response; it never falls back to a remote graph scan.

## Business rules and units

The demo preserves the evidence strings and money units already emitted by its source projection.
It does not calculate, normalize, aggregate or infer a risk relationship.

## Loading, empty and failure behavior

The page renders a local loading state while reading the file. Missing data returns HTTP 404; an
unreadable graph returns HTTP 503 without exposing a filesystem path or Kuzu exception to the page.

## Code and dependencies

`KuzuRelationshipDemoRepository` is a read-only infrastructure adapter. It opens the local Kuzu
file per request in read-only mode, releases the embedded file lock and returns bounded typed data.
The API layer validates depth and owns HTTP failure translation. Kuzu is locked as a Python runtime
dependency.

## Tests and acceptance

API tests create a temporary Kuzu file, close and reopen it through the API, verify a two-hop graph
has the expected nodes, edges and evidence, validate the standalone page, and reject depth four.
Production trial acceptance verifies the file for account 2013674, `18` entities and `18` edges,
then checks that one/two/three-hop local reads complete without a remote provider call.

## Compatibility and deprecation

This is additive and isolated. `/account/{login}`, the existing relationship-network endpoint and
all existing pages remain unchanged. The trial can be disabled by removing its local file or setting
`KDESK_KUZU_DEMO_DB` to an unavailable path; no ledger or remote data rollback is required.
