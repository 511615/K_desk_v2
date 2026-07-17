---
change_id: 20260717-1800-gov-lifecycle-enterprise-governance
features: ["GOV-LIFECYCLE-001"]
change_type: addition
status: unreleased
compatibility: compatible
---

# Establish enterprise feature-led governance

## Before and after

Before, architecture and port documents existed but were stale and feature changes were not
traceable. After, system authorities, Feature IDs, generated registry/OpenAPI, immutable records,
verification modes, hooks, CI and a maintenance Skill form one governed workflow.

## Impact

Developer workflow and `/api/meta` metadata are extended. A guarded release script adds consistent
local rollback snapshots. Production URLs and business contracts do not change.

## Documentation updated

All system authorities, ADRs and the initial feature catalog are created or refreshed.

## Verification

Governance, architecture, API, backend, legacy and frontend checks are required before release.

## Deployment and rollback

Governance files are additive. Roll back the release commit if tooling blocks an emergency; do not
remove immutable change history from later releases.
