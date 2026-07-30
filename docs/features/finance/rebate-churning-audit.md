---
feature_id: FIN-REBATE-AUDIT-001
title: Rebate churning account audit
module: finance
status: active
apis: ["GET /api/rebate-churning/accounts/{account}"]
code: ["legacy/apps/problem_account_registry/rebate_churning.py", "src/kdesk/api/account_app.py", "frontend/src/components/RebateAuditPanel.vue", "frontend/src/components/RebateTreeNode.vue", "frontend/src/rebateTreeRisk.ts", "frontend/src/pages/WorkbenchPage.vue"]
tests: ["tests/test_rebate_churning.py", "tests/test_api.py", "frontend/src/rebateTreeRisk.spec.ts"]
depends_on: ["FIN-REBATE-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Rebate churning account audit

## Purpose and user entry

Inspect the rebate hierarchy for an account and identify candidate churning relationships from the
workbench without writing CRM or trade state.

## UI and behavior

The Vue panel renders expandable rebate tree nodes, candidate accounts and evidence summaries.
Warning, high and severe nodes use yellow, orange and red accents. Account display severity maps
20/30/40 structure-contribution points to those colors; customer and non-scored upstream nodes
inherit the highest visible descendant severity. A customer row receives a separate prominent red
`返佣过大` presentation warning when its hierarchy rebate is positive and `customer trade P/L +
hierarchy rebate > 0`; this warning does not alter the risk score. The empty-node toggle hides
account rows with both zero orders and zero contribution, then recursively removes descendant
branches with no remaining account activity, trade totals, P/L, rebate or net-deposit value. It
does not change totals, scoring or exported data.

## API contract

The endpoint accepts optional time and source filters and returns explicit candidate/evidence data.
When both time filters are omitted, `query.fullHistory=true` and the period starts at the verified
historical coverage boundary for the selected CRM environment. A custom range returns
`query.fullHistory=false`.

## Data, routing and read-only constraints

CRM rebate and account mappings are queried read-only using the requested logical route. The target
account's complete parent chain is retained above the highest formal IB. A supervisory CRM node may
be displayed as an upstream IB relationship but is scored only when CRM `user_type=1`.
Detailed MT5 trade and cashflow reads use bounded `Login` and `Time` predicates without forcing an
index name from another physical schema, so AC and shared DBG MT5 layouts remain compatible.
The same portable path covers independent DBG MT5 Live2 accounts routed by `crm_vn` code 5 to
`crm_vn_mt5_live2`.
The account tree is loaded in 100-account batches. Rebate detail lets each CRM schema choose its
login/time index, selects only scoring fields, and is grouped in application memory by recipient
IB, account and trade while preserving the original rebate-row count. Historical account supplementation uses the selected audit window
(capped at five years) instead of scanning five years for every custom range. The complete tree's
rebate rows first create a high-recall deep-read candidate set from short holding, matched-cohort P95
order/rebate intensity, fixed lots and repeated cross-account signatures. The searched account is
always included. Only candidates read exact MT5 positions or MT4 tickets and cashflow history;
missing exact identifiers fall back to the selected time range. Non-target candidates above 1,000
exact rebate orders retain order, lot, holding and repetition evidence from de-duplicated rebate
metadata instead of reading every MT row. Their unknown profit is marked incomplete, cannot add
profit/economic-turnover points and does not trigger a cashflow read. Candidate membership never adds
risk points and never removes accounts, rebate amounts or detail counts from the complete tree.
Candidate membership also never controls the tree's basic trade totals. Every routed tree account
is independently aggregated over the complete selected period for order count, standard-lot-equivalent
volume, trading P/L and active days. Those complete aggregates replace the candidate evidence's
partial totals before tree financial roll-up and scoring. The indexed aggregation uses ten-account
batches grouped by physical source and reuses one connection per source. A missing aggregate row is
a confirmed no-trade result; a provider error fails the audit instead of displaying unread values as zero.
Per-account recipient amounts, raw row counts and matched-order counts are summarized once and reused
by every scored IB level. Hierarchy-total aggregation runs concurrently with candidate MT evidence,
and connections are reused across batches for each physical trade source.

## Business rules and units

Hierarchy amounts remain distinct from trade P/L and are aggregated at documented tree levels.
Accounts owned directly by an IB remain attached to that IB node. Cent-account platform lots are
multiplied by `0.01` after MT4/MT5 lot conversion to produce standard-lot-equivalent exposure for
tree totals and scoring. CRM `rebate_task_detail.rebate_amount` is always aggregated unchanged;
`usd_or_usc` remains evidence metadata and does not scale rebates.

## Loading, empty and failure behavior

Empty results show no candidates. Partial provider failures display a reason and do not assert a
clean audit.
Successful account/time/source responses are cached in process for five minutes, with a maximum of
eight entries. Cached payloads are copied before return and the cache is cleared by service restart.

## Code and dependencies

The API is a compatibility composition endpoint; the feature implementation is isolated in the
rebate churning service and Vue components.

## Tests and acceptance

Unit tests cover raw USC rebate aggregation, aggregated-detail row-count parity, Cent lot
normalization, portable DBG MT5 queries, login/time rebate-index selection, selected-period
historical reads, high-recall candidate selection, bounded exact reads, high-volume metadata evidence,
incomplete-profit economics guards, batching, cache copy isolation, upstream
relationship nodes, IB-owned accounts, tree construction and candidates. Frontend regressions cover
recursive empty-branch removal, zero-order/zero-contribution account filtering and the positive
hierarchy-rebate combined-value warning boundary. A non-candidate account
regression requires complete trade totals (`161` orders, `18.44` lots and `512.25` P/L) to remain
visible and verifies the full-history response flag. API tests verify filter
forwarding and result shape. Frontend tests cover severity propagation and empty-node filtering.

## Compatibility and deprecation

This endpoint is additive; response fields require OpenAPI regeneration when changed.
Platform discovery reuses the same expandable tree and score-free SVG presentation without
changing this route or its full-history default.
