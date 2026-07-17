---
change_id: 20260717-1830-fin-rebate-audit
features: ["FIN-REBATE-AUDIT-001", "FIN-REBATE-001"]
change_type: addition
status: unreleased
compatibility: compatible
---

# Add rebate churning account audit

## Before and after

The workbench could show total rebate but not inspect hierarchy/candidate relationships. It now has
an additive API and Vue tree panel for a read-only account audit.

## Impact

Account FastAPI, workbench UI, legacy rebate service and related tests.

## Documentation updated

Feature catalog, API authority, rebate business rules and feature documents.

## Verification

Dedicated rebate churning unit and API tests validate hierarchy, filters and candidates.

## Deployment and rollback

No migration or existing contract change. Roll back UI/API/service files together.
