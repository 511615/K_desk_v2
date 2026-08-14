---
change_id: 20260814-acc-rel-006-curved-edge-routing
features: ["ACC-REL-003"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Curved relation-edge routing

## Before and after

Close-angle relation lines were drawn as straight segments, so different relations and their labels
could visually overlap. Edges now receive deterministic lanes per source and relation family and are
drawn as quadratic curves. The first edge remains the trunk; subsequent edges fan out on alternating
sides. Labels follow the curve midpoint and selected edges retain a white dashed highlight.

## Impact

This changes only the read-only canvas projection. The same relation endpoints, group anchors, scores,
and API payload are preserved. Hit testing samples the same curve geometry, so curved lines remain
clickable. Copy-order edge inspection remains available.

## Documentation updated

- `docs/features/account/score-propagated-kuzu-investigation.md`
- This change record.

## Deployment and rollback

- Deploy the account service on port 8777 only after verification.
- Roll back by reverting this implementation commit; no database migration is required.

## Verification

- Page JavaScript syntax check.
- Focused and full API tests.
- Full K_desk verification before deployment.
