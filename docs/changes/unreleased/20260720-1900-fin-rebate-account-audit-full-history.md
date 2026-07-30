---
change_id: 20260720-1900-fin-rebate-account-audit-full-history
features: ["FIN-REBATE-AUDIT-001", "FIN-REBATE-SCAN-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Restore complete trade totals in full-history rebate trees

## Before and after

The account audit loaded the complete CRM tree and complete rebate totals, but used the candidate
deep-read set as the only source of trade features. A descendant account that was not selected for
pairing or turnover analysis therefore displayed zero orders, lots and trading P/L even when the
trading database contained valid history. DBG CN account 2013813 exposed the contradiction: 791.75
of rebate was visible while 161 closed trades, 18.44 standard lots and 512.25 trading P/L were not.

The audit now aggregates closed trade count, lots, trading P/L and active days for every routed
account over the complete selected period. These complete totals replace candidate-only totals
before hierarchy roll-up and risk scoring. Candidate selection remains responsible only for the
expensive structural evidence. Omitted dates are explicitly returned as `query.fullHistory=true`,
and the tree labels full-history totals separately from custom-range totals.

## Performance and discovery boundary

Complete aggregates are grouped by physical trading source, use ten-account indexed batches and
reuse one connection per source. Rebate totals and trade aggregates run in one background read
chain while candidate evidence is loaded independently, limiting concurrent remote read chains.
The full-platform rebate discovery implementation is unchanged: it defaults to seven recent days,
rejects more than 31 days and keeps its candidate-first deep-read optimization.

## Impact

The single-account audit performs one additional complete-period aggregate read for every routed
tree account, so uncached full-history requests may take longer than candidate-only reads. The
ten-account indexed batching, source connection reuse, bounded concurrency and existing five-minute
response cache limit that cost. Discovery jobs, persistent task data and all remote data are unchanged.

## Documentation updated

`FIN-REBATE-AUDIT-001`, `FIN-REBATE-SCAN-001`, API, data/routing, business-rule and test authorities
now distinguish full-history account audit from recent-window platform discovery.

## Verification

Unit coverage verifies that complete totals replace empty non-candidate features without removing
candidate pairing/holding evidence. An audit workflow regression verifies `fullHistory=true` and the
2013813 expected trade totals. A live read-only, uncached direct service request returned the
164-account DBG CN tree in 8.2 seconds and reported 161 orders, 18.44 standard lots, 512.25 trading
P/L, 11 active days, 791.75 raw rebate and `tradeStatisticsComplete=true` for account 2013813.
Fast and Full governance checks passed with 214 Python tests and 11 frontend tests; the Vue
production build also passed. The deployed 8777 endpoint returned the same 2013813 values and both
8777 and 8766 readiness checks passed.

## Deployment and rollback

No database migration, remote write, port change or breaking request parameter is introduced.
Deploy by rebuilding the frontend and restarting only the account service on 8777. Rollback restores
the prior candidate-only trade totals; no CRM, MT4, MT5 or local persistent data is changed.
The account service was restarted on 8777 after Full verification. The existing 8766 process was
left running and no additional listening port was opened.
