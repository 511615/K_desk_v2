---
change_id: 20260805-1730-acc-detail-inline-script-validation
date: 2026-08-05
feature_ids: ["ACC-DETAIL-001", "AUT-COPY-001"]
features: ["ACC-DETAIL-001", "AUT-COPY-001"]
change_type: bug-fix
status: unreleased
compatibility: compatible
impact: bugfix
summary: Restored account-detail initialization by removing a duplicate JavaScript declaration in the Copy dialog loader.
---

# Account detail inline script validation

## Before and after

Previously a duplicate block-scoped declaration prevented the account-detail inline script from
evaluating. The loader now reuses the already validated query parameters and initializes normally.

## Changed behavior

`loadCopyOrigins` now reuses its already validated query parameters when building its cache key.
It no longer redeclares the same block-scoped variable, so the legacy detail script evaluates and
the initial ledger, detail, risk-panel and IP requests start normally.

## Compatibility and safety

No endpoint, request parameter, business rule, local storage, remote data access or MT4/MT5 action
changed. The Copy dialog retains its opening-time validation and cache semantics.

## Impact

The legacy account-detail page can initialize normally again. API, data-routing and financial
behavior are unchanged.

## Documentation updated

- `docs/features/account/account-detail-legacy.md`
- `docs/features/automation/copy-origin-query.md`

## Deployment and rollback

Deploy with the normal 8777 application release after verification. Rollback restores the prior
legacy template revision, including its initialization failure.

## Verification

The legacy detail test suite now extracts the complete inline script and runs the bundled Node.js
syntax validator. This specifically catches a page-wide initialization failure before deployment.
