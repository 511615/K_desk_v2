---
change_id: 20260722-1200-aut-ea-cross-db-copy-owner-report
features: ["AUT-EA-001", "AUT-COPY-001", "AUT-FOLLOWER-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Correct dynamic EA identity and organize copy reports by owner

## Before and after

The first dynamic-comment fix normalized `@8@<position number>@<channel>` by retaining the final
numeric segment. Live evidence showed that both numeric segments vary by position/account/channel;
the stable EA identity is the leading Comment family plus MT5 ExpertID. That implementation returned
unrelated accounts and omitted the five AC plus three other DBG accounts expected for 2013674.

Dynamic EA groups now use `Comment family + ExpertID`, expand read-only discovery across AC CN MT5
and DBG CN MT5, retain database/server on every member and merge complete Position executions before
profit aggregation. AC uses indexable two-digit Comment shards. Multiple ExpertIDs for one family
share a single shard pass, keeping the complete cold query below ten seconds.
Every EA group in the legacy dialog is also an independent, default-open disclosure section; users
can collapse dense groups without invalidating the already cached result.

Copy Excel exports previously centered the queried account and spread CPT, source evidence, Signal
groups and notes across generic sheets. The workbook now contains only `单主汇总` and one sheet per
source owner. Each owner sheet starts with total and follower-level P/L, then lists every matched
MT5 Position or MT4 ticket. The copy-origin JSON additively retains `followerOrders`; existing fields
and the independent Signal JSON endpoint remain unchanged.

## Impact

No route, parameter, local schema or remote state changes. Exact named EA comments remain source-
local. Dynamic discovery reads only the two documented primary MT5 deal tables and caches only
derived Position IDs for 60 seconds; execution rows and profit stay live. The report route no longer
queries Signal profit because Signal content is intentionally absent from the owner report.

## Documentation updated

`BUSINESS_RULES.md`, `DATA_AND_ROUTING.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md`,
`ea-comment-profit.md`, `copy-origin-query.md` and `follower-profit.md`.

## Verification

Focused Python tests cover dynamic identity, AC shard construction, AC/DBG merging, per-Position
follower detail, owner-only workbook structure, typed identifiers and API download behavior.
The read-only cold 2013674 query completed in 2.369 seconds with no provider error. ExpertID 7
returned exactly DBG 2013674/2014359/2014169/2013651 and AC 201518/221698/207357/201628/33553;
current Position counts were 73/70/25/17 and 82/77/40/8/3 respectively, with 221698 detected as
Cent/USC. Spreadsheet QA imported the generated owner report, scanned all cells for formula errors
and rendered all three worksheets without clipped headings or unreadable values. Fast verification
passed; Full verification passed with 229 Python/legacy tests, 11 frontend tests and the production
Vue build.

## Deployment and rollback

No migration is required. Deployment restarts only account service 8777; K-line service 8766 and
workers remain untouched. Rollback restores the previous EA module, report builder, endpoint
orchestration and account-service process. SQLite and all remote read-only data remain unchanged.
Production account service was restarted from PID 7216 to PID 15500. K-line service remained on PID
14072 throughout. Both services reported ready after deployment. A fresh production EA request for
2013674 completed in 2.459 seconds with no provider error and returned the required nine ExpertID 7
members. Browser verification confirmed seven groups start open and one header click leaves exactly
that group closed while the other six remain open.
