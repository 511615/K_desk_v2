---
change_id: 20260825-1920-acc-rel-profile-terminal-refresh
features: ["ACC-REL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Refresh Galaxy profiles when expansion reaches a terminal snapshot

## Before and after

The Galaxy graph header could report a completed expansion while the selected account profile still
displayed the `pending` coverage and expansion state from its first background poll. The profile
cache keyed only by account and filters, so the terminal graph snapshot did not cause a re-read.

The profile cache and selection refresh identity now include the graph snapshot state
(`progress`, `complete`, or `truncated`). The profile is fetched once per state transition, so its
coverage and expansion outcome agree with the rendered graph without adding repeated requests during
ordinary polling.

## Impact

This is a read-only Galaxy UI consistency correction for `ACC-REL-001`. It does not alter account
discovery, scoring, relationship evidence, APIs, routing or database access.

## Documentation updated

Updated the `ACC-REL-001` current-state document with the profile terminal-snapshot refresh rule.

## Verification

The Galaxy API/page regression asserts the terminal snapshot helper and selection cache key are
present. The embedded JavaScript is syntax-checked, followed by fast/full verification and deployed
page inspection.

## Deployment and rollback

Promote the verified dev commit with `scripts/promote_dev.ps1` and deploy from clean `main` with
`scripts/release_prod.ps1`. Rollback restores the prior application commit and restarts 8777; no
migration or external-state reversal is required.
