---
feature_id: ACC-DETAIL-001
title: Legacy account detail page
module: account
status: active
apis: ["GET /account/{login}", "GET /api/accounts/by-login/{login}/detail", "GET /api/accounts/by-login/{login}/risk-panels", "GET /api/accounts/by-login/{login}/historical-funds", "GET /api/accounts/by-login/{login}/relationship-network", "GET /api/accounts/by-login/{login}/orders"]
code: ["src/kdesk/api/account_app.py", "src/kdesk/application/relationship_network.py", "legacy/apps/problem_account_registry/app.py", "frontend/src/main.ts"]
tests: ["tests/test_api.py", "legacy/apps/problem_account_registry/test_app.py", "frontend/e2e/legacy-account.spec.ts"]
depends_on: ["ACC-SEARCH-001", "FIN-COMP-001", "FIN-HISTORY-001", "AUT-COPY-001", "AUT-FOLLOWER-001", "AUT-EA-001", "TOX-PUSH-001", "TOX-POSITION-001", "TOX-HEDGE-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-19
---

# Legacy account detail page

## Purpose and user entry

All `/account/{login}` links render the familiar legacy account detail HTML from the new production
service. Platform/server query parameters select the account source.

## UI and behavior

The page contains ledger controls, finance and risk panels, order paging, chart generation, copy
origin, EA comment, relationship-network, Toxic and historical-funds controls. The `历史资金回溯`
button is immediately after Toxic and opens a separate factual timeline. Copy and EA query dialogs each provide a one-click Excel
profit report using the current platform/server filters. Copy and EA expose optional opening-time
start/end controls and an explicit query action; each dialog's visible result and Excel export always
use the same range. It is intentionally not replaced by the
Vue AccountPage.
The top-right account search accepts a numeric Login and opens its detail without returning to the
ledger. It reuses the read-only account lookup route. When the Login exists on multiple platforms or
servers, a source-selection dialog lists every candidate and the user must choose one before
navigation; the selected platform/server is carried into the detail URL. Empty, non-numeric,
not-found and lookup-in-progress states are visible beside the input. Direct detail requests without
source filters also return a source-selection state rather than merging orders from different servers.
Successful Copy and EA dialog payloads are retained in page memory by normalized platform/server/
symbol filters and their selected opening-time ranges. Closing a dialog preserves its result; reopening uses no network request. The main
refresh button clears both dialog caches before loading fresh account data.
Each EA result group starts expanded and can be collapsed independently from its header; this is a
local display state and does not invalidate or repeat the query.
The additive `关系网络` dialog is generated only after its button is clicked; it delegates its
evidence-only relation categories, aggregation expansion and local page cache to `ACC-REL-001`. Its
interactive graph is one client-only native Canvas. Its static scene is held in a detached 3x raster cache,
so camera gestures copy the cache once per animation frame; only an actively dragged node is redrawn over
it. Filters, aggregate expansion and finished node movement refresh the cache without re-querying data.
EA account rows display the observed ExpertID/MAGIC and an explicit match clue. Same-server clues
state that both Comment and identifier matched; cross-server clues state that Comment matched.
The EA dialog separately labels `可能是跟单路由` groups. Those groups remain expandable with the
same account/order/profit detail but the dialog headline and Excel EA KPIs exclude them.
No-comment ExpertID-sequence groups use the same route label, show the complete shared-ID count and
compact long per-account identifier lists to eight samples without discarding API/report evidence.
Confirmed cent accounts show `USC` with money normalized to USD even when a newly registered MT5
account has not produced its first daily snapshot. The same-name panel includes every account owned
by the same CRM user across configured logical servers and displays each account's actual server.
A zero-order account whose CRM route is confirmed still shows that platform and server in the detail
header and selectors, plus the explicit `账户暂未做单` state; it is not shown as `未识别平台`.
MT4 rows whose close time is the `1970-01-01` open-position sentinel, or otherwise is not later
than the open time, are excluded from closed-order counts, duration metrics and daily P/L charts.
MT4 detail analytics read the complete closed-order history rather than a 50,000-row prefix. The
full-history rows, costs and metrics are calculated once per account/source cache window and reused
by detail, risk, finance and automation panels. The order table uses exact database pagination and
reports the exact total without first loading the complete account history.
The chart task card displays partial-success totals and structured per-symbol quote failures without
hiding the successfully generated chart.
The inline page script is syntax-validated in the legacy detail test suite so a dialog enhancement
cannot prevent the initial ledger, detail, risk and IP requests from starting.
The Toxic `平台内多账户对锁` item renders a dedicated query result: physical-source coverage,
opposite-account routing, subject/peer lots and exact synchronized opening/closing order evidence. It
does not display the copied account-internal reverse-leg score as the completed result.
The historical-funds dialog pages raw events while preserving complete totals. It shows external
cashflows separately from internal account transfers, Credit changes, negative-balance clear rows and
trade realization. Its balance/Credit curve is replayed only from sourced ledger/trade facts after a
daily anchor; equity is shown only at authoritative daily anchors and is never synthesized between
them. Platform Stop Out and negative-balance-clear events appear as red clickable curve markers and
as a complete jump list; selecting one opens its event page and highlights the raw row. It makes no
conclusion about bonus deduction, debt forgiveness or customer compensation.
The additive read-only `复制实验` section matches the selected Login, platform and server against
`AUT-POOL-001`. It shows account-product sleeves, base/current weight, the client loss budget and
each source Position to Demo Ticket mapping. Execution states and rejection reasons are localized
in Chinese; unavailable or unmatched dashboard data degrades inside this section without blocking
the rest of the account page.

## API contract

The HTML URL and supporting detail/risk API response structures remain backward compatible.
The additive relationship-network response is governed by `ACC-REL-001`.
The additive historical-funds response is governed by `FIN-HISTORY-001` and accepts the existing
platform/server selection; it deliberately ignores the page symbol filter because funding history is
account-wide.
The copy-experiment section consumes the existing read-only `GET /api/copy-pool/dashboard` contract
owned by `AUT-POOL-001`; it adds no account-detail write endpoint.

## Data, routing and read-only constraints

The selected account uses its selected read-only route. Server query parameters accept both the
canonical source name and the compatibility aliases emitted by the copy-pool logical routes;
normalization happens before source selection and does not change the canonical server returned in
the payload. Same-name account analytics resolve every
related account through its own CRM server code and trading source; local edits go only to
authoritative SQLite. DBG MT5 Live2 resolves only through `crm_vn` code 5 and
`crm_vn_mt5_live2`; the legacy DBG GB MT5 code 2 route remains on `mt5_export_new`.
For a temporarily missing CRM account mapping, the selected source can read only the documented
unique physical trade-user fallback; a duplicate Login or a shared-schema secondary logical route
does not render another server's data.
When CRM confirms the selected route but the trading history is empty, detail retains that confirmed
source identity and reports an empty-order state. It never guesses another physical source merely
to populate the page.
MT5 reversal/out-by deals (`Entry` 2/3) that have no standard open/close pair remain visible as a
zero-duration factual trade row; they are not discarded as an empty account.
The account-source lookup includes those entries before conversion, so the detail page cannot report
an empty account solely because its available execution uses an `Entry` 2/3 form.

## Business rules and units

Displayed finance and automation values defer to their feature documents.
Weekend and opening Toxic rows defer to `TOX-POSITION-001` and present leverage-adjusted economic
position evidence rather than the copied page's legacy time-only heuristics.
Cross-account hedge queries defer to `TOX-HEDGE-001` and show only opposite synchronized open/close
evidence, without adding other Toxic conclusions.
Historical cash/Credit reconstruction, classifications and limitations defer to `FIN-HISTORY-001`.

## Loading, empty and failure behavior

Panels load independently where supported. A failed panel shows its own reason and must not block
the complete page or leave a false 100% progress state. A cold read of the normal account detail
and risk-panel APIs must return complete results within 10 seconds; a warm read must not be used to
hide a cold-path regression.
The legacy source-notes text is optional once the compatibility workbook exists. If it is absent,
the detail API treats it as empty source input and continues to serve the stored ledger; it never
creates the file during a read request.

## Code and dependencies

FastAPI calls `LegacyBridge.account_page`; no other v2 module imports the copied page module.

## Tests and acceptance

Account 302360 returns HTTP 200, includes the legacy control IDs (controls may be conditionally
hidden when their feature has no data) and contains no Vue `#app` mount. Live3 account 241003365
must show the USC badge and USD-normalized money rather than raw cent values. Its same-name panel
must include Live1 account 245856 plus the four Live3 accounts belonging to CRM user 133018. A
cache-cleared production request for this five-account panel must finish in less than 10 seconds.
MT4 account 5013015 is the open-position sentinel regression sample: its three current positions
remain in current holding state but do not create a `01-01` chart bar or a negative holding time.
High-volume MT4 account 8208074 is the completeness and performance sample: it must report 59,504
closed orders, 704 daily bars and an exact 59,504-order pagination total; page 1 returns 100 newest
orders. Cold detail, risk, automation and order-page requests must each finish within 10 seconds.
AC GB MT5 account 641903 is the Copy completeness sample: 895 positions map with no unresolved rows,
640598 owns 625 and 632824 owns 270, current-account follower profits reconcile to 439.89 and 64.43,
and a cold complete response finishes within 10 seconds. DBG CN MT5 account 2013674 is the EA-route
format sample: the EA dialog must classify its `@8@...@7` structure as `可能是跟单路由`, retain
database/server-aware member profit detail, exclude it from EA headline totals, and complete a cold
correct response within 10 seconds.
DBG CN MT5 account 2014201 is the no-comment EA-route sample: the dialog must list 2014201, 2014202,
2014137 and 2014195 through conservative complete-ExpertID/time/symbol/direction evidence, while
keeping the EA headline at zero groups.
New AC GB MT5 account 954059 must render with `MT5 / AC GB MT5` and zero orders, rather than an
unidentified platform, before its first deal is recorded.
Pure bracketed TP/SL/SO exit comments must not produce EA groups, and every returned member must
carry a non-empty match clue in both the dialog and Excel report.
The detail HTML includes the top-right Login search form, its status region and source-aware lookup
handler. The form accepts Enter or the query button and does not change the current page when input
is invalid or lookup fails.
The complete inline script must pass the bundled Node.js syntax check before a detail-page change is
accepted.

## Compatibility and deprecation

This is the required production detail UI until an explicit, documented replacement is approved.
