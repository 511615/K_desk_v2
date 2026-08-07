---
feature_id: AUT-POOL-001
title: Dynamic copy-pool monitor
module: automation
status: active
apis: ["GET /copy-pool", "GET /api/copy-pool/dashboard", "PUT /api/copy-pool/controls", "GET /copy-pool/accounts/{alias}"]
code: [".env.example", "src/kdesk/settings.py", "src/kdesk/application/copy_pool_monitor.py", "src/kdesk/infrastructure/copy_pool_monitor.py", "src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py", "frontend/src/main.ts", "frontend/src/pages/WorkbenchPage.vue", "frontend/src/pages/CopyPoolPage.vue", "frontend/src/copyPool.ts", "frontend/src/beijingTime.ts", "scripts/start_prod.ps1", "services/copy_pool_runtime/run_copy_demo_live.ps1", "services/copy_pool_runtime/copy_delay_replay_domain.py", "services/copy_pool_runtime/copy_dynamic_pool_domain.py", "services/copy_pool_runtime/copy_independent_execution.py", "services/copy_pool_runtime/copy_manual_controls.py", "services/copy_pool_runtime/copy_pool_equity_reconstruction.py", "services/copy_pool_runtime/copy_pool_factor_domain.py", "services/copy_pool_runtime/copy_pool_factor_service.py", "services/copy_pool_runtime/copy_pool_history_adapter.py", "services/copy_pool_runtime/copy_pool_history_repository.py", "services/copy_pool_runtime/copy_pool_multisource.py", "services/copy_pool_runtime/copy_product_catalog.py", "services/copy_pool_runtime/copy_quote_replay_cache.py", "services/copy_pool_runtime/copy_trading_demo.py", "services/copy_pool_runtime/copy_trading_live_core.py", "services/copy_pool_runtime/copy_trading_live_demo.py", "services/copy_pool_runtime/copy_trading_multi_demo.py", "services/copy_pool_runtime/mt5_quote_partition_provider.py"]
tests: ["tests/test_copy_pool_monitor.py", "tests/test_production_versioning.py", "legacy/apps/problem_account_registry/test_app.py", "frontend/src/copyPool.spec.ts", "frontend/src/beijingTime.spec.ts", "frontend/src/pages/CopyPoolPage.spec.ts", "services/copy_pool_runtime/tests/test_copy_manual_controls.py", "services/copy_pool_runtime/tests/test_copy_delay_replay_domain.py", "services/copy_pool_runtime/tests/test_copy_dynamic_pool_domain.py", "services/copy_pool_runtime/tests/test_copy_independent_execution.py", "services/copy_pool_runtime/tests/test_copy_pool_equity_reconstruction.py", "services/copy_pool_runtime/tests/test_copy_pool_factor_domain.py", "services/copy_pool_runtime/tests/test_copy_pool_factor_service.py", "services/copy_pool_runtime/tests/test_copy_pool_history_adapter.py", "services/copy_pool_runtime/tests/test_copy_pool_history_repository.py", "services/copy_pool_runtime/tests/test_copy_pool_multisource.py", "services/copy_pool_runtime/tests/test_copy_quote_replay_cache.py", "services/copy_pool_runtime/tests/test_copy_trading_live.py"]
depends_on: ["ACC-DETAIL-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-07
---

# Dynamic copy-pool monitor

## Purpose and user entry

The workbench navigation exposes `动态跟单`, a dense read-only operations page for the running
all-route, cross-product dynamic customer-pool Demo experiment. It presents account-product
sleeves, independent source-position to Demo-ticket ownership, effective weights, client loss
budgets, execution decisions, account equity and safety gates.

Immediately below the scheduling cadence and entry-event panel is the pinned Demo account ledger.
It identifies the current Login and server, shows balance, equity, used/free margin and margin
level, then lists every actual MT5 open position and the most recent 30-day trading Deals. The
independent current-copy mapping follows directly after it, keeping source Position to Demo Ticket
ownership adjacent to the account ledger. Rows distinguish copier-owned activity from other account
activity. The Producer writes this account-scoped projection atomically every five seconds and
caches the bounded history query for ten seconds; the 8777 monitor only reads the local projection.
MT5 comments, Magic values, private source keys and credentials are never exposed.

## Independent execution model

Selection and monitoring use `account + normalized product` sleeves across every supported Demo
product. The first candidate gate is a close within the rolling seven-day activity window, followed
by strictly positive rolling 30-day closed trading net plus current
same-product floating P/L. The cross-product population targets up to 30 unique monitored clients
and up to 70 unique reserve clients, not 30 clients per product; all hard-qualified sleeves belonging
to a selected client remain visible. A non-empty qualified monitor population may proceed below the
30-client target instead of weakening hard risk gates, while an empty population stops preflight.
Product sleeve floors and a 40% monitor-account cap protect product coverage, with explicit fallback
metadata when the floor/cap combination cannot be satisfied.
Holding-period, copyability and minimum-risk-lot checks decide which sleeves can execute.

Once a sleeve passes the hard factor, cost, holding and copyability gates, its factor score is
used for proportional base-weight allocation. The score is not itself a second eligibility floor:
there is no `monitor_score > 0.55` requirement. A lower-scoring hard-qualified sleeve receives a
smaller positive base weight when its product and client caps permit it; current floating risk,
loss budgets, margin, quote, latency and portfolio limits may still reduce its executable weight
or reject a new order at runtime.

Execution ownership is `account + source Position -> one or more Demo Tickets`. Customer opening,
increasing, reducing, closing and reversing events affect only those mapped Tickets. Opposing
customers remain independently open; net exposure is display and combination-risk evidence only.
MT4 may replace the source Ticket after a partial close. When the authoritative open residual has
the direction-consistent smaller lot and its Comment proves the prior Ticket (`from #<Ticket>`),
the Producer rekeys that one source-position mapping to the replacement Ticket. It preserves the
existing owned Demo Ticket and original signal time, so the residual is one reduction rather than a
new, stale entry. Unproven, direction-changing or larger replacements remain ordinary snapshot
changes and receive no inferred ownership migration.
Existing source positions at startup and positions first observed during shadow are not chased.
Restart requires persisted and actual Ticket ownership to match exactly.
The governed launcher supplies the explicitly approved Demo Login. During initialization the MT5
adapter selects that saved portable-terminal account on `ACCMGlobal-Demo` when another account is
active, requires consecutive matching identity samples through the asynchronous terminal transition,
verifies Demo trade mode and hedging, then pins the exact Login. It never supplies or stores a
trading password. A failed or unstable selection and any different Login/server after selection are
fail-closed.
Every later account sample must retain that identity; an inconsistent IPC sample is rejected before
sizing, risk evaluation, status publication or order execution. The last valid dashboard snapshot
remains authoritative while the account channel is inconsistent.
Closed source mappings remain in the current trading-day ledger so realized Demo P/L continues to
consume the correct client's loss budget; empty closed mappings are pruned on the next trading day.
Independent order comments are deterministic 16-character identifiers that survive the Demo
server's comment limit without truncation. A source-position change is atomically persisted before
and after execution. If a process interruption leaves an actual Ticket ahead of the second write,
restart or the next loop may recover it only when comment and product match exactly one persisted
source position; ambiguous or unmatched Tickets remain an execution hard stop.
After that recovery pass, every restored open source Position that still has no actual child Ticket
is persistently downgraded to `restart_without_demo_ticket`. It remains monitor-only across every
live reconciliation and is removed when the source closes; restart never turns it into a replacement
Demo order. A uniquely recovered or already mapped Ticket remains eligible for reduction, close and
risk management.

After rolling-30-day cost-adjusted comprehensive-profit and non-compensable account-data gates,
every executable sleeve receives proportional base-weight input. Drawdown, holding, carry and
recent-performance evidence are ranking warnings and score inputs, not a second eligibility filter.
The adjusted score is not subject to a separate
`0.55` activity floor or threshold subtraction: factor ranks determine relative allocation, while
zero current risk multipliers still receive no new-risk allocation. Product weights use a 40%
diversification cap when at least three qualified products make that cap feasible; with fewer
products the unallocatable remainder is distributed evenly and the fallback is disclosed instead of
silently shrinking the base-weight total. Existing per-client, per-sleeve, route, product and
combination caps remain authoritative. Combination risk utilization and the live 40%
product-direction cluster limit remain separate. If active effective weights exceed the separate
25% client-risk utilization budget, all positive sleeves are reduced proportionally so their
relative allocation is retained; lower-ranked qualified sleeves are not tail-cut to zero merely to
meet that portfolio budget. The copier applies a 1.5% cycle-loss budget, 3%
daily stop, per-client Demo loss budgets,
and 15% soft/25% hard margin limits. Client loss use follows the 20/50/80/100% reduction curve;
exhaustion closes only that client, pauses two hours and requires a 15-minute recovery shadow.
Twelve-hour positions cannot add risk and 24-hour positions close and pause that client.

Historical Tick delay replay is deferred from V0.1 because its cross-product validation cost is not
yet accepted. It does not participate in score or hard eligibility, and missing Tick partitions do
not reject a sleeve. The primary cost_profit_recent_coverage_carry_v4 score is 45% 30-day cost-adjusted
profit per copied trade, 25% recent seven-day cost-adjusted profit per copied trade, 15% copy-cost
coverage and 15% carry quality. Source P/L is first normalized to USD, then scaled from the 30-day average closed
execution size to the selected Demo product's actual minimum lot. Estimated cost is the product
default round-trip spread at that minimum lot plus a 25% execution reserve; rebates never enter
either P/L or cost. MT5 close counts and lots share the same exit/reversal Deal population. The
30-day cost-adjusted comprehensive P/L is the core profitability gate; seven-day performance and
cost coverage rank sleeves but do not reject them. Missing or non-finite required cost evidence,
negative equity, cashflow exhaustion and stop-out compensation remain non-compensable hard gates.
Drawdown, holding, carry and evidence-quality checks are visible ranking warnings rather than
secondary rejection gates. Carry risk combines floating-loss depth, underwater duration and
simultaneous losing-position count after the cheap profitability gates. Score 70, 10% observed
maximum floating loss, 48 hours underwater or eight losing positions is a build-time hard rejection.
Carry evidence does not remove an already selected sleeve from intraday activity or alter an open
copy; client and portfolio loss-budget controls remain authoritative while trading. Historical depth
and duration use bounded equity/path proxies in this version and do not claim Tick-level MAE precision.
Drawdown uses cashflow-adjusted equity including synchronized floating
P/L. Pre-funding zero-equity rows are ignored and the first positive funded observation establishes
capital without subtracting its own funding movement. Actual platform equity below zero remains
`negative_equity`; that code comes only from authoritative platform daily/current equity evidence,
not from an incomplete reconstructed snapshot path. Later cashflow-adjusted capital at or below zero is the separate hard gate
`cashflow_adjusted_capital_exhaustion`, so replenishment after losses is rejected without being
misreported as platform negative equity. Daily drawdown uses only the bounded 31-day daily read: the
extra day supplies a possible rollover baseline for the 30-day scoring window, and the repository
never searches farther into old account history. If no earlier funded observation exists inside
that bounded read, a newly funded account's first positive observation supplies its first baseline;
otherwise 30-day coverage remains incomplete and fails closed. Missing
position-path or intraday-equity evidence remains monitor-only rather than clean. A/TA status adds
0.02 only after hard gates. Real-time quote age, database staleness, measured signal latency and
entry/exit expiry remain execution gates; without historical break-even evidence, including a
missing sleeve delay record, a new-risk signal budget defaults to five seconds and is capped by
`holdP25 / 3`, whichever is lower.
Each source Position persists the latest opening, increase or reversal timestamp as its risk-signal
clock. Initial entries, additions and reversal open legs all recheck this clock in the central
risk-increase path and immediately before the broker request. Reductions and closes do not refresh
the clock. An expired reversal may close the prior owned Ticket but cannot open the opposite leg.

The producer targets a 500 ms source-event cadence. Every selected physical source starts in the
same platform poll wave, while the MT5 and MT4 waves start concurrently. The completed MT5 batch is
applied before waiting for MT4 snapshots, so a slow MT4 source cannot delay an already-read MT5
signal. After an accepted historical build, source connections switch from the complete-read profile
to two-second connect/read/write timeouts; an isolated timeout closes only that source connection,
preserves its cursor and reconnects on a later cycle. The producer refreshes client and sleeve risk every 10
seconds, re-ranks the monitor/reserve range every 15 minutes, performs a bounded one/four-hour
accepted-universe discovery every hour and completely rebuilds at 05:15 Beijing. A newly ranked
hard/activity/minimum-lot-qualified sleeve enters `ACTIVE` on its first qualified ranking and can
copy subsequent new source positions immediately. The old `ENTRY_SHADOW` tier remains readable for
legacy snapshots but is promoted on its next qualified ranking; no new normal entry shadow is
created. Hourly discovery
never repeats the 60-day factor query and cannot promote a historical hard-gate failure. A non-empty
hourly candidate set may publish below the monitor target. If its refreshed candidate set is empty, it records
`insufficient_qualified_accounts`, retains the last accepted pool without advancing the successful
discovery schedule, and retries after the one-minute retry floor; this condition never interrupts
the main risk or recovery-shadow state loop. Normal entry activation no longer waits for consecutive
rankings or a healthy entry-shadow window. An entry-shadow health failure caused by a transient
operational gate is retained only for compatibility with an already persisted legacy
`ENTRY_SHADOW`; the next qualified ranking promotes it directly. Loss of factor qualification,
current comprehensive product profit or activity eligibility returns the sleeve to monitor
immediately, and no new-risk order is allowed while the sleeve is not `ACTIVE`.
Initial live activation still requires the complete reconciliation/latency qualification. Once it
has passed, one ordinary later reconciliation drift does not by itself de-arm a healthy live loop;
complete route/source coverage, zero duplicate events and selected-source freshness remain required
on every cycle and still block new risk immediately when they fail.
Hourly current-position evidence uses collision-free `current` column names, preserving daily
build-time floating/hedge columns when a product currently has no open position.
Hourly monitor-only sleeves receive no provisional execution base weight. Producer status and the
dashboard define active weight as the final executable minimum of source quality, dynamic sleeve
state and client risk reduction. The dynamic product sleeve is the sole execution-state authority:
an `active` sleeve must have `effective_weight > 0`; a zero-weight sleeve is projected as
execution-suspended and cannot appear in the active copy tier. `activeCopyClients` counts only
clients with an active, positive-weight dynamic sleeve, while risk-ledger membership is reported
separately.
Restoring a versioned, fully covered accepted cache records its build day in scheduler state, so a
post-05:15 restart does not immediately repeat the same full build. The producer publishes a fresh
status snapshot before entering its first polling cycle. Each successful hourly rotation also
persists the accepted same-day pool. Restart therefore restores the latest membership instead of
rolling back to the initial daily pool; a legacy snapshot without hourly evidence keeps those
values unknown and schedules an immediate bounded discovery refresh.

The optional `-AllowDemoMinLotOverride` test switch is valid only for `ACCMGlobal-Demo` in
`StagedLive`. It may promote each eligible source Position to the product minimum lot when its
normal stress allocation is smaller, but only while whole-portfolio stress and margin permit it.
In this explicit Demo mode the product-direction cluster cap is disabled, so multiple independent
customers may hold the same product and direction until the separate whole-portfolio stress budget
is exhausted. Build-time feasibility and execution use the same rule. It does not bypass quote,
spread, database, Ticket-ownership,
daily-stop, equity-floor or margin hard gates and is never implicit.
This is the only all-supported-product waiver of the ordinary same-direction limit: no minimum-lot
or same-direction exception is enabled by product name, a normal profile or an omitted switch.
For an active client under that exact Demo-only switch, the client loss budget is floored at the
existing 20% per-client share of the 1.5% cycle budget. This keeps the risk allowance consistent
with the indivisible 0.01-lot test exposure. Clients with zero activity weight receive no floor, and
all default, non-Demo and non-`StagedLive` execution keeps the weight-proportional budget.
Once a source Position owns that minimum lot, normal reconciliation preserves the same Ticket while
the source, weight and gates remain eligible; an eligible same-direction sibling receives its own
Ticket while whole-portfolio stress and margin still permit another minimum lot.
More than eight Demo open requests in a rolling 60-second window triggers an execution hard stop and
strategy flatten before another opening request is sent.

The `-DemoFastActivation` switch remains accepted for launcher compatibility and is reported in
status, but it no longer controls ordinary entry activation. For a fresh sleeve in the active zone
that is hard-eligible, activity-eligible and minimum-lot feasible, the first ranking directly sets
`ACTIVE` and its effective weight to the current `live_base_weight` in every mode. It does not
authorize trading or bypass operational/risk gates. Existing loss-recovery shadows remain
independent and still require their recovery health window.

## UI and behavior

The page refreshes the dashboard snapshot every second. The header operator clock advances from the
browser clock independently of dashboard requests, so a slow or failed snapshot request cannot freeze
the visible seconds. The page header and pinned Demo account identity line render that same clock value;
every wall-clock timestamp is parsed as an instant and formatted explicitly in `Asia/Shanghai`, including
Demo positions and Deals, source events, scheduling, current-copy openings and chart axes. Holding age,
shadow countdown and both visible clocks derive from the single reactive runtime clock. Source freshness
and stale-state labels remain tied to Producer evidence. It uses
the K_desk dark operations theme, Chinese labels and responsive desktop/mobile layouts. Every visible account label, event, mapping and
filter uses the actual trading Login; the private `C001` alias remains an internal mapping and redirect
identifier only. Platform/server context remains a secondary line.
The displayed operational clock is normalized to Beijing time. Current Demo account state, Ticket
ownership, strategy P/L, source/risk events and execution gates are shown in separate bounded
panels so an operator can distinguish live account facts from historical event rows.
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
The scheduling event stream is an entry-signal view: it shows source opening events only. Source-only
reductions and closes remain in the API/event ledger and the position/history panels, but are omitted
from this stream so an exit from a position that was never copied cannot look like a missed Demo
order. Each visible source event includes a sanitized execution outcome such as active, monitor,
signal_expired or risk_rejected plus a bounded event-time `reasonCode`. New Producer events persist
the exact accepted code (for example `below_minimum_risk_lot`, `signal_expired_no_copy` or a bounded
`execution_gate_blocked:*` code) separately from the legacy composite reason. The dashboard never
returns that raw reason or any unknown free text. Event placement uses its event-time decision and phase rather than
the account-product sleeve's current tier. A monitor event recorded while the pool is rebuilding,
rebuild has failed, shadow reconciliation is active or AutoTrading is unavailable is shown under
the corresponding suspended/recovery tier with that concrete phase and a zero target, rather than
the generic combined point-spread/latency/external-position wording. Event-time phase remains
authoritative when a compatible older 8777 projection does not yet include the additive decision
field. A legacy event without `reasonCode` is labelled explicitly as missing historical detail; the
UI must not infer point spread, delay or external-position failure without event-time evidence.
The `当前跟单` table contains only source Positions with actual owned Demo child Tickets. It shows
the real source Login and detail link, server/platform, product/direction, source Position and lots,
Demo Ticket and lots, both opening timestamps/prices, entry delay, holding age, exact current source
floating P/L and Demo comment-attributed realized plus floating P/L. Legacy snapshots without exact
per-position evidence display an unavailable state rather than allocating account totals.
Status and equity-timeline rows include the pinned Demo Login. A Producer schema upgrade rotates a
legacy timeline without this identity column into a timestamped archive before starting a clean
current curve, so account-crossed equity samples cannot remain mixed into the displayed series.
Detailed execution-gate sub-reasons in the current-copy view are localized for operators while the
underlying bounded reason codes remain additive and compatible.

The `客户池层级与影子准入` panel is an interactive tabbed read view. Its tabs are `活动跟单池`,
`监控池`, `候补池`, `恢复观察`, `执行暂停` and `硬门拒绝`; the obsolete `入场观察` tab is not
shown for new runs. Legacy `ENTRY_SHADOW` rows are normalized to `监控池` in the presentation
layer. Selecting a tab immediately replaces the panel body with that tier's
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
plus additive `clientRisks`, `copyPositions`, `ticketMappings`, `currentCopies` and `exposures`. It is additive
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
exact configured eleven-route and nine-source sets and every source completed successfully.
Every MT4 and MT5 factor-history load is limited to one bounded 31-day daily-equity range. It never
performs a second pre-window query or progressively searches older history. Risk history, holding
statistics and factor history each run across at most four physical sources concurrently, while
each physical source remains one serial task per stage. Results merge in stable physical-source
order; any source failure rejects the complete build.
Coverage records bounded stage timings for route discovery, feature scan, current state, risk,
holding, factor history/scoring and total build time without exposing SQL or account identity.
The v10 producer may migrate a same-trading-day v6, v7, v8 or v9 cache without repeating the 30-day
database build only when the private universe is present and metadata plus coverage prove the exact
complete eleven-route/nine-source set and complete carry-risk evidence. A legacy universe without
carry-risk evidence forces a full rebuild. Migration preserves all existing hard-gate failures,
applies the current seven-day/30-day after-cost evidence across the full cached universe,
regenerates selection and positive-score weights, and stamps v10/v4 metadata. The next 05:15 schedule
still performs a complete read-only database rebuild under the v10 model. A migration rebases sleeve
weights but remains a same-day restart: persisted source-position to Demo-Ticket ownership is
restored and validated rather than cleared.
MT5 polling intentionally reads non-trading ledger actions so each physical cursor can advance past
them; those actions never change virtual positions, intraday trading P/L, dynamic weights or source
signals. All MT5 Deals returned in one polling cycle are first applied to the source ledger and then
coalesced by account, product and Position to one terminal transition. An opening and complete close
already present in the same batch advances cursor/P&L and emits `batch_terminal_flat` evidence but
never opens a Demo Ticket; a batch with residual or reversed exposure executes only its terminal
state once. Terminal transitions are durably journaled before broker execution, pure reductions
run before new risk, one Position failure does not discard its siblings, and incomplete entries are
retried during the same process. On restart only pending reductions/closes resume; pending opens are
cancelled to monitor-only and a pending reversal resumes only its old-direction close, preserving the
no-chase rule. Invalid pending state fails startup instead of being silently discarded. An expired residual source position is reported as
`signal_expired_no_copy`, not as source-flat. Reconciliation rechecks the entry deadline whenever an
eligible source Position has no Demo child, so a prior rejection cannot be chased after its signal
budget expires. Existing copied exposure still follows reductions and closes. MT4 remains
snapshot-authoritative. The producer persists effective weights by composite
account key; the dashboard prefers that current mapping over historical event rows and clamps any
legacy fallback to zero through the accepted pool's base weight.
Replicated MT4 `OPEN_TIME` is normalized by physical source before signal-age calculation: AC
`mt4_export_syc` uses UTC, while DBG CN Live1/Live2 use MT4 server time UTC+3. DBG VN Live3 remains
fully routed and provisionally follows UTC+3 until a fresh runtime event reconfirms it. This prevents
a timely snapshot position from appearing hours early or late.
Daily holding-period reconstruction keeps the complete 20-day evidence requirement while avoiding
one unbounded MT5 aggregate. MT5 reads start as five-day Login-batch windows; a slow window splits
Logins first and then time down to six hours. Position openings and closes are merged across window
boundaries before percentiles are calculated, and no sample is silently skipped. MT4 retains its
fast aggregate first and uses the same bounded fallback after a timeout.
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
The append-only `events_public.csv`, `orders_public.csv` and `status_timeline_public.csv` files each
require an exact producer header and row width. The single-source Producer retains its own fixed
columns; the multi-source Producer uses fixed event and order supersets, normalizes unavailable
source-specific values to empty cells and rejects unexpected fields. At producer startup and before
every append, a missing or matching file is retained; a non-empty file with any different column
order, name, header count or row count is atomically renamed in place to
`*.schema-mismatch-<UTC timestamp>.csv` and a new public file starts with the current header.
Archived rows remain byte-preserved for investigation and are intentionally not mixed into the
current dashboard feed.

The page does not query MySQL or MT terminals and does not start, stop or modify the copier. It has
no order, balance, permission or MT Manager write action.

## Business rules and units

K_desk does not recompute customer selection, base weights, open-risk penalties, client loss-budget
reductions or copied lots. It displays the latest values produced by the governed copier. Money is
USD, positions are standard lots, product spread is ask minus bid and database latency is seconds.
For an executable cross-currency Demo product, the Producer converts one-lot bid/ask spread cost
through the selected Demo terminal/account currency calculation; it must not treat
`(ask - bid) * contract_size` as USD when the quote currency differs. The pool excludes rebates and
uses money-only Cent normalization. Opposing customers are never presented as if one customer's
event closed another customer's Ticket.

## Loading, empty and failure behavior

The page has explicit loading, unavailable, request-failure and empty-filter states. A status file
older than five seconds is marked stale. Missing or malformed optional CSV/JSON files degrade to
empty sections; they never expose raw parse exceptions or synthesize account identities.

Runtime heartbeat recovery is best effort. A terminal identity/IPC failure or a Demo ledger refresh
failure no longer prevents `status.json` from advancing: the last verified account fields are kept,
the current phase and error are published, and the failed ledger refresh is retried on its normal
interval. If AutoTrading is disabled after live activation, the Producer moves to
`armed_waiting_autotrading`, stops broker reconciliation calls that could add risk, and continues
database polling, persistence and status publication until terminal permission is restored.

The Demo ledger is Position-oriented. Current MT5 Positions appear only in the current-position
table. The history table groups all closing Deals for each completed Position into one row, sums its
closed lots and final realized P/L, and uses the last close time and price. Opening Deals and
incomplete/orphan evidence are not repeated in history.

The real-time event stream is colocated with the scheduling cadence panel. Events resolve their
pool tier through the same account-product sleeve projection as the adjacent customer-tier table.
Both panels share one tier selection, so activity, monitor, reserve, recovery, suspended and
hard-rejected views always stay synchronized.

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
The minimum-lot budget regression also requires a tiny-weight active client to receive the 20%
cycle-budget floor only under the explicit Demo switch, proves that a 0.69 USD copied loss does not
exhaust that floor and preserves weight-proportional budgets elsewhere.
Producer and dashboard tests also cover direct first-ranking activation for fresh eligible sleeves,
legacy entry-shadow promotion, retained recovery-shadow safety and effective status projection.
Producer CSV tests also cover schema-mismatch rotation, byte-preserved archival, multi-source
MT5/MT4 event and independent/flatten order superset alignment, and a clean current header/data
file, preventing DictReader field shifts after a producer schema upgrade.
Open-path regressions cover MT4 partial-close residual Ticket rekeying without a second Demo open or
signal-expiry false positive; an already-live service retaining readiness through one routine
reconciliation drift while current coverage, duplicate-event and source-freshness gates continue to
fail closed; a missing delay row using the five-second runtime budget; and cross-currency spread
conversion through the selected Demo account rather than a raw contract-size multiplication.
MT5 batch tests cover a complete open/close round trip with no execution, a multi-Deal residual open
with one execution, and a close-plus-opposite-open reversal whose latency starts at the opposite
entry rather than the earlier close. They also require risk reductions before additions, durable
pending serialization, restart cancellation of new risk, restart retention of risk release and
continuation of independent sibling transitions after one execution failure.
Restart ownership regressions require an open persisted source Position without a real Demo child
to remain monitor-only even in live reconciliation, retain a uniquely recoverable real Ticket, and
remove the monitor-only mapping after its source close without sending a Demo order.
Holding-statistics regressions force MT5 Login and time-window subdivision, reconstruct a Position
whose opening and close fall in adjacent windows, and require its exact duration and sample count.
Governed Full verification imports the dashboard API from the active worktree's `src` directory,
so another checkout's editable installation cannot satisfy these assertions with stale code.

## Manual risk controls

The dashboard exposes the current equity-floor, daily-loss, cycle-loss and automatic-entry
switches. The `PUT /api/copy-pool/controls` endpoint accepts only the fixed boolean schema and
only loopback clients; updates are atomically written to the producer output directory and
appended to an audit JSONL file. Disabling a gate does not close existing positions or bypass
execution reconciliation. The separate resume action clears the persisted daily hard-stop only
once and starts a recovery shadow; it never jumps directly to live execution. Missing or malformed
control files fail closed to all protections enabled.

## Compatibility and deprecation

The feature is additive. Existing `/`, `/account/{login}`, `8777/8766` ports and account APIs are
unchanged. Removing the dashboard requires removing its navigation entry and routes together; local
snapshot files remain independently usable by the copier.
