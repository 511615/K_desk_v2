---
change_id: 20260813-aut-ea-global-comment-parallelism
features: ["AUT-EA-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# Parallel global EA Comment source lookup

## Before and after

The new all-MT4/MT5 exact Comment search issued at most four independent source reads at once,
creating serial waves across the configured source routes.

## Impact

The exact Comment and dynamic fallback stages now issue up to 12 bounded, read-only source reads in
parallel. MT5 position completion uses 5,000-position batches rather than 300-position batches,
reducing round trips while retaining complete position/deal reconstruction. Query semantics, source
routing, result fields and remote permissions are unchanged.

## Documentation updated

Updated AUT-EA-001's data-routing/performance behavior.

## Verification

Regression coverage asserts the global source budget. Full Python/API/report/frontend verification
and a production timed read remain required before handoff.

## Deployment and rollback

Restart only 8777 after verification. Rollback is the paired Git commit and account-service restart;
no local schema, remote database or Manager state is changed.
