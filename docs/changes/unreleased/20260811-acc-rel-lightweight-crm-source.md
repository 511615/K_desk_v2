---
change_id: 20260811-acc-rel-lightweight-crm-source
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Use a mapping-only CRM evidence source during relationship expansion

## Before and after

Continuous graph expansion was invoking the complete account-dashboard risk-panel payload for every
eligible account solely to obtain same-CRM-user peers. That payload loads and caches complete trade
history, causing the 8777 process to grow during multi-hop investigations.

## Impact

`AccountRelationshipNetworkService` now calls `account_relationship_core_payload`. The new read-only
legacy payload resolves the selected source and returns only CRM-mapped account identities, platforms
and servers. The full dashboard `risk-panels` endpoint and response are unchanged.

## Documentation updated

Updated the ACC-REL-001 and ACC-REL-003 current-state documents, architecture, data-routing and
test-strategy authorities.

## Verification

Relationship API and application tests verify the mapping-only source is used. Full verification and
a live read-only multi-hop/memory acceptance are required before release.

## Deployment and rollback

No remote write, MT Manager operation, API contract removal or port change is introduced. Deploy by
restarting only the 8777 account service. Roll back by restoring the prior verified account-service
commit and restarting only that service; no data migration is involved.
