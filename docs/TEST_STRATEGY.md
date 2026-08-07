# Test strategy

## Gates

- Fast: governance/document checks, application and copy-pool Producer compile, application Ruff,
  Producer correctness-only Ruff selectors and focused tests.
- Full: Fast plus all pytest/legacy tests, the versioned copy-pool Producer regression suite,
  frontend Vitest and production build, OpenAPI and architecture checks.
- Release: Full plus explicitly configured read-only live contracts, version/release readiness and
  production health acceptance, including the Playwright legacy-detail route test.

Production-version regressions require `Settings` to honor a pinned `KDESK_FRONTEND_DIST` and the
launcher to reject non-main or dirty checkouts before startup while selecting a full-Git-SHA
frontend release directory.

## Representative server matrix

| Logical server | Stable sample |
| --- | ---: |
| AC GB MT5 | 637557 |
| AC CN MT5 | 36460 |
| AC CN MT5 live3 | 241003021 |
| AC CN MT4 | 5002693 |
| AC GB MT4 | 5010772 |
| DBG MT4 CN1 | 7798437 |
| DBG MT4 CN2 | 8325931 |
| DBG CN MT5 | 2014191 |
| DBG MT4 VN3 | 113167 |
| DBG GB MT5 | 3067746 |
| DBG MT5 Live2 | 5200101 |

Contracts cover routing, MT4/MT5, USD/USC, empty orders, old aliases and shared login `10002`.
Account `309361` is the CRM-lag fallback regression: it is present only in DBG `mt5_export_new`
trade users, returns `unique_trade_user_fallback`, derives USC/USD metadata from its users-group,
and must remain unavailable if the same MT5 Login appears in another independent DBG physical source.
Expected live values are maintained in an ignored local contract fixture because account data is
not committed to GitHub. Active-account fields may be declared volatile: they must remain present
and numeric. Only values that are operationally stable retain exact/tolerance comparisons; moving
balances, net deposits, rebates and derived P/L are verified against deterministic offline fixtures
instead of an aging online snapshot.
Live3 account 241003365 is the no-daily-row USC regression sample: routing remains server code 3,
the group fallback yields `moneyScale=0.01`, and CRM rebates remain unscaled USD values. Its CRM
user 133018 also verifies cross-server same-name discovery: Live1 account 245856 and all four Live3
accounts must be returned, with finance queried from each account's own source. After clearing the
process query cache, the complete production risk-panel request must return correctly in under 10
seconds. MT5 metadata tests prohibit synchronous access to the unindexed daily view.

Rebate-discovery contracts cover all four CRM environments and eleven logical routes, daily/six-hour
sharding, exact MT5 position and MT4 ticket reconstruction, USD/USC cohorts, no candidate cutoff,
different-customer one-to-one pairing, delayed rebates, partial failure, cancellation and recovery.
The one-trade `630830` sample remains below warning without other suspicious evidence.
Account-audit regressions cover a Cent account's `0.01` standard-lot conversion, an account owned
directly by its formal IB, a non-`user_type=1` supervisory parent retained above that IB, and raw
CRM rebate aggregation even when `usd_or_usc=USC`. DBG MT5 coverage also prohibits forcing the
AC-only `idx_mt5_deals_Login_Time_Comment` index in detailed trade or cashflow reads.
Frontend tree regressions remove zero-order/zero-contribution account rows and recursively empty
customer branches only when the empty-node toggle is active. A customer row is marked `返佣过大`
only when hierarchy rebate is positive and trade P/L plus hierarchy rebate is strictly above zero;
the exact zero boundary, zero-rebate profit and IB rows remain unmarked.
Performance regressions prohibit forcing the rebate table's single-column `idx_mtLogin`, preserve
raw rebate-row counts after bounded application grouping, use 100-account batches, constrain historical discovery
to the selected period, retain the searched account in the high-recall candidate screen, limit exact
trade and cashflow reads to bounded candidates, derive high-volume structure without treating unknown
profit as zero, keep all tree rebate values independent of candidate status,
reuse per-IB recipient summaries, overlap independent hierarchy and MT evidence reads, reuse source
connections and return isolated copies from the five-minute account-audit cache. Candidate status
must not affect basic trade statistics: every routed tree account receives a complete-period
aggregate in ten-account indexed batches. The DBG CN non-candidate regression `2013813` must retain
161 orders, 18.44 standard lots and 512.25 trading P/L alongside 791.75 raw CRM rebate, and an
omitted-date request must report `query.fullHistory=true`.
MT4 account-detail regressions require open-position sentinel rows (`CLOSE_TIME=1970-01-01`) to be
excluded from closed-order counts, holding duration, daily P/L and closed profit.
Historical-funds regressions require an additive legacy-toolbar control immediately after Toxic with
working open, close and event paging handlers. MT4 replay uses close time for closed market rows,
keeps pre-anchor events with unknown balance/Credit/equity, classifies `TRS-`/`TFM-`/`TFH-`/`CRM-T`
as internal rather than external cash, and never creates intraday equity from a balance event. MT4
5005187 must retain its forced close, following `RST` clear and later `TRS` transfers separately;
MT4 5012309 must retain deposit, Credit grant/removal and clear rows. An MT5 cash/Action-3 Credit
fixture must preserve timestamp order and USD/USC scaling. Stop Out (`MT4 REASON=5`, `MT5 Reason=6`)
and explicit negative-balance clear rows must each expose a clickable liquidation marker; stop loss
and ordinary losses must not. All live validation is read-only.
DBG GB MT5 account 3066617 is the MT5 daily-view timeout regression: the historical endpoint must
not execute the unindexed daily-snapshot query, must retain the complete indexed deal ledger and
current-account-calibrated balance/Credit replay, return HTTP 200 with `dailyAnchorsAvailable=false`, and explain that historic equity snapshots are
unavailable. A total account-history failure remains HTTP 503 but returns a sanitized application
error rather than exposing raw database detail or `HTTP 503` as the only user-facing explanation.
Relationship-network regressions require the legacy entry button to remain after EA and before Toxic,
with working open, reset and close handlers. API fixtures must retain typed evidence from every
available source when another source fails, preserve selected filters, expose no risk score or
relationship-strength label, and allow EA/Copy aggregate members to expand locally without another
request. Every visible relation edge must retain a readable type label. The graph surface uses one native
high-DPI Canvas with a detached 3x raster scene cache: pan and wheel zoom must coalesce input to at most
one cache-copy redraw per animation frame, apply camera coordinates rather than CSS `translate3d`/`scale`,
and avoid re-drawing static nodes, edges and text during gestures. A node drag may draw only its active
node and incident relationships over the cached scene; cache rebuilds occur at static invalidation points.
The renderer must retain viewport culling, relation-label width caching, frame timing samples, no SVG/DOM
graph rebuild and no evidence-pane render for pointer movement. A drag of at least four screen pixels must
suppress activation on release. Canvas hit testing must preserve node and edge selection; wheel deltas must
use continuous cursor-centred scaling rather than fixed scale steps.
Kuzu-demo regressions create and close a temporary local graph file, then verify the additive standalone
page and a reopened two-hop API response preserve typed nodes, evidence edges and source counts while
depth outside the fixed `1..3` range is rejected. The test has no remote provider call and does not
assert a risk score or conclusion.
Automation-report regressions open each generated `.xlsx` and verify sheet order, table ranges,
account IDs stored as text, numeric profit formats, reconciliation formulas, valid empty-result
workbooks and download content-disposition headers. Copy reports must contain only `单主汇总` plus
one sheet per source owner; every owner sheet contains follower summaries before Position/ticket
order detail. Visual QA renders every sheet and rejects clipped headings, unreadable columns and
formula-error output.
Copy-query regressions require MT5 opening-comment authority, no first-1,000 origin-ID or first-200
source-order truncation, exact indexed comment lookup, account-level Position aggregation and page-
local Copy/EA cache invalidation only on refresh/filter change/reload. AC GB MT5 account 641903 must
map all 895 copy positions to 640598 (625, 439.89 USD) and 632824 (270, 64.43 USD), with current-
account follower totals equal to the attribution totals and a cold complete response below 10 seconds.
EA-query regressions require exact full-Comment lookup before any dynamic template read. A successful
exact result with at least two routed accounts suppresses fallback; an exact provider exception also
suppresses fallback and remains an explicit error. MT5 candidate discovery must use `Entry=0`; MT4
uses bounded COMMENT/MAGIC reads because Entry is unavailable.
Classifier fixtures cover `CPT-SS#id`, `CPT #id`, three-part `@` and slash structures, long
account-source pairs, `B1`, brace references, restart/DCA instances, CID, BuyOrder, BR/SR and
Grid/Layer levels. They verify templates, stable prefixes, labels and `countedAsEa`. Platform
SL/TP/SO, stop-out, funding/credit, origin-reference and contact-only comments remain excluded.
Previously unseen stable-text/long-number comments must create or update the local SQLite observation
without holding a Windows file handle after the request. SQL-shape tests require a valid MySQL LIKE
escape character, literal underscore/percent handling and complete adaptive subdivision of an
over-limit numeric prefix.
DBG CN MT5 account 2013674 with `ExpertID=7 + @8@` is now a possible-copy-route regression, not an
EA-family conclusion. The dialog must retain database/server-aware structural peer detail, keep
Position-level profit and USC scaling, and report zero contribution from that group to `eaSummary`.
Every returned member and workbook detail row retains its observed identifier and match clue; the
workbook EA KPIs exclude route-like groups while their detailed rows remain present.
DBG CN MT5 account 2014201 is the no-comment ExpertID-sequence regression. It must return the four
same-server accounts 2014201, 2014202, 2014137 and 2014195 as `可能是跟单路由`, expose complete-ID
and bilateral-overlap evidence, report no provider error and keep `eaSummary.groups=0`. Negative
fixtures cover same `157` prefix with different complete IDs, fewer than five shared IDs, a single
time batch, opposite direction and candidate dilution below 80%.
High-volume MT4 account 8208074 is the complete-history regression sample. Acceptance requires
59,504 closed orders, 704 daily bars, an exact 59,504 order-page total and 100 newest rows on page 1.
Unit tests assert an unlimited MT4 analytical read, one shared metric calculation and database-level
pagination without loading all orders. After a process restart, detail, risk, automation and the
first order page must each return complete data in less than 10 seconds.

Push-discovery regressions cover MT5 12-hour and MT4 daily candidate shards, adaptive timeout
bisection, exact profit/maximum-lot merging, exact MT5 distinct-position re-counts at the order-limit
boundary, per-database lifetime-query serialization, conditional active-day aggregation, and
adaptive profile-batch reconnect/shrink, and prohibition of candidate access to `mt5_daily_view`.
Tests also preserve deferred lifetime-filter semantics: structural ranking is computed first, while
all enabled lifetime restrictions are enforced before deep selection. Progressive ranked profiling
must produce the same requested Top-N as profiling every structural candidate.
Candidate-order loading tests cover bounded time-index reconstruction, exact MT5 complete-position
joins, cross-shard deal de-duplication and reconnecting split fallback. Single-account tests verify
that concurrent source queries retain configured source order and merged Tick reads reproduce each
order's exact quote slice. Structure-screen tests compare serial and bounded process-pool results in
input order; process failure must fall back to the serial implementation.
Economic-evidence regressions require positive lifetime and suspected-interval net, cover the exact
100-unit absolute boundary and the combined 50-unit/10%-of-deposit boundary, and reject negative or
economically immaterial intervals without recording them as query failures.

Bonus-arbitrage tests cover historical cycles after current Credit reaches zero, exact profit and
cash extraction, reversed withdrawal attempts, dynamic credit lifetime, repeated cycles,
locked-profit warning caps, unpaired sacrifice evidence, related-account opposing legs, Cent scaling
through the adapter contract, exact minimum-margin timestamp/order membership and replacement of the legacy
placeholder in durable Toxic jobs.
They enforce a hard inclusive 20% `赠金 / 入金` eligibility boundary and prove that 10% and 18.18%
profit-extraction cycles plus low-ratio coordinated sacrifice cannot enter a risk level or repeated
cycle escalation.
Preventive regressions require high risk when the minimum standard margin level anywhere in an
eligible Credit cycle is at or below 200%, without requiring direction concentration, withdrawal or
a visible peer. They verify the displayed equity, used margin, standard lots, exact orders and first
lowest timestamp; a late-cycle heavy position remains eligible. Visible 40% opposite-lot coverage
raises confidence but leaves the preventive-path score unchanged. Low-ratio and above-200% light
counterexamples remain below warning. Opening-only MT5 and MT4 sentinel positions must reach the
domain model, and Cent/USC monetary scaling must not alter standard lots.
Historical-breach regressions require severe risk for a negative-balance reset, cumulative closed
trading loss reaching all funded cash plus Credit, or current negative balance/equity. A later
profit recovery cannot erase a prior breach; 75%-99% funded loss warns; below-20% Credit remains
capped at 39; same-time profit/loss closes are netted before breach evaluation; and a recovered
near-breach with completed extraction remains at least high risk.
Peer-match regressions preserve one-to-one closest-time and lot-similarity semantics while a
10,000-by-10,000 related-order fixture must complete through the indexed five-second window rather
than an all-pairs scan.

Platform bonus-discovery regressions cover the 180-day and 300-account limits, all-environment
default, handled-account exclusion, descending current-margin/cumulative-deposit ordering,
deposit-reversal exclusion, ranking-query fallback, daily-to-six-hour fallback, severe-cycle
projection, peak-order and suspected-hedge detail projection, partial failure retention, durable API
recovery, routed account links and client-side level filtering.
They also enforce at most four concurrent physical-source scans and three concurrent account deep
checks, with same-source shards remaining serial. Route validation must run once after all daily
rows for a physical source are merged, candidate mappings must bypass redundant deep route lookup,
and profile/peer-family prefetch must run once before account workers start.

Position-risk regressions require the economic hard gate before weekend/open timing, explicit
configured-leverage handling, losing-event eligibility, combined weekend/reopening classification,
and a lower score for staggered additions than cohesive batches. Evidence tests require peak lots,
concurrent order count, exact order identifiers, margin amount/ratio/level formulas, actual-loss
penetration, explicit data gaps and reset-only suspicion. Peer tests require both opening and closing
within five seconds, reject late/missing closes, preserve target/peer order provenance, deduplicate the
nine configured physical sources, reject opposite pairs below 80% lot similarity and retain partial-failure coverage. Discovery tests cover the 90-day
and 300-account limits, handled-account exclusion, prohibit fallback from opening-only candidate peers,
at most four source and three deep workers, durable API
recovery, routed links, readable wrapped conclusions and the per-account analysis modal. SQL review
must confirm indexed time predicates and prohibit candidate reads from unindexed MT5 daily/position views.
Shared-source tests require CRM-specific peer server resolution, and high-cardinality fixtures require
complete totals with at most 500 detailed pairs per direction.
Optional discovery-filter regressions cover inclusive position-percent, peak-lot and event-profit
boundaries, invalid negative values, missing evidence and a retained unfiltered default. Frontend tests
require descending profit, position and score sorting without mutating the stored result list.

Cross-account hedge-query regressions require the existing `internal_lock_arbitrage` Toxic item to
replace the copied account-internal score with opposite-only all-platform evidence. They cover target
entry projection, open-position exclusion, exact subject/peer order provenance, the inclusive 80%
lot-similarity boundary, rejection below that boundary, nine-source coverage,
partial-failure language, Worker replacement and the dedicated account and order tables. A clean
no-match result is forbidden when any physical source failed. Saturated multi-target opening queries
must recursively split and retain every row; only a saturated single-target window may fail coverage.
MT5 prefilter tests retain same-direction candidates for position-risk coordination, but require the
dedicated hedge query to remove same-direction, wrong-symbol and below-80%-lot openings before Position
completion. SQL-shape tests require the same hedge constraints inside the indexed MT5 opening query.

K-line regressions cover suffix/Roll/UT100 mapping, preferred and fallback source order, use of the
unscoped default Terminal as a strict fallback for server-routed database jobs,
fallback thresholds, initial GMT/GMT+3 then expanded offsets, low-confidence rejection, partial
success, old mapping/cache compatibility and structured job failures. Offline quote profiles keep
gold and GBPUSD accepted while BTCUSD, XAGUSD and AUDCAD anomalies must reject or warn. Gap fixtures
span 2,946 through 4,383 minutes and assert compressed boundary labels, elapsed-time blanks and no
cross-gap aggregation. Browser checks cover standalone, iframe and task-center desktop/mobile layout,
nonblank canvas pixels and both time modes.
K-line funds/position replay tests require a selected account route, exact Balance/Credit carry-in
or an explicit unknown state, separate funds/order event categories, no default 10,000/1:500 funding
fallback, usable liquidation markers, paged event rows and standalone HTML JavaScript parsing. They
also require the replay option to be off by default, one complete cache build, no source read on a
subsequent chart request, an explicit-refresh rebuild, invalid-cache recovery and full-history default
dates. Every visible K-line funds-panel liquidation marker and its event-table action must move the
viewport to the same factual timestamp.

The standalone replay uses the same visible summary, curve and detailed-event hierarchy as
`历史资金回溯`. Funds ledger rows and each market order opening/closing event must remain individual,
chronological source rows with their factual post-event Balance/Credit values. The table must not fold
Position lifecycles or sum source-event deltas; the Balance/Credit curve keeps the same original
source-event resolution.

Dynamic copy-pool monitor regressions cover malformed or missing snapshot files, stale-source age,
bounded event/timeline reads, account-product effective-weight projection, virtual-position contribution,
client Demo loss budgets, sanitized source Position/Demo Ticket mappings and per-product
long/short/net/locked exposure,
detailed Login/platform/server projection without raw private-state structures and strict `C001`
alias redirects to the compatible platform/server-aware account page. Frontend tests cover detailed
account labels, Chinese operational labels and chart geometry. Browser acceptance uses an isolated
service with live local snapshots at desktop and mobile widths and confirms explicit base/current
weight comparison, reduction reason, readable event/gate sections and account links. The legacy
account detail contract must not embed a `复制实验` section or call the copy-pool dashboard.
Producer CSV tests require an exact ordered header and row width for event, order and timeline
streams, rotation of a mismatched legacy header/data layout before startup counter/latency
restoration, byte-preserved timestamped archives and a newly headed current file so dashboard
`DictReader` fields cannot shift. Multi-source regressions require its schema override to survive
base initialization, MT5 then MT4 event normalization without rotation, and independent then
flatten order normalization without rotation.
Event-reason regressions require each new MT4/MT5 entry to persist one bounded event-time
`reason_code`, including minimum-risk-lot, signal-expired, restart-monitor and each supported
execution-gate code. Dashboard tests assert separate `decision`/`reasonCode`, rejection of unknown
free text and compatibility for old rows without the column. Frontend helper and mounted-page tests
must display the exact localized code and must never fall back to the former combined
point-spread/delay/external-position guess.
Execution-quality dashboard tests additionally require an explicit deferred historical-delay state,
cashflow-adjusted drawdown coverage, holding/overnight/weekend fields, factor gate-code filtering,
pool-tier projection and scheduler/dynamic-sleeve state. A dynamic state row with an unmapped private
sleeve key must be omitted from both top-level and per-sleeve output.
Drawdown regressions require pre-funding zero rows and the first funding movement not to create a
false loss, raw platform equity below zero to retain `negative_equity`, and later cashflow-adjusted
capital exhaustion to use its own non-compensable reason. An incomplete reconstructed path cannot
set the platform-negative code when the authoritative daily aggregate is clean. MT4 and MT5
repository tests require one bounded 61-day daily read, prohibit any pre-window history query and
retain fail-closed 20/60-day coverage; a new account's first funded observation supplies its first
daily baseline. Factor-service tests require more than one and at most four physical-source history
loads in flight, one load per source, stable merging and whole-build failure on any source error.
Dashboard tests also pin hourly score, one/four-hour net P/L, current comprehensive-profit hard-gate
state and bounded hourly-discovery coverage.
Producer tests prove that deferred mode performs no Tick-cache load, removes delay from score and
hard gates, normalizes the remaining six weights to 100%, and keeps the five-second/P25 runtime
signal-age cap plus entry/exit expiry counters.

All-source copy-pool regressions additionally pin eleven logical routes to nine physical sources,
including `crm_vn` code 2 versus code 5, composite identity for repeated Login values, independent
source cursors, MT4/MT5 position semantics, Cent money-only scaling, account-product normalization, source
outage gates and current-day restart recovery. MT5 ledger-action tests require cursor progression
without position, trading-P/L, weight or signal changes; simulations also cover duplicate/out-of-
order isolation, MT4 snapshot reversal and rejection of incomplete accepted-pool coverage.
Runtime-polling regressions require all five selected MT5 physical sources to start before any
source finishes, require the accepted historical build timeout to switch to a two-second live
connect/read/write profile, and prove that ready MT5 events are applied while an MT4 snapshot wave
is still blocked. A timed-out source must retain its cursor and expose failure without discarding
successful sibling-source results.
Read-only preflight acceptance requires 11/11 route
and 9/9 physical coverage, at least ten deployable clients, no ambiguous shared-source Login in the
pool and no MT initialization or order. Dashboard contracts cover the source funnel, runtime health
and composite-key P/L/position joins without returning private state wholesale.
Independent execution tests require startup and shadow positions to remain monitor-only; source
open/add/reduce/close/reverse to affect only owned Demo Tickets; reversal to close and reconcile
before opening the new direction; and A-client events never to modify B-client Tickets. Restart must
reject both unowned actual Tickets and missing persisted Tickets. Exact offsetting gross positions
must still flatten for outage, Friday, daily/equity/margin hard stops. Client tests cover the
20/50/80/100% loss curve, two-hour pause, 15-minute recovery shadow, slow weight recovery, minimum
risk-lot rejection, 12/24-hour rules, 40% cluster cap and 15%/25% margin gates.
The Demo minimum-lot regression must keep one source Position's Ticket unchanged across repeated
reconciliation while eligible same-direction siblings receive independent Tickets only within the
whole-portfolio stress budget. Budget regressions require a
tiny-weight active client to receive the 20% cycle-budget floor only for the explicit
`ACCMGlobal-Demo`/`StagedLive` switch, prove that a 0.69 USD loss does not exhaust that floor, and
retain weight-proportional behavior without the switch or on another server/mode. A realistic gold
fixture must prove that two same-direction 0.01-lot stress amounts above the ordinary 40% cluster
share are executable under the explicit Demo switch while the next minimum is rejected by the
unchanged whole-portfolio stress budget. A rolling
order-storm fixture must hard-stop before a ninth open request in 60 seconds. MT4 adapter tests
preserve AC raw UTC and convert DBG CN Live1/Live2 raw UTC+3 to UTC; Live3 remains in the complete
physical-route set under its provisional UTC+3 convention. A normalized snapshot observed two or
three seconds later remains within the five-second budget. A risk-rejected source Position without
a Demo child cannot open on a 40-second retry, while an expired Position with an owned child can
still reduce or close.
Risk-deadline regressions additionally require an expired same-direction addition to keep the
existing Ticket unchanged, an expired reversal to close the old Ticket without opening its opposite
leg, and a final deadline check immediately before the broker call. Persistence tests require only
open/increase/reversal events to refresh `risk_signal_at`. Current-copy contracts require one row
per actual Demo Ticket, real Login identity, exact source floating P/L, exact Demo comment P/L,
Cent money normalization and `null` rather than allocated account P/L when evidence is unavailable.
Producer regressions also pin the broker-retained 16-character independent comment, migrate older
overlong persisted comments, persist source ownership on both sides of execution, recover exactly
one comment-plus-product owner after an interrupted post-fill write, and keep ambiguous/unmatched
Tickets rejected.
MT5 polling regressions apply a same-batch complete open/close round trip to cursor and realized P/L
without invoking independent execution, coalesce multiple opening Deals to one residual target and
use the opposite entry timestamp for a same-batch reversal. They also pin reduction-before-addition
ordering, durable pending serialization, sibling continuation after one failure and the distinct
`signal_expired_no_copy` disposition. Restart fixtures cancel pending additions, retain only the
risk-release side of pending reversals and reject malformed journals.
Daily-build holding regressions require proactive five-day MT5 reads, then force both Login and time
subdivision to merge a Position across adjacent windows with its exact duration. Minimum-window
failure remains explicit and cannot silently remove an account or sample.
Restart no-chase regressions also persist an eligible open source Position without a Demo child,
prove live reconciliation sends no replacement order and preserves the explicit monitor reason,
retain and close a uniquely recovered real Ticket, and remove a monitor-only mapping when its source
closes without a Demo action.
Open-risk regressions require closed profit with a large floating loss to lose quality, positive
floating P/L to add no score, negative realized and floating components to reduce weight without
positive-component offset, Cent money-only conversion, gross exposure retention under a zero-net
hedge, exact 10% floating-loss and 50% margin/equity hard boundaries, restart persistence and
rejection of incomplete selected-source floating state. Browser acceptance shows realized,
floating and dynamic values separately and keeps zero-net hedged accounts in the position filter.
Execution-quality scheduling regressions require the hourly schedule to be consumed exactly once,
the cached factor-ready universe to rank 30 unique monitor plus 70 unique reserve clients, current
comprehensive loss to remain a hard rejection, and one/four-hour strength to affect only ordering.
Execution-weight regressions require non-activity sleeves and monitor dynamic sleeves to project zero
current weight even when cached source quality is positive; active-client counts must use active
dynamic sleeves rather than risk-ledger status.
Service rotation tests require newly observed source positions to remain monitor-only, offline
increases/reversals never to be chased, offline reductions/closes to reduce risk, and daily rebuilds
to preserve execution suspension while resetting the old-position boundary. Versioned Producer
tests additionally require hourly membership to survive restart, missing hourly values to remain
unknown, zero-member sources to report idle rather than failed and the explicit Demo minimum-lot
exception to retain portfolio stress, direction and margin limits.
Entry-activation regressions require a fresh hard/activity/minimum-lot-qualified sleeve to enter
`ACTIVE` on its first ranking without the fast-activation switch. They also pin immediate monitor
fallback on factor disqualification, non-positive current comprehensive product profit or lost
activity eligibility. Legacy `ENTRY_SHADOW` fixtures must promote on the next qualified ranking and
remain readable by the monitor. Status projection reports one required ranking and zero entry-shadow
minutes while retaining the compatible fast-activation requested/effective fields.

## Release acceptance

Both readiness endpoints, one live interactive Worker and one live discovery Worker, account 302360 legacy detail HTML, account 7798437 finance, Live3,
DBG MT5 Live2 account 5200101 routing/finance/orders, rebate, copy/EA, Toxic job recovery, K-line
generation and rollback rehearsal must pass. Remote
tests are read-only and never mutate MT or CRM state.

Hierarchy routing regressions require all configured CRM/server routes to be derived from the
central source registry. They pin `crm_vn` code 2 to `mt5_export_new`, code 5 to
`crm_vn_mt5_live2`, prohibit fallback for unknown codes, require DBG-qualified ambiguity targets,
and verify that product discovery reads each physical source once while retaining Live2 products.
