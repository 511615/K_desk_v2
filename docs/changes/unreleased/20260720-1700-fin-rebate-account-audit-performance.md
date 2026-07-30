---
change_id: 20260720-1700-fin-rebate-account-audit-performance
features: ["FIN-REBATE-AUDIT-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# Bound account rebate-audit deep reads

## Before and after

Account audit expanded the selected account to its highest formal IB's complete tree, then issued
four serial read passes for every account in 25-account batches. Rebate detail forced the
single-column `idx_mtLogin`, so MySQL filtered account lifetime rows after index lookup even for a
short requested period. Historical account discovery also scanned five years for every custom
window. Account 3066186 expands to 2,223 CRM users and 1,217 accounts; a one-hour audit took about
116 seconds before this change.

Rebate detail now lets the CRM optimizer select the existing login/time index, transfers only the
fields needed by scoring and groups repeated source rows in bounded application batches by
recipient IB, account and trade while retaining raw-row counts. Recipient-IB evidence and account
hierarchy totals are read separately. One detailed trade pass supplies both structural evidence and
order/active-day/lot/profit totals, removing the duplicate historical aggregate pass; cashflows are
limited to bounded exact-evidence accounts. The audit uses 100-account batches, reuses trade-source
connections, constrains historical discovery to the selected period with a five-year cap, and
caches eight successful account/source/period responses for five minutes.
Recipient rebate rows now retain symbol, volume and open/close timestamps for a high-recall candidate
screen. Only candidates and the searched account reconstruct exact MT5 positions or MT4 tickets and
read cashflows; candidates lacking exact identifiers use the selected-period fallback. Non-target
candidates above 1,000 exact rebate orders use de-duplicated rebate metadata for structure evidence,
while incomplete profit cannot add economic-turnover points or funding-cycle evidence. Complete-tree
rebate amounts and raw detail counts remain unfiltered, and candidate membership adds no risk points.
Per-account recipient summaries are calculated once and reused across IB levels. The hierarchy-total
query runs concurrently with independent candidate MT evidence instead of extending wall time.

## Impact

The complete CRM tree, account nodes, monetary totals, risk thresholds and API fields remain
compatible. Accounts without period trades or rebates retain zero detailed evidence instead of
triggering unnecessary trade and ledger reads. Repeated identical requests may show data up to five
minutes old; service restart clears the in-memory cache.

## Documentation updated

The account-audit feature document, data/routing authority and test strategy now describe the
selected-period historical scope, optimizer-selected rebate index, split recipient/total rebate
reads, bounded in-memory grouped detail counts, single-pass trade aggregates, active-account
cashflows, high-recall bounded deep reads, high-volume metadata evidence, connection reuse, larger batches and short-lived
response cache, reusable recipient summaries and concurrent independent read stages.

## Verification

Unit regressions cover optimizer-selectable rebate SQL, grouped amount/raw-count parity, 100-account
batches, selected-period historical parameters, high-recall candidate selection, bounded exact
trade/cashflow reads, incomplete-profit guards and defensive cache copies. Live read-only EXPLAIN on DBG
`crm_vn.rebate_task_detail` estimates 50,672 examined
rows with the old forced index versus one row with the existing login/time index for account
3066186 over a one-hour range. A live read-only test returned the complete 2,224-node, 1,217-account
full-history tree in 96.98 seconds; a one-hour uncached request took 5.05 seconds and the matching
cache read took 0.30 seconds. Fast and Full governance checks are required before deployment.

## Deployment and rollback

No migration, remote write, API change or port change. Restart account production on 8777 after
deployment. The account service was restarted on 8777 after Full verification; 8766 remained on its
existing process. Rollback restores the prior query breadth and latency; local and remote data are
not changed.
