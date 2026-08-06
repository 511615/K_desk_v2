---
change_id: 20260805-0900-acc-detail-header-search
features: ["ACC-DETAIL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# ACC-DETAIL-001: Add header account search

## Before and after

Account detail required users to return to the ledger before opening another Login. The detail header
now provides a numeric account search that opens the selected Login directly.

## Impact

The client reuses the existing read-only account lookup endpoint. It selects the current
platform/server when available for the searched Login, otherwise the endpoint's first valid source.
No API route, database schema, financial calculation or remote system state changes.

## Documentation updated

Updated `ACC-DETAIL-001` with the search location, source-selection behavior and validation states.

## Deployment and rollback

Restart only the localhost account service on port `8777` to load the server-rendered page. Rollback
is the prior account page revision; no data migration or service restart on port `8766` is required.

## Verification

Added legacy HTML regression coverage for the form, status region and source-aware lookup handler.
Full governance, backend, frontend and production health checks are run before deployment.
