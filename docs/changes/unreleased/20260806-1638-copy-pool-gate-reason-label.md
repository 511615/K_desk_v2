---
change_id: 20260806-1638-copy-pool-gate-reason-label
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Copy-pool execution reason labels

The current-copy panel now resolves the producer's bounded execution-gate sub-reasons into
localized Chinese labels. Existing generic reason codes remain supported, and this is a
presentation-only additive change.

## Before and after

Before, a detailed producer rejection code was rendered as an untranslated raw string. After,
operators see a concise Chinese reason while the API code remains unchanged.

## Impact

Only the 8777 Vue presentation changes. Producer behavior, snapshot files and execution contracts
are unchanged.

## Documentation updated

The AUT-POOL-001 current-state document records the localized reason mapping behavior.

## Verification

The frontend unit suite and production build pass. No runtime process or API contract changes are
introduced.

## Deployment and rollback

Deploy with the main-branch frontend bundle. Rollback is the previous frontend bundle; no data
format or Demo state migration is required.
