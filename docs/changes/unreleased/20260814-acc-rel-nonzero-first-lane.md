---
change_id: 20260814-acc-rel-008-nonzero-first-lane
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Prevent straight first-lane overlap

## Before and after

The first outgoing edge from each source still used zero curvature. That left visually coincident
edges when different sources or relation families happened to share a direction. The first lane now
receives a deterministic left/right bend as well; additional edges continue to use the shared source
fan-out lanes.

## Impact

Read-only canvas geometry only. Relation endpoints, community aggregation, scores, API payloads and
curve hit testing are unchanged.

## Documentation updated

- `docs/features/account/score-propagated-kuzu-investigation.md`
- This change record.

## Deployment and rollback

- Deploy the account service on port 8777 only after verification.
- Roll back by reverting this implementation commit; no database migration is required.

## Verification

- Focused page contract and JavaScript syntax checks.
- Full K_desk verification before deployment.
