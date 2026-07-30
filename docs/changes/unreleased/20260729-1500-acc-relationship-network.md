---
change_id: 20260729-1500-acc-relationship-network
features: ["ACC-REL-001", "ACC-DETAIL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# ACC-REL-001: Add evidence-only interactive relationship network

## Before and after

The legacy detail page now opens its completed relationship-network graph through the `关系网络`
button. The graph lets an operator show or hide relation categories, inspect node/edge evidence,
expand aggregated EA and Copy nodes, drag nodes, pan/zoom and restore the default local view.

The graph only composes existing account, IP, EA, Copy and rebate facts. It explicitly does not
assign risk scores, relationship strengths or conclusions. A failed independent source remains
visible as coverage instead of discarding the evidence from the other sources.

## Impact

The additive account API is read-only and uses the existing selected platform/server/filter routing.
No remote database, MT4/MT5 Manager, SQLite authority data or service port is written or changed.
Existing legacy detail URLs and all current APIs remain compatible.

## Documentation updated

Added ACC-REL-001 and updated the legacy-detail, API and test authorities. Generated registry and
OpenAPI artifacts are refreshed with the additive endpoint.

## Deployment and rollback

This affects only the existing localhost account service on port 8777. Rollback removes the
additive endpoint/button and restores the preceding legacy page; no migration or data restoration is
required.

## Verification

- Fast governance, Python compile and Ruff verification passed.
- Full verification passed: 302 Python/legacy tests, 20 frontend tests and the production frontend
  build.
- Production restart passed both `8777` and `8766` readiness checks.
- Localhost browser acceptance on account `7798437` confirmed the entry button, evidence dialog,
  no-score limitation text, relation-type hiding, view reset and dialog close behavior.
