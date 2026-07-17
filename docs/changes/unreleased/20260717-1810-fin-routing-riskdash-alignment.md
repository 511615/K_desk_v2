---
change_id: 20260717-1810-fin-routing-riskdash-alignment
features: ["ACC-SEARCH-001", "FIN-COMP-001", "FIN-REBATE-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Align server routing and finance with RiskDash

## Before and after

Live3 was missing, shared physical schemas could select the wrong logical source, and several
cashflow comments were misclassified. Routing now verifies CRM/server identity and finance matches
the verified RiskDash samples while old aliases remain compatible.

## Impact

Account search, finance, rebate and routing for all ten logical servers.

## Documentation updated

`DATA_AND_ROUTING.md`, `BUSINESS_RULES.md` and the three referenced feature documents.

## Verification

101 legacy tests and the ten-server read-only production matrix passed at baseline verification.

## Deployment and rollback

No database migration. Roll back application code and restart services if contract checks regress.
