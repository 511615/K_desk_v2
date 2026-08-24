# Data ownership and server routing

## Local authority

Production state is under `runtime/prod`; development and tests use `runtime/dev` and
`runtime/test`. SQLite WAL, foreign keys and busy timeout are enabled. Core local entities are
accounts, account history, quick actions, login-IP observations, job runs, job events and Alembic
revision state. Excel files are import/export snapshots only.
The account relationship network has no independent authoritative store. It recursively composes
routed read-only account-risk, same-server MT5 current-LastIP, Copy, EA, CRM-rebate, exact CRM
account-owner/direct-IB mappings and selected high-priority principal-order synchronisation/opposite-lock
payloads, and never
writes an inferred cross-account relationship. A top-IB cohort is a count-only aggregate for the
selected seed, not a source of unbounded account edges.
Direct-IB anomaly discovery reads `rebate_task_detail` by `rebate_ib_id` and selected time range,
groups by route/login, joins only routed MT4/MT5 status views for elevated status candidates, and
batch-reads closed market P/L only for the bounded candidate set. USD/USC normalization is applied
consistently to rebate and trading P/L. The source returns counts and evidence only; it does not alter
CRM, rebate or trading data.
Historical funds backtrace has no independent store. For one selected account route it reads the
complete platform ledger/trade facts and daily account anchors through LegacyBridge. MT4 sources are
`mt4_trades` plus `mt4_daily`; MT5 sources are the indexed `mt5_deals` and current `mt5_accounts`.
The MT5 `mt5_daily_view` is not queried online because it is not indexed by Login and an account
filter can become a full-view scan. Current balance/Credit calibrates the replay and the API marks
historical equity snapshots unavailable. It returns raw coverage counts and does not read a second logical
route to merge a shared Login. The data is read-only and is not copied into SQLite or Excel.
Database K-line generation may package this same selected-route replay into its local output artifact.
When the user explicitly includes the replay, the Worker first saves the complete account/platform/server
replay under `runtime/<profile>/cache/kline_timeline`; later charts reuse that local cache and do not
read the remote funds source. An explicit chart refresh is the only normal cache-refresh path. The
timeline input package uses no new remote source and remains inside the configured runtime artifact
directory.
The separate `ACC-REL-002` Kuzu demo reads an operator-created local file at
`KDESK_KUZU_DEMO_DB` (default `runtime/<profile>/relationship_graph_demo.kuzu`). It is a
non-authoritative evidence projection for one bounded demo subject: it does not refresh from, write
to or replace any remote source or local authority. Missing data remains missing rather than
triggering an on-demand remote multi-hop scan.
The account-detail `ACC-REL-001` relationship entry uses a different request-scoped Kuzu projection:
it reads governed account/IP/EA/Copy/rebate payloads for each score-eligible account, serializes the
aggregated response to a temporary local Kuzu graph once, reads it and deletes it before response.
MT5 same-IP peers are same-server `LastIP` matches only. The account endpoint starts or reuses one
bounded local background expansion and returns an in-progress read-only snapshot for page polling;
it continues through score-eligible accounts until the threshold or the 2,000-node/10,000-score-
expansion safety limits are reached. Each source has a six-second wait budget and the LastIP/CID follow-up
has a separately clamped three-second client/database timeout. Known members of one current-LastIP or
current-CID cohort skip redundant follow-up queries. Each legacy evidence family has one local shared execution
lane; a source that exceeds its per-account wait budget remains bounded instead of accumulating
threads during continued expansion. The temporary Kuzu write is limited
to 400 selected entities and 1,200 selected relationships and runs in an isolated local child process
with a four-second hard deadline; the parent falls back to pure in-process scoring if the child is busy,
fails or times out. `include_toxic=true` enables the existing all-platform five-second open-and-close
sync matcher for up to two high-score accounts. It never writes AC, DBG, MT4, MT5, CRM or authoritative
K_desk SQLite data.
`ACC-REL-003` separately reads an operator-created direct-account evidence file at
`KDESK_KUZU_RISK_DB` (default `runtime/<profile>/relationship_risk_graph.kuzu`). It is likewise a
non-authoritative read-only projection. Runtime scoring reads only local Kuzu `Entity` and
`Evidence` rows; missing data never falls back to AC/DBG/MySQL/MT/CRM scanning. The projection must
exclude authentication fields and unnecessary contact/KYC fields.

The dynamic copy-pool dashboard reads the copier's local snapshot directory. Public inputs are
`status.json`, `pool_public.csv`, `events_public.csv`, `orders_public.csv` and
`status_timeline_public.csv`. `runtime_state_private.json` is used only to derive account-product
virtual positions, dynamic sleeve weights, client Demo loss budgets and independent source Position
to Demo Ticket ownership. `client_routes_private.json` maps `C001` aliases to composite
account key, trading Login, logical/physical source, platform/server identity and the existing
account-detail route. `source_coverage.json` records the accepted build funnel and runtime status
overlays per-source freshness and errors. The localhost dashboard JSON and UI intentionally expose
only those identity fields; private structures, credentials and contact data never enter responses
or logs. The API sanitizes independent state into `clientRisks`, `copyPositions`, `ticketMappings`
and per-product `exposures`; internal composite keys and order comments do not enter those projections.
`demo_account_public.json` retains account-level balance/equity/margin facts but publishes only
open positions and trading Deals owned by copy-model Magic `26072801` and its approved Comment
namespace. The 8777 adapter rejects any legacy row without explicit `strategy_owned=true`, so manual
orders and other EAs cannot enter the model position count, floating P/L or Position history.
Producer status publishes `external_position_count` as observation-only evidence while keeping
`external_position_conflict=false`; the 8777 projection exposes this as `externalPositionCount`.
Pending-order conflict remains independently projected and may still block new model risk.
The public pool retains delay compatibility columns but V0.1 marks them
`historical_delay_enabled=false` and `delay_factor_status=deferred_v0_1`; the producer does not read
historical Tick partitions during its complete build. Cashflow-adjusted drawdown and holding-quality
columns remain authoritative. K_desk maps
the status `dynamic_sleeves` list only after matching each private sleeve key to a current
`client_routes_private.json` alias plus public product row, then exposes the alias/product state and
the fixed scheduler timestamps. Unmapped state, raw private keys and free-form private gate text are
dropped.
The public pool also carries the current factor-model identifier, normalized seven/30-day copied P/L,
estimated seven/30-day copy cost, cost-adjusted P/L, cost coverage and four percentile factor
scores. These fields are derived from the complete private universe and expose no credentials,
contacts or private route structures. Hourly score, one/four-hour P/L, current comprehensive-profit eligibility and discovery coverage are
also public snapshot fields. K_desk does not query them from MySQL. The producer obtains them from
the accepted `pool_universe_private.csv` plus bounded current-session reads; the daily historical
factor evidence remains immutable until the next complete build.
Account eligibility evidence is computed before product selection. Lifetime closed trading net uses
the current platform `Balance + Credit` less cumulative Balance, Credit, Charge, Correction and Bonus
ledger movements, so funding, withdrawals and balance-posted rebates are removed without a remote write. Current all-product floating P/L
is added to lifetime and rolling-30-day trading net. MT5 complete-sample counts use distinct closed
Position IDs with no authoritative open residual; MT4 counts closed market Tickets. The 30-day sample
must contain at least five such Positions/Tickets and three distinct close dates. A v10 or older cache
without these fields is invalid for v11 and triggers a full read-only rebuild.
The private `account_profitability_cache_private.json` is a v1 per-physical-source accumulator of
Login, cumulative raw Balance/Credit-class ledger net and Deal/Ticket highwater. It contains no CRM
identity, contact, credential or Ticket ownership data. A known Login is refreshed from the highwater
delta; a missing candidate is backfilled through the current highwater. Rolling sample counts and
active-day sets come from the same non-overlapping 30-day feature shards already used for product P/L.
The recovery endpoint is the only copy-pool monitor path permitted to write local runtime files:
it atomically creates or reuses `runtime_recovery_request.json` and reads the bounded companion
`runtime_recovery_status.json`. The request contains only the fixed action, revision and request
time; it has no process command, database configuration, source cursor or Ticket mapping. The
existing Producer is the only consumer. It resets read-only physical-source connections in-process
while retaining source cursors and source-Position-to-Demo-Ticket ownership; 8777 does not open
those connections or operate the Producer process.
The additive carry-risk evidence contains its 0-100 score, 0-1 quality score, hard-gate state,
bounded reason codes, maximum floating-loss ratio, maximum underwater seconds and maximum losing
position count. Current MT4/MT5 product-position aggregates count losing positions directly in the
existing grouped read. Historical depth and duration reuse bounded equity/position-path evidence;
no Tick partition or unbounded pre-window query is added.

The producer treats each append-only public CSV header as a versioned local contract. Before startup
counter/latency restoration and before every append, `events_public.csv`, `orders_public.csv` and
`status_timeline_public.csv` must exactly match the current ordered producer columns and every row
must have that width. The multi-source runtime declares fixed event/order supersets before its
base-service initialization, so MT5 and MT4 events plus independent and product-level orders append
to one normalized layout; absent allowed columns are empty and unknown fields fail the Producer.
A current event row ends with the bounded `reason_code` column. Only the published allowlist is
accepted by the dashboard projection; unknown values become empty and the legacy composite `reason`
is never returned. Older headers without `reason_code` rotate through the same schema-mismatch path,
while already archived events remain honest legacy evidence without a reconstructed sub-reason.
`signal_age_seconds` is the source trade/open observation age used by the expiry decision;
`query_latency_seconds` is only the physical database query duration. The legacy
`db_latency_seconds` remains an alias of signal age for compatibility and must never be populated
with MT4 query duration.
A mismatch is renamed atomically in the same snapshot directory as a timestamped
`schema-mismatch` archive, then the current file is written with a new header. The archive is
historical evidence only; it is not merged into the dashboard's live reader, so old rows cannot
shift current DictReader fields.

The copy-pool producer treats `(CRM schema, mt_server_code, Login)` as account identity. Shared
physical sources are scanned once and routed through CRM evidence; a Login mapping to more than one
logical route is excluded rather than guessed. Source cursors and health are independent. MT5 uses
execution increments plus current-position reconciliation; MT4 uses authoritative current-open-
position snapshots because its replicated trade row is mutable. MT5 non-trading ledger actions are
retained in the incremental read only to advance the physical-source cursor. They do not alter
virtual positions, trading P/L, weights or signals. Accepted pool snapshots require the exact
configured route/source key sets and a successful health row for every physical source. Runtime
state persists effective weights by composite account-product key so a same-alias historical event
from a prior pool build cannot overwrite the current pool projection. The dashboard multiplies a
  sleeve dynamic weight by the client-specific Demo loss-budget factor before clamping it through the
  sleeve base weight.

At runtime every selected physical source receives its own worker in the MT5 or MT4 poll wave; the
five MT5 sources therefore cannot leave one source queued behind a four-worker ceiling. The MT5 and
MT4 waves start together, and completed MT5 Deals are applied before the producer waits for the MT4
snapshot wave. Live connections use two-second connect, read and write timeouts. A timeout closes
only that physical source connection, preserves its cursor and reconnects on a later cycle. Historical
pool construction retains the longer complete-read timeout and switches to the bounded live profile
only after an accepted pool has loaded. A complete pool build gives a source at most two additional
connection attempts, and only for classified MySQL connection loss or timeout; query, schema,
data-quality and eligibility errors fail without retry. While retrying or after a rebuild failure,
the Producer advances the heartbeat with `runtime_snapshot_stale=true` and `data_fresh=false`; a
recent heartbeat is not fresh pool evidence.

Raw MT4 `OPEN_TIME` is physical-server time, not MySQL session time. AC `mt4_export_syc` uses UTC;
DBG `crm_cn_mt4_live1` and `crm_cn_mt4_live2` use UTC+3. DBG `crm_vn_mt4_live3` remains in the full
route set and provisionally uses UTC+3 until a fresh selected-position event reconfirms the clock.
Current-position routing converts each source to aware UTC before comparing source age with the
signal budget. The MySQL session's `+08:00` rendering must not be attached to the raw value.

Open-position risk reads all market positions for each candidate, not only XAUUSD. MT5 uses current
`mt5_positions` plus the current account `Profit`, `Equity` and `Margin`; MT4 uses `CMD IN (0,1)`
rows with the 1970 close sentinel plus current user equity/margin. The producer persists open count,
all-symbol gross lots, XAUUSD gross/net lots, oldest-open seconds, floating P/L, floating-loss ratio,
margin/equity and hedge ratio by composite identity. Product aggregates also persist the count of
positions whose current profit, commission and swap sum is negative. Confirmed Cent/USC scales only money fields by
0.01; position counts, lots and ages remain unchanged.

The producer persists independent execution under `independent_copy`. A source key contains the
composite account identity, normalized product and source Position/Ticket. Each child stores the Demo
Ticket, side, lots, opening time and price required for exact ownership recovery. Startup compares
both Ticket sets exactly: an unowned strategy Ticket or missing persisted Ticket hard-stops. Source
positions present at startup populate `legacy_source_positions` and remain monitor-only until close.
For an already mapped source Position, restart may lower the approved source quantity when an
offline reduction/close is observed, but it never raises or reverses that approved quantity without
a new timely source event. Hourly entrants use the same old-position boundary. Retiring clients with
same-day mapping/P&L ownership remain internally subscribed until the daily ledger reset.
After exact Ticket recovery, a restored open source Position with no actual child Ticket is marked
`restart_monitor_only` and made copy-ineligible. That persisted marker cannot be cleared by ordinary
reconciliation; the mapping is deleted only when the source closes. A uniquely recovered actual
Ticket is not marked and remains under exact ownership management.
For a live eligible source Position without a Demo child, every reconciliation retry also compares
the original source-open/first-signal time with the sleeve entry budget. Once expired, its target is
zero for that Position with reason `signal_expired_no_copy`; this does not block reductions or closes
of an existing owned child Ticket.
Every Position also persists `risk_signal_at`, updated only by an opening, same-direction increase
or reversal. The executor checks this timestamp again in the central risk-increase path and once
more immediately before the broker open call. This applies to first entries, additions and the new
leg of reversals; expiration may close the prior reversal leg but can never open the opposite leg.
Missing or malformed risk-signal time fails closed for new risk.
Current source-position snapshots retain open/current price and normalized floating P/L. Demo
realized and floating P/L are persisted by the deterministic source-Position comment. These values
feed the sanitized `currentCopies` projection; account-level P/L is not divided among Positions.
MT5 execution increments and MT4 authoritative snapshots use the same position-difference contract,
so one account cannot modify another account's children.
An MT4 partial close can replace the residual open Ticket. The read-only snapshot retains COMMENT
only to recognize the proven `from #<prior Ticket>` relationship. When the replacement is a smaller
same-direction residual for the same composite account/product, the private ownership mapping is
rekeyed atomically and keeps its Demo-child ownership and original risk-signal time. COMMENT and the
parent Ticket remain private; an absent or invalid relationship never triggers guessed migration.
MT5 polling applies every returned Deal to cursor, position and P&L state before invoking execution.
The resulting changes are grouped by composite account, Position and normalized product. A batch
whose pre-batch and post-batch quantities are both zero is terminally flat and must not create a Demo
Ticket even when the batch contains a complete opening and close. A non-flat batch executes one
coalesced terminal transition; an opposite entry supplies reversal signal time. Before broker
execution, the Producer persists the source ledger, cursors and pending terminal transitions in the
private state. Successful transitions are removed individually. Within one process, failed items
remain pending and coalesce with later source events. On restart, only reductions/closes remain
executable; opens are cancelled and reversals retain only the old-direction close. Invalid journal
records fail startup so a possible risk-release instruction is never silently lost.
The daily 30-day holding-statistics read is also complete-data only. MT5 starts with five-day
Login-batch windows instead of waiting for one 20-day aggregate to time out. A slow window splits
Logins and then time recursively down to six hours; opening/closing timestamps are merged by
Login/Position/product before holding duration is derived. MT4 first uses its indexed aggregate and
falls back to the bounded path after a timeout. Exhausting the minimum window fails the build.
Closed mappings remain through the current trading day so comment-attributed realized Demo P/L stays
assigned to its client loss budget. They are pruned only after the trading day changes and only when
no Demo child Ticket or source exposure remains. Emergency flatten acceptance is based on the actual
strategy Ticket set, never on a possibly zero net position.

Factor-history daily reads are strictly bounded to the 61 days ending at the build cutoff. The
repository issues no separate pre-window query and never progressively searches older account
history. The extra bounded day may establish the 30-day funded-capital and server-day boundary; if
it cannot, the first funded observation inside the range is used only for a new account, otherwise
coverage fails closed. Deal, trade and snapshot reads remain bounded to the same factor window.
Risk history, holding statistics and factor history use a global concurrency limit of four within
each stage and one serial task per physical source. Results merge in stable source order.

The product catalog maps only proven source/Demo equivalents. Suffix and Roll aliases are normalized,
including `UT100 -> NAS100Roll` and `USOIL -> USOILRoll`; unproven dated futures are excluded rather
than guessed. Source lots convert by source contract size divided by Demo contract size. Cent/USC
never scales lots.

## Remote read-only routing

| Logical server | CRM route | Trading schema | Compatibility alias |
| --- | --- | --- | --- |
| AC GB MT5 | `int_sass_crm_ac`, code 1 | `int_sass_crm_ac_mt5_live_new` | - |
| AC CN MT5 | `sass_crm_ac`, code 1 | `sass_crm_ac_mt5_live` | - |
| AC CN MT5 live3 | `sass_crm_ac`, code 3 | `sass_crm_ac_mt5_live3` | `AC CN MT5 Live3` |
| AC CN MT4 | `sass_crm_ac`, code 2 | `mt4_export_syc` | `AC MT4` |
| AC GB MT4 | `int_sass_crm_ac`, code 2 | `mt4_export_syc` | `AC MT4` resolved by account route |
| DBG CN MT5 | `crm_cn`, code 4 | `mt5_export_new` | `DBG MT5` |
| DBG GB MT5 | `crm_vn`, code 2 | `mt5_export_new` | `DBG MT5` resolved by account route |
| DBG MT5 Live2 | `crm_vn`, code 5 | `crm_vn_mt5_live2` | `DBG MT5` / `DBG GB MT5 Live2` resolved by account route |
| DBG MT4 CN1 | `crm_cn`, code 1 | `crm_cn_mt4_live1` | `DBG CN MT4 Live1` / RiskDash live1 |
| DBG MT4 CN2 | `crm_cn`, code 3 | `crm_cn_mt4_live2` | `DBG CN MT4 Live2` / RiskDash live2 |
| DBG MT4 VN3 | `crm_vn`, code 1 | `crm_vn_mt4_live3` | `DBG VN MT4 Live3` / RiskDash live3 |

The same numeric login can exist on multiple logical servers. CRM schema and server code are part
of account identity. A shared physical trading schema must never be used to infer the CRM route.
An exact CRM route confirmation remains authoritative for source identification when the new account
has no trade/deal rows yet. Interactive lookup and detail responses retain the confirmed logical
platform/server and account metadata with an explicit zero-order status; lack of orders is not an
unknown-source condition and must not trigger cross-source guessing.
When a newly created account exists in an indexed physical `mt4_users_view` or `mt5_users_view` but
its CRM mapping has not arrived, interactive account reads may use a fail-closed
`unique_trade_user_fallback`. It is allowed only for the canonical logical route of that physical
source and only after every other independent source on the same database host and platform proves
that it does not contain the Login. A shared physical schema's other logical routes, any duplicate
independent-source Login, missing users view, or users-view query failure remains unavailable. The
lookup response exposes this as `routeValidation`; it is not CRM-route confirmation.
Same-name discovery groups by CRM `user_id` across server codes within that CRM schema. The public
graph presents this only as `同名账户` and does not expose the internal table or `user_id`. Every
returned account retains its own server code and is queried through the corresponding logical
trading source; the selected account's source must never be reused for a related account.

Hierarchy net-deposit and product analysis follows the same central registry. It derives CRM
environments and allowed server codes from `crm_routes`/`account_route`, resolves every hierarchy
account by exact `(CRM schema, mt_server_code)`, and de-duplicates product reads by physical source.
It must not maintain a separate fixed server-code or source-name allowlist.

## Units and time

MT4 raw volume is converted with `VOLUME / 100`; MT5 uses `Volume / 10000` or
`VolumeExt / 100000000`. Rebate-churning then multiplies confirmed Cent-account lots by `0.01` to
show and score standard-lot-equivalent exposure. Confirmed USC money values are also multiplied by
`0.01` for USD display; prices, identifiers and timestamps are never scaled. Synchronous MT5 currency resolution uses the indexed
`mt5_users_view.Group` path: delimiter-bounded `Cent`/`USC` means USC, an explicit currency segment
is retained and otherwise the configured source default is USD. The unindexed `mt5_daily_view` is
not used by interactive requests. Database sessions use their server time; offsets are applied only
when an evidence-backed feature explicitly documents them.
CRM `rebate_task_detail.rebate_amount` is always read and aggregated unchanged. Its `usd_or_usc`
column remains metadata and does not participate in rebate amount conversion; the `0.01` scale above
applies only to platform money and standard-lot-equivalent exposure.
MT4 closed-order reads require `CLOSE_TIME > OPEN_TIME`; the `1970-01-01 00:00:00` value is the
open-position sentinel and is never treated as a close event or chart date.
Interactive MT4 detail analytics read the complete closed-order history; they must not apply the
legacy 50,000-row prefix. Rows, costs and derived metrics are cached together by login, platform
and logical server so detail, risk, lookup-finance and automation reuse one consistent read model.
The order-list API is separate: it executes an exact count and a newest-first ticket page in MySQL,
then normalizes only those tickets. Platform and server filters are mandatory routing inputs for
this pagination path.

EA discovery uses the selected route to identify authoritative opening-Comment seeds, then queries
every configured MT4 and MT5 physical source by exact full Comment. Exact Comment membership is
cross-platform and cross-server; ExpertID/MAGIC is displayed as per-order evidence and never gates
membership. MT5 candidates come only from opening deals and use the Comment index; MT4 candidates
use the bounded observed interval because COMMENT and MAGIC are not independently indexed. Pure
contact Comments are valid exact user-investigation keys; platform/system events, balance operations
and routing formats retain their explicit exclusions/classifications.

Only an error-free exact stage with fewer than two valid routed accounts may start structural
fallback. Fallback queries the classifier's stable prefix, validates the complete normalized template
in memory and then reconstructs exact MT5 Positions or MT4 tickets. Route templates do not require a
shared ExpertID because their numeric identifier commonly represents the source order or channel;
dynamic EA templates retain ExpertID/MAGIC evidence. AC `@number@` prefixes retain bounded two-digit
shards and recursively add one numeric prefix digit when a shard exceeds its row ceiling. Derived
`(Login, PositionID)` matches are cached briefly; execution rows and profits are read
fresh with database/server provenance and match clues.

Observed non-exact formats are stored in ignored local SQLite
`ACCOUNT_REGISTRY_DATA_DIR/ea_comment_patterns.sqlite`, never in remote trading or CRM databases.
The table stores template, stable prefix, category, evidence, source, rule version, first/last seen,
observation count and a sample. Automatic observations cannot override built-in system exclusions;
rows explicitly marked `source=manual` take priority over learned classifications.

When the selected MT5 source has no usable opening-Comment seed, no-comment ExpertID sequence
discovery remains on that exact logical source. It reads a bounded opening-time window by complete
ExpertID, validates candidate logins through the source CRM route, then reads each candidate's
bounded opening rows to enforce bilateral coverage. It does not scan by numeric prefix, does not
cross logical servers and does not write to MT/CRM or the learned-Comment registry.

Platform rebate discovery uses `rebate_task_detail.create_time` for candidate windows. Recipient
IBs are discovered in daily shards with one six-hour fallback, then read in IB batches without a
Top-N cutoff. Deep evidence follows exact MT5 deals to positions and exact MT4 tickets, preserving
delayed-rebate links even when a trade close is outside the rebate-entry window.
Account and IB rebate-detail drill-downs constrain MT5 reads by login and time but do not force a
physical index name shared across AC and DBG; each schema's optimizer selects from its verified
local index set.
Account-audit rebate detail likewise does not force the single-column `idx_mtLogin`: the optimizer
may use the available `(trade_mt_login, create_time)` index. Only scoring fields leave MySQL; rows
are grouped per batch in application memory by recipient IB, account and deal/ticket, with the raw
source-row count retained separately. This avoids large full-history MySQL temporary grouping.
For account audits, recipient-IB evidence and per-account hierarchy totals are separate queries.
Recipient rows retain symbol, volume and open/close timestamps for a high-recall in-memory candidate
screen. Exact MT5 position or MT4 ticket reconstruction and cashflow reads are limited to candidates
and the searched account; candidates without an exact identifier use the selected period fallback.
Non-target candidates above 1,000 exact rebate orders derive de-duplicated structure metrics from
rebate metadata and do not read full MT profit or cashflow history. Unknown profit is not treated as
zero when scoring rebate economics.
The screen controls read breadth only: complete-tree rebate amounts and source detail counts remain
unfiltered and candidate membership contributes no score. Historical-account discovery uses the
requested period with a five-year upper bound. Per-account recipient summaries are built once for
all scored IB levels, while hierarchy totals run concurrently with independent MT evidence reads.
For the account audit, omitting both dates means the environment's complete verified trading-data
history. Every routed account in the displayed CRM tree receives an indexed full-period aggregate
for closed order count, standard-lot-equivalent volume, trading P/L and active days. Aggregates use
ten-account source batches with connection reuse and replace candidate-only totals before hierarchy
roll-up. Candidate filtering remains limited to expensive position/ticket reconstruction, pairing,
holding, EA and cashflow evidence. Platform rebate discovery is separate and continues to use its
requested recent `create_time` window, defaulting to seven days with a 31-day maximum.

Platform push discovery uses bounded close-time shards: 12 hours for MT5 and one day for MT4, with
adaptive bisection down to 30 minutes after a transient timeout. Shard profit and maximum lot merge
exactly. MT5 distinct-position counts that may cross the configured order limit are re-counted over
the complete window before exclusion; daily distinct counts must never be summed as if exact.
Candidate metadata and USD/USC scaling use `mt5_users_view.Group`, never the unindexed
`mt5_daily_view`. Lifetime profile batches use one query slot per physical database to avoid
competing full-history index scans; AC and DBG retain independent slots. Active-day distinct
aggregation is issued only when that optional filter is enabled. Profile queries use 10-account
indexed batches and retry with 5 accounts on transient timeout using a fresh read-only connection.
Lifetime trading net uses the platform identity `balance - non-trading ledger net`: MT5 aggregates
the money components of `Action>=2` deals and MT4 aggregates `CMD=6` profit. This avoids scanning
all historical trading rows while retaining the same closed trading-net result.
Candidate order reconstruction reuses the bounded close-time shards. MT5 selects candidate
`(Login, PositionID)` pairs through the time index and joins complete position deals through the
position index; duplicate deals from partial closes spanning shards are removed by `Deal`. MT4 uses
the close-time index with the exact candidate-login set. The older 50-account login path remains a
compatibility fallback and recursively splits/reconnects down to five accounts on timeout.

Single-account synchronization queries independent logical sources concurrently but assembles rows
in configured source order before matching. MT5 Terminal Tick reads may combine nearby windows up
to a 15-minute total span; every order is sliced back to its original request range and an empty
slice is retried individually.

Account bonus-arbitrage checks route by CRM schema, server code and login. MT5 reads bounded
`mt5_deals` ledger/execution history; opening-only and partially open Position IDs remain available
for exposure scoring by comparing opened and closed deal volume. MT4 reads bounded `mt4_trades`
balance, credit and market-trade history and preserves the 1970 close sentinel as an open position
for this detector rather than treating it as a close. A requested period expands seven days for adjacent funding events; otherwise registration
history is capped at 400 days. Same-user peer reads retain each peer's own server route. Historical
credit grants, restores and removals are separate events, as are withdrawal reversals and internal
transfers, so attempted and completed extraction are not conflated. Cent/USC monetary values use
the existing confirmed `0.01` scale; standard lots are never currency-scaled. MT5 deal reads include
opening Price and ContractSize, while MT4 includes opening/closing price. Account profiles include
configured leverage and current Margin/MarginLevel. Historical floating P/L snapshots are unavailable,
so the detector clearly labels historical margin level as estimated; an active current-cycle state can
use actual current Equity and Margin.
Historical breach detection orders all closed cycle trades, nets rows with the same close timestamp
and retains the lowest cumulative trading result. It also consumes already-loaded reset/clearing
ledger events and current profile balance/equity, so no additional remote query is introduced.
Later ledger or trading rows cannot overwrite the retained historical low point.
Normalized bonus-cycle trades retain the order/Position or MT4 ticket identifier, symbol,
direction, standard lots, open/close price, contract size where available, open/close time, open state
and net profit for minimum-margin order evidence. Existing
same-user peer histories provide the exact subject/peer order IDs used by visible five-second
opposite matching; no extra remote query is introduced by the detail card.

Platform bonus discovery scans bounded daily positive MT5 Credit/Bonus or MT4 Credit events and
falls back to six-hour shards after a daily query failure. Shared physical AC MT4 and
`mt5_export_new` DBG MT5 sources are read once; the independent `crm_vn_mt5_live2` source is scanned
separately. Daily rows are merged by login before 500-login CRM route batches validate
every configured logical route, rather than opening new CRM routing reads for every day. Candidate
mappings feed the deep detector directly. Candidate profiles and same-user families are prefetched
per logical source; identical bounded histories may be reused within a 64-entry task cache, while
registration/history boundaries remain unchanged. The discovery window is candidate-only; deep
analysis uses the account detector's full historical scope. Candidate grant amounts use mapped
Cent/USC scaling. After cheap candidate filters, current Margin and qualifying positive
`DEP-`/`CRM-DP-` deposits are read in login batches from registration or at most 400 days. `DEP-RS`
reversals are excluded. Both numerator and denominator use the candidate's confirmed money scale.
Their ratio orders the bounded deep queue but never enters domain scoring. Ranking read failures are
reported and retain the candidate through the older bonus-evidence fallback order.

Platform position-risk discovery scans daily indexed `mt5_deals.Time` or `mt4_trades.OPEN_TIME`
shards and performs five-minute login/symbol/action aggregation in SQL. Candidate ranking retains the
largest single event instead of summing multi-day turnover. Shared physical sources are
scanned once, then CRM mappings and current balance/equity/leverage are fetched in 500-login batches.
The candidate stage does not read unindexed `mt5_daily_view` or AC `mt5_positions_snap`. Ranked deep
accounts use routed login/time history for at most the event window plus a 180-day baseline (or 400
days for an unbounded account check). Historical cash equity is reconstructed backward from current
balance, later closed trading P/L and balance-affecting ledger events. MT5 configured leverage comes
from `mt5_users_view`; MT4 uses `mt4_users_view`. Deep history retains MT5 `Order` and ledger `Comment`
or MT4 ticket and `COMMENT` so peak-order evidence and negative-balance reset/clear clues can be shown.
Opening-only peer proximity remains a cheap same-physical-source candidate-ranking hint and is never
projected into final evidence. Deep peer lookup deduplicates all configured AC/DBG MT4 and MT5 sources
by `(host, schema, table, kind)` and queries every physical source. MT4 uses bounded `OPEN_TIME` plus
`CLOSE_TIME` windows and only closed `CMD IN (0,1)` rows. MT5 first reads opening deals in bounded
`Time` windows, then completes candidate `(Login, PositionID)` groups in bounded batches and requires
closed volume to cover opening volume. Pure domain matching requires canonical-symbol equality and
both opening/final-closing deltas within five seconds. Opposite-direction suspected-hedge matches also
require at least 80% lot similarity; same-direction coordination is unchanged. Per-source failures and unclosed target orders
remain explicit coverage metadata rather than clean negative evidence.
Equivalent MT5 opening timestamps and MT4 opening/closing timestamp pairs are de-duplicated without
removing any target from domain matching. Opening-window queries group at most 25 distinct target
windows. If their 20,000-row ceiling is reached, the
adapter recursively halves that target batch and merges de-duplicated rows; a source fails as
incomplete only when one target's five-second window itself remains saturated.
MT5 candidate opening SQL combines each indexed five-second target window with a canonical-symbol
prefix. The dedicated hedge query also pushes opposite Action and the equivalent 80%-125% peer-lot
range into the bounded query. Returned openings are checked again in memory against the target-open map before Position
completion. All modes require canonical symbol and five-second proximity; opposite candidates also
require 80% lot similarity. The dedicated hedge query additionally discards same-direction openings,
while full position-risk discovery retains them without a lot gate for coordination evidence.
Matches from shared AC MT4 or DBG MT5 tables are batch-routed through each represented CRM
`(schema, mt_server_code)` so displayed peer servers are account-specific rather than an ambiguous
physical-source label. Detailed pairs are capped at 500 per direction after complete account/pair totals
are calculated.

The single-account `平台内多账户对锁` Toxic query reuses this physical-source plan for every closed
target entry in the bounded account-analysis history. It returns only opposite-direction matches that
reach at least 80% lot similarity;
same-direction rows loaded by the shared candidate query are discarded. Open target positions are
counted but excluded because synchronized closing cannot be verified. The target route and every peer's
resolved logical route remain explicit in the response.

The relationship investigation reuses the same bounded AC/DBG MT4+MT5 physical-source plan, but does
not forward every historical order. It derives principal orders per symbol (95% cumulative volume with
a five-order floor), submits them as one batch, then aggregates returned rows by peer route/account and
relationship type. Same-direction evidence is restricted to two-second open and close deltas and a
recurrence floor; opposite-direction evidence is restricted to five-second deltas and 80% lot similarity.
The graph receives at most one relationship edge for each peer account and detection type, plus at most
20 auditable order-pair examples. Source coverage remains explicit when one physical source times out or
fails; a partial scan must not be represented as a complete no-match result.

Position discovery's nullable minimum position, peak-lot and event-profit values are applied only
after authoritative deep event reconstruction. Initial candidate position and lot values may
prioritize likely matches inside the bounded queue but cannot satisfy or reject the final filter.

K-line quote providers are local read-only Terminal definitions selected through
`KDESK_KLINE_QUOTE_SOURCES`. The file contains provider identity, Terminal path, represented logical
servers, allowed hour offsets, aliases and optional explicit price corrections, but no passwords.
Database chart rows retain platform/server provenance so each symbol selects a same-source provider;
fallback is eligible only when named by that route. Provider identity is part of new quote-cache
names, while the loader still recognizes old unqualified cache files. The unscoped legacy default
Terminal is the universal read-only fallback for database tasks and is always evaluated with the
stricter fallback validation threshold rather than inferred to be same-source. When an explicit
registry is configured, missing database routes fail before quote access and expose the requested
route plus credential-free configured-provider metadata.

## Relationship-expansion source profile

Same-CRM-user graph evidence uses the read-only legacy
`account_relationship_core_payload`. It resolves the selected platform/server and returns only
mapped trading-account identity, platform and server. Graph expansion must not call dashboard
`risk-panels` or retain order history merely to discover this CRM relationship; the full dashboard
continues to use its existing endpoint independently.
Relationship-only EA and Copy calls pass an internal `_relationship=1` marker across the legacy
bridge. That marker preserves the returned read-only evidence but bypasses the dashboard result cache;
it is not a public API parameter and does not alter interactive dashboard caching.
Within one discovered current-LastIP cohort, only the representative account runs EA and Copy
discovery. Sibling accounts retain their CRM and LastIP reads and return explicit skipped-source
coverage; the graph does not silently claim that their individual automation history was queried.

Current-CID discovery reads `mt5_users_view.ClientID` on the already-routed MT5 server. It returns
same-server peers only, ignores `ClientID` zero/null, is unavailable for the current MT4 export, and
uses the same cohort de-duplication and automation-reuse rule as current LastIP. It is unrelated to
order-comment text such as `CID=...`.

## Safety

Remote adapters expose query/export only. Password, phone-password and API blob fields must never
be selected or logged. MT4/MT5 Manager state changes are prohibited.

Except for the bounded recovery-request/status handshake above, the copy-pool monitor is read-only
with respect to its local source files. Missing, stale or malformed snapshots produce unavailable or
empty monitoring states; they never cause 8777 to recover a copier directly, mutate an account or
send an MT order. A queued request is inert until the already-running Producer consumes it.
