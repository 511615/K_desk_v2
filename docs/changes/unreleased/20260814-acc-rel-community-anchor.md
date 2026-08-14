---
change_id: 20260814-acc-rel-005-community-anchor
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Render collapsed relationship communities as canvas objects

## Before and after

Collapsed relationship edges still ended on one representative account, while every member account
remained separately visible. A community therefore looked like a normal account and the intended
expand/merge interaction was unclear. A collapsed community now has one anchor on its relation band,
shows its member count, and receives the common edge. Clicking the anchor expands all members;
clicking the expanded band or the detail control merges them again.

## Impact

Read-only canvas projection only. Relationship discovery, propagation scores, API payloads and
database access are unchanged.

## Documentation updated

- `docs/features/account/score-propagated-kuzu-investigation.md`
- This change record.

## Deployment and rollback

- Deploy the account service on port 8777 only after verification.
- Roll back by reverting this implementation commit. No database migration is required.

## Verification

- Page JavaScript syntax check.
- Focused Kuzu page API contract test.
- Full K_desk verification before deployment.
