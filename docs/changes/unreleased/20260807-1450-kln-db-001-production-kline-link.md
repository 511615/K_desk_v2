---
change_id: 20260807-1450-kln-db-production-kline-link
features: ["KLN-DB-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Point the production account page to the production K-line task center

## Before and after

The Vue account page linked its K-line task-center button to development port `8866`. It now opens
the running production K-line service on `127.0.0.1:8766`.

## Impact

`KLN-DB-001` Vue account-page navigation only. K-line APIs, task payloads, chart artifacts, source
reads and existing legacy-detail behavior are unchanged.

## Documentation updated

- `docs/features/kline/database-generation.md`

## Verification

- Frontend type checking and production build verify the rendered account page.
- Production health checks verify that port `8766` is ready after release.

## Deployment and rollback

The normal release script rebuilds the frontend and restarts only verified K_desk services. Rollback
restores the previous versioned frontend bundle and runtime snapshot.
