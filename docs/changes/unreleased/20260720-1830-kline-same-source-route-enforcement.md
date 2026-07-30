---
change_id: 20260720-1830-kline-same-source-route-enforcement
features: ["KLN-DB-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Keep Terminal as the universal K-line fallback

## Before and after

When no quote registry was configured, the single legacy `default` Terminal was labelled as a
same-source provider for every database server. This understated the risk when a logical server's
prices diverged from the Terminal feed. A subsequent strict-routing draft also made server-specific
provider configuration mandatory, which was unnecessarily restrictive for current operations.

Database jobs now use the current Terminal as their universal default quote provider and classify it
as a fallback whenever server provenance exists. This requires the stricter fallback endpoint gate:
aligned feeds generate normally, while divergent feeds are rejected instead of producing a shifted
chart. Explicit registries can still constrain routes and retain structured missing-route failures.

## Impact

New server-routed K-line jobs no longer require a provider registry and use the configured Terminal
path. URLs, request fields, SQLite schema, historical HTML, chart style, marker shapes and read-only
constraints are unchanged; unscoped Terminal feeds use the existing stricter fallback threshold.

## Documentation updated

The K-line current-state document, data/routing authority, operations guide and test strategy now
state that the unscoped default Terminal is a universal strict fallback and document the remaining
explicit-registry missing-route failure.

## Verification

Focused tests cover universal strict fallback selection, uploaded-report compatibility and actionable
structured failure. The final Full gate passed with 214 Python/legacy tests, all 11 frontend tests,
generated-contract validation, compile/lint checks and the production frontend build.

## Deployment and rollback

Deploying the code requires no quote registry; `TRADE_KLINE_TERMINAL` remains the default source.
Production deployment still requires separate authorization. Roll back code/configuration only; no
data migration or MT4/MT5 Manager action is required.
