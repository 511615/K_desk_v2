---
feature_id: FIN-REBATE-AUDIT-001
title: Rebate churning account audit
module: finance
status: active
apis: ["GET /api/rebate-churning/accounts/{account}"]
code: ["legacy/apps/problem_account_registry/rebate_churning.py", "src/kdesk/api/account_app.py", "frontend/src/components/RebateAuditPanel.vue", "frontend/src/components/RebateTreeNode.vue", "frontend/src/pages/WorkbenchPage.vue"]
tests: ["tests/test_rebate_churning.py", "tests/test_api.py"]
depends_on: ["FIN-REBATE-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Rebate churning account audit

## Purpose and user entry

Inspect the rebate hierarchy for an account and identify candidate churning relationships from the
workbench without writing CRM or trade state.

## UI and behavior

The Vue panel renders expandable rebate tree nodes, candidate accounts and evidence summaries.

## API contract

The endpoint accepts optional time and source filters and returns explicit candidate/evidence data.

## Data, routing and read-only constraints

CRM rebate and account mappings are queried read-only using the requested logical route.

## Business rules and units

Hierarchy amounts remain distinct from trade P/L and are aggregated at documented tree levels.

## Loading, empty and failure behavior

Empty results show no candidates. Partial provider failures display a reason and do not assert a
clean audit.

## Code and dependencies

The API is a compatibility composition endpoint; the feature implementation is isolated in the
rebate churning service and Vue components.

## Tests and acceptance

Unit tests cover tree construction and candidates; API tests verify filter forwarding and result shape.

## Compatibility and deprecation

This endpoint is additive; response fields require OpenAPI regeneration when changed.
