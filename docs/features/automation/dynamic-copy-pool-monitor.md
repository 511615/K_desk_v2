---
feature_id: AUT-POOL-001
title: Dynamic copy-pool monitor
module: automation
status: active
apis: ["GET /copy-pool", "GET /api/copy-pool/dashboard", "GET /copy-pool/accounts/{alias}"]
code: [".env.example", "src/kdesk/settings.py", "src/kdesk/application/copy_pool_monitor.py", "src/kdesk/infrastructure/copy_pool_monitor.py", "src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py", "frontend/src/main.ts", "frontend/src/pages/WorkbenchPage.vue", "frontend/src/pages/CopyPoolPage.vue", "frontend/src/copyPool.ts", "services/copy_pool_runtime/run_copy_demo_live.ps1", "services/copy_pool_runtime/copy_delay_replay_domain.py", "services/copy_pool_runtime/copy_dynamic_pool_domain.py", "services/copy_pool_runtime/copy_independent_execution.py", "services/copy_pool_runtime/copy_pool_equity_reconstruction.py", "services/copy_pool_runtime/copy_pool_factor_domain.py", "services/copy_pool_runtime/copy_pool_factor_service.py", "services/copy_pool_runtime/copy_pool_history_adapter.py", "services/copy_pool_runtime/copy_pool_history_repository.py", "services/copy_pool_runtime/copy_pool_multisource.py", "services/copy_pool_runtime/copy_product_catalog.py", "services/copy_pool_runtime/copy_quote_replay_cache.py", "services/copy_pool_runtime/copy_trading_demo.py", "services/copy_pool_runtime/copy_trading_live_core.py", "services/copy_pool_runtime/copy_trading_live_demo.py", "services/copy_pool_runtime/copy_trading_multi_demo.py", "services/copy_pool_runtime/mt5_quote_partition_provider.py"]
tests: ["tests/test_copy_pool_monitor.py", "legacy/apps/problem_account_registry/test_app.py", "frontend/src/copyPool.spec.ts", "services/copy_pool_runtime/tests/test_copy_delay_replay_domain.py", "services/copy_pool_runtime/tests/test_copy_dynamic_pool_domain.py", "services/copy_pool_runtime/tests/test_copy_independent_execution.py", "services/copy_pool_runtime/tests/test_copy_pool_equity_reconstruction.py", "services/copy_pool_runtime/tests/test_copy_pool_factor_domain.py", "services/copy_pool_runtime/tests/test_copy_pool_factor_service.py", "services/copy_pool_runtime/tests/test_copy_pool_history_adapter.py", "services/copy_pool_runtime/tests/test_copy_pool_history_repository.py", "services/copy_pool_runtime/tests/test_copy_pool_multisource.py", "services/copy_pool_runtime/tests/test_copy_quote_replay_cache.py", "services/copy_pool_runtime/tests/test_copy_trading_live.py"]
depends_on: ["ACC-DETAIL-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-30
---

# Dynamic copy-pool monitor

## Purpose and user entry

The workbench navigation exposes `动态跟单`, a dense read-only operations page for the running
all-route, cross-product dynamic customer-pool Demo experiment. It presents account-product
sleeves, independent source-position to Demo-ticket ownership, effective weights, client loss
budgets, execution decisions, account equity and safety gates.

## Independent execution model

Selection and monitoring use `account + normalized product` sleeves across every supported Demo
product. The first candidate gate is strictly positive 20-day closed trading net plus current
same-product floating P/L. The cross-product population targets up to 30 unique monitored clients
and up to 70 unique reserve clients, not 30 clients per product; all hard-qualified sleeves belonging
to a selected client remain visible. A non-empty qualified monitor population may proceed below the
30-client target instead of weakening hard risk gates, while an empty population stops preflight.
Product sleeve floors and a 40% monitor-account cap protect product coverage, with explicit fallback
metadata when the floor/cap combination cannot be satisfied.
Holding-period, copyability and minimum-risk-lot checks decide which sleeves can execute.

Execution ownership is `account + source Position -> one or more Demo Tickets`. Customer opening,
increasing, reducing, closing and reversing events affect only those mapped Tickets. Opposing
customers remain independently open; net exposure is display and combination-risk evidence only.
Existing source positions at startup and positions first observed during shadow are not chased.
Restart requires persisted and actual Ticket ownership to match exactly.
Closed source mappings remain in the current trading-day ledger so realized Demo P/L continues to
consume the correct client's loss budget; empty closed mappings are pruned on the next trading day.
Independent order comments are deterministic 16-character identifiers that survive the Demo
server's comment limit without truncation. A source-position change is atomically persisted before
and after execution. If a process interruption leaves an actual Ticket ahead of the second write,
restart or the next loop may recover it only when comment and product match exactly one persisted
source position; ambiguous or unmatched Tickets remain an execution hard stop.

Base sleeve weights total 100%. Product weights use a 40% diversification cap when at least three
qualified products make that cap feasible; with fewer products the unallocatable remainder is
distributed evenly and the fallback is disclosed instead of silently shrinking the base-weight
total. Combination risk utilization and the live 40% product-direction cluster limit remain
separate. The copier applies a 1.5% cycle-loss budget, 3% daily stop, per-client Demo loss budgets,
and 15% soft/25% hard margin limits. Client loss use follows the 20/50/80/100% reduction curve;
exhaustion closes only that client, pauses two hours and requires a 15-minute recovery shadow.
Twelve-hour positions cannot add risk and 24-hour positions close and pause that client.

Historical Tick delay replay is deferred from V0.1 because its cross-product validation cost is not
yet accepted. It does not participate in score or hard eligibility, and missing Tick partitions do
not reject a sleeve. The remaining six weights are normalized to 25/18.75/18.75/12.5/12.5/12.5
for five-day and 20-day risk-adjusted return, spread stress, PF structure, return/MDD and holding
quality. Drawdown still uses cashflow-adjusted equity including synchronized floating P/L; missing
position-path or intraday-equity evidence remains monitor-only rather than clean. A/TA status adds
0.02 only after hard gates. Real-time quote age, database staleness, measured signal latency and
entry/exit expiry remain execution gates; without historical break-even evidence, a new-risk signal
budget is capped at five seconds and `holdP25 / 3`, whichever is lower.

The producer processes source events every 500 ms, refreshes client and sleeve risk every 10
seconds, re-ranks the monitor/reserve range every 15 minutes, performs a bounded one/four-hour
accepted-universe discovery every hour and completely rebuilds at 05:15 Beijing. Hourly discovery
never repeats the 60-day factor query and cannot promote a historical hard-gate failure. Two
consecutive active-zone results and ten healthy shadow minutes are required before execution.
An entry-shadow health failure caused by a transient operational gate, including the first pending
source-position reconciliation frame, retains the sleeve's two ranking qualifications but restarts
the full ten-minute continuous-health window. Loss of factor qualification, current comprehensive
product profit or activity eligibility returns the sleeve to monitor immediately, and no weight
becomes executable before the restarted window completes.
Hourly current-position evidence uses collision-free `current` column names, preserving daily
build-time floating/hedge columns when a product currently has no open position.
Hourly monitor-only sleeves receive no provisional execution base weight. Producer status and the
dashboard define active weight as the final executable minimum of source quality, dynamic sleeve
state and client risk reduction; `activeCopyClients` counts only clients with an active dynamic
sleeve, while risk-ledger membership is reported separately.
Restoring a versioned, fully covered accepted cache records its build day in scheduler state, so a
post-05:15 restart does not immediately repeat the same full build. The producer publishes a fresh
status snapshot before entering its first polling cycle. Each successful hourly rotation also
persists the accepted same-day pool. Restart therefore restores the latest membership instead of
rolling back to the initial daily pool; a legacy snapshot without hourly evidence keeps those
values unknown and schedules an immediate bounded discovery refresh.

The optional `-AllowDemoMinLotOverride` test switch is valid only for `ACCMGlobal-Demo` in
`StagedLive`. It may promote one minimum lot for a product/direction when a client's normal stress
allocation is smaller, but only while whole-portfolio stress and margin permit it and no copied
Ticket already occupies that product/direction. It does not bypass quote, spread, database,
Ticket-ownership, daily-stop, equity-floor or margin hard gates and is never implicit.

The optional `-DemoFastActivation` switch is also effective only for `ACCMGlobal-Demo` in
`StagedLive`. It changes entry from two consecutive rankings plus ten healthy minutes to one
qualified ranking plus two continuously healthy minutes. It does not authorize trading, bypass an
operational or risk gate, chase a position observed during shadow or increase weight while health is
false. Without the switch, and on every other server or mode, the normal two-plus-ten policy remains
authoritative.

## UI and behavior

The page refreshes the dashboard snapshot every second. It uses the K_desk dark operations theme,
Chinese labels and responsive desktop/mobile layouts. Every visible account label, event, mapping and
filter uses the actual trading Login; the private `C001` alias remains an internal mapping and redirect
identifier only. Platform/server context remains a secondary line.
On narrow screens, source-health rows reduce their fixed columns and gaps while retaining the
candidate/eligible/selected funnel and latency; wide account tables scroll inside their own panel
without widening the page.

Weight views show each account-product sleeve's base weight, executable weight, reduction amount
and reason. The table distinguishes historical factor score from hourly dynamic score and shows
one/four-hour net performance plus the current comprehensive-profit hard gate. The page also shows
client loss-budget use, source Position to Demo Ticket mappings,
per-product quotes, gross long/short, net and locked exposure, equity history, database latency,
strategy P/L, recent source/risk/order events and the current execution gates. Search
and filters are presentation-only and never affect the copier.

The `客户池层级与影子准入` panel is an interactive tabbed read view. Its seven tabs are `活动跟单池`,
`入场观察`, `监控池`, `候补池`, `恢复观察`, `执行暂停` and `硬门拒绝`; each shows the current
account-product sleeve count. Selecting a tab immediately replaces the panel body with that tier's
account table, including trading Login detail links, product, planned/effective weight, current tier
and primary reason. Runtime `dynamicSleeves` overrides the daily pool tier when present. Material
client-risk states for recovery, pause/flatten or hard rejection override both dynamic and daily
tiers; other client-risk state contributes only the displayed reason. This is presentation-only and
does not alter membership, rank or execution.

The open-position risk section shows account count, position count, XAUUSD gross and net lots,
floating P/L, oldest open age, floating-loss ratio, margin/equity usage and XAUUSD hedge ratio.
Gross lots remain visible when opposing positions make net lots zero. The current-position filter
uses open-position count, so internally hedged accounts are not hidden. Pool rows distinguish
intraday realized trading P/L, current floating P/L and the negative-only dynamic evaluation used
for weight reduction.

The full-source panel shows eleven logical-route and nine physical-source build coverage plus
candidate, eligible and selected-account counts for every physical source. A successfully built
source with zero selected customers is projected as `idle/unsubscribed` and displayed as
`已接入，当前无订阅账号`; it remains available for coverage health rather than appearing as a
connection failure. Only an explicit runtime `error` is displayed as a read failure.

The legacy account detail page does not embed copy-pool data. Account links from `/copy-pool` still
open the compatible Login plus platform/server detail route; all copy-pool monitoring remains on
the dedicated page.

## API contract

`GET /api/copy-pool/dashboard` accepts bounded `timeline_limit`, `event_limit` and `order_limit`
query parameters and returns camelCase status, account-product pool, timeline, event and order rows,
plus additive `clientRisks`, `copyPositions`, `ticketMappings` and `exposures`. It is additive
and read-only. Pool rows intentionally expose `accountLogin`, `accountPlatform` and `accountServer`
for operators on the localhost risk workbench; no password, credential, contact field or complete
private route object is returned. The response additively exposes `sourceCoverage`, route/source
identity on pool rows, per-source identity on events and all-route health fields in status. Source
coverage also exposes actual monitor, reserve and active counts, selected/active products and the
product-weight cap fallback.
The additive execution-quality contract includes hourly score, one/four-hour net P/L, current
comprehensive 20-day P/L, hourly hard/activity eligibility and hourly discovery coverage. When a
restarted daily cache has not yet received its hourly refresh, current comprehensive P/L and hourly
hard/activity fields are `null` rather than fabricated as `0` or `false`. The UI labels this state
`待小时刷新`, displays the daily-build comprehensive value with its build-time basis, and does not
misstate a hard-gate result.

Execution-quality producer snapshots additively project per-sleeve `poolTier`, factor readiness,
base score, bounded factor/gate reason codes, factor components, `delay`, `drawdown` and
`holdingQuality` objects. `historicalDelayFactorEnabled=false` and
`delayFactorStatus=deferred_v0_1` distinguish compatibility delay fields from active evidence;
their zero values do not mean a customer failed a delay test. Drawdown exposes the 20/60-day and
current measures with coverage; holding exposes overnight/weekend, swap and long-loss quality. The dashboard also returns
sanitized `dynamicSleeves` and `scheduler` state. A dynamic sleeve is returned only after its private
sleeve key matches a current public alias/product route; unknown mappings are omitted. The fields do
not expose composite account keys, source keys, order comments or arbitrary private reason text.
Status also projects whether Demo fast activation was requested and effectively enabled, plus the
effective ranking count and shadow duration, so an ignored server/mode-incompatible request is
visible without exposing private routing state.

`GET /copy-pool/accounts/{alias}` accepts only `C` plus three digits, resolves the private local
mapping server-side and returns a 307 redirect to the compatible
`/account/{login}?platform=...&server=...` detail route. Unknown or invalid aliases return 404.

## Data, routing and read-only constraints

The monitor reads local files from `KDESK_COPY_POOL_OUTPUT_DIR`, defaulting to
`<KDESK_LEGACY_OUTPUT>/copy_live_demo_capital10k`. Public status, pool, event, order and timeline
files supply presentation data. The private runtime state is used only to derive pool virtual
positions, product effective weights, client Demo loss budgets and independent Ticket ownership.
`client_routes_private.json` supplies the displayed Login/server,
composite account key, logical route, physical source and server-side detail redirect.
`source_coverage.json` supplies the accepted build funnel. Runtime positions and P/L join by
composite account key, with legacy Login keys retained only as a compatibility fallback. Neither
private file is returned wholesale or logged.

The accepted same-day pool cache is valid only when its metadata and coverage file contain the
exact configured eleven-route and nine-source sets and every source completed successfully. MT5
polling intentionally reads non-trading ledger actions so each physical cursor can advance past
them; those actions never change virtual positions, intraday trading P/L, dynamic weights or source
signals. MT4 remains snapshot-authoritative. The producer persists effective weights by composite
account key; the dashboard prefers that current mapping over historical event rows and clamps any
legacy fallback to zero through the accepted pool's base weight.
The producer also persists normalized per-account open-risk state. The dashboard prefers the
runtime projection over the build-time snapshot, while missing legacy fields degrade to the build
values without inventing a clean current state. Missing hourly discovery fields remain unknown and
never fall back to daily factor readiness or daily activity eligibility.
The hourly discovery reads only the accepted daily universe cache plus bounded current-session
facts. When membership changes, current source positions are bootstrapped as monitor-only; retiring
clients with same-day Ticket/P&L ownership stay subscribed until the daily ledger reset. A restart
may apply missed reductions or closes, but never approves an offline source increase or reversal.
The v6 execution-quality and sparse-product fallback `pool_public.csv` columns are a local producer
contract. K_desk projects
only their documented numeric/boolean fields and bounded gate codes, while status-level scheduler
and dynamic sleeve records are anonymized through the current route map before response assembly.

The page does not query MySQL or MT terminals and does not start, stop or modify the copier. It has
no order, balance, permission or MT Manager write action.

## Business rules and units

K_desk does not recompute customer selection, base weights, open-risk penalties, client loss-budget
reductions or copied lots. It displays the latest values produced by the governed copier. Money is
USD, positions are standard lots, product spread is ask minus bid and database latency is seconds.
The pool excludes rebates and uses money-only Cent normalization. Opposing customers are never
presented as if one customer's event closed another customer's Ticket.

## Loading, empty and failure behavior

The page has explicit loading, unavailable, request-failure and empty-filter states. A status file
older than five seconds is marked stale. Missing or malformed optional CSV/JSON files degrade to
empty sections; they never expose raw parse exceptions or synthesize account identities.

## Code and dependencies

The application service owns the read-only repository port. The infrastructure adapter parses and
sanitizes local snapshots. The account API composes the service and owns the private redirect. Vue
presentation helpers contain only localization and SVG path generation.

The production producer is versioned with K_desk under `services/copy_pool_runtime`. Its launcher
resolves every Producer module from its own directory, while Terminal, Input, Output and the local
`D:\risk\pydeps` dependency directory remain external runtime resources. Production and development
worktrees therefore execute physically separate Producer source trees without duplicating local
market data or MT terminal state.

## Tests and acceptance

Backend tests cover snapshot parsing, account-product weights, client budgets, Ticket mappings,
gross/net/locked exposure, derived contribution/open-risk state, explicit missing-file
behavior, detailed and composite account identity, absence of raw private-state structures,
all-source coverage, bounded dashboard API output and alias detail redirect. Frontend tests cover detailed account labels,
Chinese independent-execution state/event labels, open-risk wording, holding-duration formatting and bounded line/step chart paths.
They also cover idle/unsubscribed successful build sources, nullable hourly evidence and Chinese
unknown-state labels.
Tier-tab tests cover dynamic-sleeve and risk-state tier precedence, real Login-only row rendering,
tab counts and interactive switching without exposing aliases.
Legacy-page tests preserve the account detail route and assert that no copy-experiment panel or
dashboard fetch is embedded. Production
build and desktop/mobile browser inspection are required before handoff.
Producer tests additionally cover hourly hard-gate ranking, bounded unique-client 30/70 rotation,
non-empty populations below the monitor target,
single-consumption discovery scheduling, restart missed-add suppression and daily suspended-state
preservation. They also require hourly pool persistence, unknown rather than zero restart evidence,
idle source semantics and the bounded explicit Demo minimum-lot exception.
Producer and dashboard tests also cover the explicit Demo fast-activation scope, one-ranking/two-
minute policy, default two-ranking/ten-minute compatibility and effective status projection.

## Compatibility and deprecation

The feature is additive. Existing `/`, `/account/{login}`, `8777/8766` ports and account APIs are
unchanged. Removing the dashboard requires removing its navigation entry and routes together; local
snapshot files remain independently usable by the copier.
