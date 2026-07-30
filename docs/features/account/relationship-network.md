---
feature_id: ACC-REL-001
title: Account relationship network
module: account
status: active
apis: ["GET /api/accounts/by-login/{login}/relationship-network"]
code: ["src/kdesk/application/relationship_network.py", "src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["tests/test_api.py", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-DETAIL-001", "ACC-SEARCH-001", "AUT-COPY-001", "AUT-EA-001", "AUT-FOLLOWER-001", "FIN-REBATE-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-29
---

# Account relationship network

## Purpose and user entry

The legacy account detail page exposes `关系网络` beside Copy and EA queries once the selected
account has database orders. It is generated only after the operator clicks the button.

## UI and behavior

The dialog shows an interactive evidence graph for same-CRM-user accounts, current-account login
IP observations, EA or route features, Copy origins/followers, Signal Copy groups and the current
account's CRM rebate record. Checkboxes hide an entire relation type without deleting data. Clicking
an aggregate EA or Copy node expands or collapses its members; clicking an edge or node presents its
source evidence. Every visible edge also carries a persistent, high-contrast relation-type label so
the graph remains readable without opening the detail pane. Nodes can be dragged, the canvas can be
panned/zoomed, and `恢复视图` resets the local layout and filters. One high-DPI native Canvas redraws on
`requestAnimationFrame`; pan and wheel zoom update its camera/layout state rather than applying a CSS
`translate3d`/`scale` transform to a Canvas texture. The stable graph is first drawn to a detached 3x
raster scene cache. Gesture frames copy that cache once with `drawImage`; a node drag overlays only the
active node and its incident lines/labels, then rebuilds the stable cache on release. Static invalidation
occurs only for filters, aggregate expansion, selection, reset or finished node movement. Label widths are
cached and visible-content culling remains available for dynamic overlays. Movement of four or more screen
pixels is treated as a drag and does not activate
a node or edge on release. Wheel deltas are coalesced, use continuous exponential scaling rather than
fixed zoom steps, and retain the world point under the cursor while zooming. Canvas hit testing preserves
node selection, edge selection, panning, relation-type filtering,
aggregate expansion and reset. The dialog intentionally provides no score, no strong/weak classification
and no risk conclusion. Successful results are cached in the current page memory per selected
platform/server/symbol/time filter and cleared only by detail refresh, filter change or reload.
Nonvisual Canvas `data-*` attributes expose latest frame, cache-build and input-to-paint timing for
diagnostic acceptance; they do not alter page data or the visible evidence interface.

## API contract

`GET /api/accounts/by-login/{login}/relationship-network` accepts the existing account filters.
It additively returns `entities`, `relationships`, `relationTypes`, `summary`, source `coverage`
and human-readable `limitations`. Each relationship carries its type label and evidence strings.
Individual source failure is reported in coverage and limitations while the available graph remains
usable.

## Data, routing and read-only constraints

The application composes existing read-only account-risk, login-IP, Copy and EA payloads. It writes
no local or remote data. Same-CRM-user and rebate facts preserve the source-routing and currency
rules owned by their existing features; login IP facts are only current-account database/local
observations and are not inferred as cross-account IP ownership.

## Business rules and units

The graph only presents evidence already returned by governed features. Money labels retain the
source payload currency and its established USD/USC normalization. The graph must not derive a risk
score, relationship strength or trading conclusion.

## Loading, empty and failure behavior

The dialog opens with a loading message. Independent evidence sources are fetched concurrently.
Failures do not hide successful evidence and appear as source coverage; an all-empty graph retains
the current account and explains the empty result. A failed request is removed from the page cache
so a later click retries it.

## Code and dependencies

`AccountRelationshipNetworkService` is application-layer composition over the LegacyBridge
compatibility boundary. The legacy page owns only graph rendering and interaction. No application
or domain code imports the copied legacy page module.

## Tests and acceptance

API tests pin entity/relationship typing, evidence-only output and nonfatal partial coverage. Legacy
HTML tests pin button placement, handlers, one native Canvas, the 3x raster scene cache, dynamic drag
overlay, frame sampling, viewport culling, label-width caching, persistent drawn edge labels, canvas hit
testing, drag-click suppression, cursor-centred continuous zoom and animation-frame-limited redraws without
a CSS-composited stage.
Account detail retains its legacy
route and all selected platform/server filters when opening the graph.

## Compatibility and deprecation

The feature is additive to the legacy account detail page. Existing account URLs, APIs, Copy, EA
and Toxic interactions are unchanged.
