---
change_id: 20260803-1900-acc-rel-kuzu-local-demo
features: ["ACC-REL-002"]
change_type: feature
status: unreleased
compatibility: compatible
---

# ACC-REL-002 Kuzu local relationship graph demo

## Before and after

K_desk previously had only the legacy relationship graph, which composes remote-backed payloads at
request time. The new isolated `/kuzu-demo` page reads a prebuilt local Kuzu evidence graph for one
operator trial account and supports bounded local traversal without changing the legacy page.

## Impact

The change adds two localhost account-service routes, a read-only local Kuzu adapter and its locked
Python dependency. The trial neither queries nor modifies a remote provider when the page is opened.

## Documentation updated

Added the ACC-REL-002 current-state document and updated architecture, data-routing, API and test
authorities. The feature registry maps the API, code, dependency files and test.

## Verification

Temporary Kuzu persistence/API tests, the focused relationship API test, Ruff, governance artifact
generation and Fast/Full verification are required. Production trial acceptance includes readiness
and the persisted account 2013674 graph response.

## Deployment and rollback

The page is deployed only to the isolated 8877 development account service for review. Rollback stops
that service or removes the local Kuzu file; the 8777 service, SQLite ledger and all remote data are
unchanged.
