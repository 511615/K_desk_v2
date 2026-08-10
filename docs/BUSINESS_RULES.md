# Business rules

## Finance

- `closedNetProfit = grossClosedProfit + tradingFees + interest`.
- `comprehensiveProfit = closedNetProfit + holdingProfit + rebate + compensation + reward + negativeBalanceClear`.
- Net deposit is deposits minus withdrawals and excludes compensation, rewards and negative-balance clearing.
- MT5 `CRM-DP-` comments are deposits and `CRM-CW` comments are withdrawals.
- MT4 `CPS_` balance rows are compensation and `CCB-Reward` rows are negative-balance clearing.
- Historical funds backtrace is an evidence view, not a compensation decision. It replays routed
  MT4/MT5 trade and ledger deltas after the first authoritative daily balance/Credit anchor. External
  deposits and withdrawals use their recognized `DEP-`/`WDR-` or CRM equivalents; `TFM-`, `TFH-`,
  `TRS-` and `CRM-T` are internal transfers and never external net deposit. Credit grant/removal,
  negative-balance clear, compensation, reversal and other balance adjustments remain separate.
  A liquidation marker requires platform Stop Out evidence (MT4 `REASON=5` or MT5 `Reason=6`) or an
  explicit negative-balance-clear entry; stop loss and negative realized P/L alone are not enough.
  A chart may show reconstructed balance and Credit. MT5 online backtrace does not read its
  unindexed daily view; its complete indexed ledger is calibrated from the authoritative current
  Balance/Credit row, while historical and
  intraday equity/margin remain `unknown` unless an authoritative snapshot exists. The feature never
  decides an amount to deduct, clear or repay.
  K-line funds replay reuses the same facts for Balance/Credit and liquidation display. It carries the
  last known pre-window state into a filtered chart; a missing state is shown as unknown. Historical
  margin, margin level and equity must not be inferred from a default opening balance or leverage.
- MT5 USC detection uses a distinct `Cent` or `USC` users-group segment. Explicit currency segments
  are retained; standard groups use the configured source default USD. The resulting `0.01` USC
  scale applies to platform money only, not prices, lots, identifiers, timestamps or CRM rebates.
- Rebate detail is hierarchical: aggregate at the requested grain before joining trades so trade
  counts are not multiplied. CRM `rebate_task_detail.rebate_amount` is aggregated unchanged;
  `usd_or_usc` is evidence/display metadata and never applies a currency scale to CRM rebates.
- Same-name accounts are all trading accounts assigned to the same CRM `user_id`, including accounts
  on other configured server codes. Their finance and trading values are calculated independently
  through each account's own logical server route before totals are aggregated.
- MT4 closed-order analytics require `CMD IN (0,1)` and `CLOSE_TIME > OPEN_TIME`. The platform's
  `1970-01-01 00:00:00` open-position sentinel is excluded from closed profit, order counts, holding
  durations and daily P/L; current floating P/L remains sourced from the current account state.
- Platform rebate-churning scores each recipient IB independently from that IB's actual receipts.
  Rebate presence confirms the stage but is not suspicious structure. The model is structure 50,
  economics 30, IB coordination 15 and funding cycle 5, minus up to 20 counterevidence points.
  Structure is the maximum of within-account pairing, turnover and different-customer cross-account
  pairing. Scores 60, 75 and 90 map to warning, high and severe.
- Rebate-churning exposure uses standard-lot equivalents: after normal MT4/MT5 lot conversion,
  confirmed Cent/USC account lots are multiplied by `0.01`. This applies to displayed/summed lots,
  lots-per-deposit and pairing loss-per-lot calculations, not prices, IDs or CRM rebate amounts.
- A formal IB's own trading accounts participate in its subtree. Upstream supervisory CRM nodes are
  retained for relationship display but receive a rebate-churning score only when `user_type=1`.
- Rebate account audit without explicit dates is full history for every routed account in the
  displayed tree. Candidate selection may reduce detailed structural reads, but must not reduce or
  zero order count, lots, trading P/L or active days. Platform rebate discovery remains a bounded
  recent-window task with a seven-day default and a 31-day maximum.
- The rebate tree's `返佣过大` row warning is presentation-only. It applies to a customer when
  hierarchy rebate is positive and `customer trade P/L + hierarchy rebate > 0`; it adds no score.
  Hiding empty nodes removes zero-order/zero-contribution account rows and recursively empty
  branches, while preserving all API totals and audit calculations.

## Automation

- The dynamic copy pool rebuilds from all eleven verified logical routes after the MT5 trading day,
  with nine physical sources scanned read-only and the selected pool restored from a versioned
  same-day private snapshot after restart. Any missing source rejects the build; a partial pool is
  never deployed.
- Pool identity is `CRM route + Login + normalized product`. Shared-source ambiguity is excluded.
  The first candidate gate is a close in the rolling seven-day window. The core gate is
  `30-day closed trading net + current same-product floating P/L > 0` after normalized copy cost.
  Scoring excludes rebates, converts confirmed Cent/USC money by `0.01` without scaling lots,
  applies 1.5x spread stress, negative-balance/equity, stop-out compensation and margin gates, and
  gives an additive `0.02` A-containing status boost that cannot bypass a hard gate.
- The cross-product population targets up to 30 unique monitored clients plus up to 70 unique reserve
  clients; one client may retain multiple product sleeves. A smaller non-empty qualified monitor
  population is accepted and disclosed rather than filled by weakening hard gates; zero qualified
  monitor clients stops preflight. Product coverage uses sleeve floors and
  an initial 40% per-product monitor-account cap with an explicit fallback when infeasible. Base
  product weights also use a 40% cap when at least three products make it feasible. With one or two
  qualified products, residual weight is distributed evenly and disclosed so base weights still
  total 100%; the live 40% product-direction cluster risk limit remains independent. An
  active sleeve requires P25 holding above
  10 seconds, median holding from 60 seconds through eight hours, P90 at most 24 hours, fewer than
  20% closes within ten seconds and positive stressed profit. After those gates, every sleeve with a
  positive adjusted score receives proportional weight input; factor ranking is not a second `0.55`
  hard gate and the allocation does not subtract that value. Existing per-client, sleeve, route and
  product caps remain in force, while product weights and within-product customer weights normalize
  where those caps are feasible. Risk utilization is not embedded in those weights. When current
  effective weights exceed the separate 25% client-risk budget, every positive sleeve is scaled by
  the same ratio; the budget must not be enforced by zeroing the lowest-ranked sleeves one by one.
- Source execution is customer-owned: `account + source Position` maps to one or more Demo Tickets.
  Open, add, reduce, close and reverse events may touch only those Tickets. Opposing customers remain
  independently open; combination risk may reject or shrink additions but never nets customer
  Tickets. Startup and shadow-observed source positions are monitor-only and never chased. A proven
  MT4 partial-close residual (`COMMENT` references the former Ticket) may rekey the same-direction,
  smaller source Position while preserving its owned Demo Ticket and original entry deadline; it is
  a reduction, never a new entry or inferred ownership claim.
- The explicit Demo minimum-lot exception has stable ownership. Once a qualifying source Position
  owns a minimum lot, later reconciliations preserve that Ticket while eligibility remains true.
  Same-direction siblings may own independent Tickets in the explicit Demo mode. Eight open
  requests are permitted in a rolling 60-second window; the next request hard-stops execution and
  flattens strategy Tickets instead of allowing an order storm.
- Independent Demo comments must fit the server's 16-character retained limit. Ownership state is
  persisted immediately before and after an execution. An unpersisted actual Ticket may be recovered
  only by a unique exact comment-plus-product match to a persisted source position; otherwise the
  execution hard stop remains in force.
- The 10,000 USD profile uses a 1.5% combination cycle-loss budget and 3% daily hard stop. Each
  client's loss allowance is that cycle budget times its portfolio base weight and uses only that
  client's Demo realized plus floating P/L after commission, fee and swap. Loss use at 20/50/80/100%
  follows the 100/70/25/0 reduction curve. Exhaustion closes only that client, pauses two hours and
  requires 15 minutes of recovery shadow. Weight decreases are immediate; recovery increases no
  faster than five percentage points per 15 minutes and ten per hour.
- Local operator controls may disable automatic new exposure or one of the equity-floor, daily-loss
  and cycle-loss gates for the Demo experiment. Missing or invalid controls enable every gate. A
  resume request clears a latched daily stop once and enters recovery shadow; it never directly
  authorizes a broker order and never disables margin, outage, Friday or Ticket-ownership controls.
- When the explicit minimum-lot exception is active on `ACCMGlobal-Demo` in `StagedLive`, an active
  client's loss allowance is floored at the existing 20% per-client share of the cycle budget. This
  exception aligns the indivisible 0.01-lot test exposure with its stop budget; it does not increase
  a zero-weight monitor client, apply on another server/mode or bypass whole-portfolio stress or
  margin gates. The product-direction cluster limit is disabled only in that explicit Demo mode;
  same-direction minimum lots remain bounded by the 1.5% whole-portfolio stress budget and margin.
- A 12-hour source position cannot add copied risk. At 24 hours all copies for that client close and
  the client pauses. Outside the explicit Demo minimum-lot exception, a product-direction cluster
  may use at most 40% of combination stress budget.
  Margin/equity at 15% blocks additions and 25% triggers a strategy hard stop. Three seconds of
  selected-source staleness blocks additions; thirty seconds flattens all strategy Tickets, including
  offsetting gross positions whose net is zero.
- Live source polling starts every selected physical source in the same platform poll wave. MT5 and
  MT4 poll concurrently, and a completed MT5 batch is applied before waiting for MT4 snapshots.
  Runtime database connect/read/write operations use a two-second bound and reconnect on the next
  cycle after failure; the longer build-time timeout remains limited to complete historical builds.
  A failed source never advances its cursor or converts missing evidence to an empty result. Live
  activation requires the complete reconciliation/latency qualification once. Thereafter one routine
  reconcile drift does not revoke an otherwise healthy live state, but route/source completeness,
  duplicate-event absence and selected-source freshness remain per-cycle hard gates.
- MT5 balance, credit and other non-trading ledger actions advance the per-source cursor so polling
  cannot stall, but they contribute no position change, intraday trading P/L, dynamic-weight change
  or executable signal. A duplicate or out-of-order cursor is ignored within that physical source.
- MT5 market Deals received in one poll are source-ledger authoritative as a batch. Execution occurs
  once per account/product/Position terminal transition, never once per intermediate Deal. A complete
  open/close round trip already flat by the end of the batch records evidence and P/L but sends no
  Demo order. Residual opens and reversals use the first risk-increasing Deal's timestamp; reductions
  and closes remain immediately risk-reducing. Pure reductions execute before unrelated additions.
  Each terminal transition is durably pending during the process, so one Position failure cannot lose
  later Position transitions; later events for the same Position coalesce before retry. Restart
  resumes only risk reduction, never an unfilled open or opposite reversal leg. Expired residual
  exposure is `signal_expired_no_copy`, not source-flat.
- MT4 snapshot signal age normalizes raw `OPEN_TIME` by physical source: AC `mt4_export_syc` is UTC;
  DBG CN Live1/Live2 are UTC+3; DBG VN Live3 remains fully routed with a provisional UTC+3 mapping
  pending fresh runtime confirmation. The database session's `+08:00` rendering is not the raw
  platform datetime's timezone.
- An eligible source Position without a Demo child must pass its original entry-delay budget on every
  retry. After expiry it remains `signal_expired_no_copy` and cannot be chased when a prior rejection
  clears. A missing or deferred historical-delay sleeve record uses the conservative five-second
  runtime budget (also bounded by `holdP25 / 3`). Existing owned children remain subject to
  reductions, closes and emergency risk release.
- Every risk-increasing order uses the most recent opening, increase or reversal signal timestamp;
  reductions and closes never refresh that deadline. The deadline is checked before execution gates
  and again immediately before the broker open request. An expired addition is ignored, while an
  expired reversal closes the old owned Ticket but cannot open its opposite leg.
- Pool quality uses same-product closed trading net plus current same-product floating P/L for the
  strict positive candidate gate. Current floating profit cannot hide later account-risk failures or
  increase a dynamic weight. Current floating loss at or above 10% of equity or margin usage at or
  above 50% of equity is a build hard gate. Below those extremes, negative realized/floating
  components, margin use and gross-versus-net hedge evidence reduce the deployable score.
- V0.1 defers historical Tick delay sensitivity from both scoring and hard eligibility. The primary
  factor score is 45% cost-adjusted profit per copied trade, 25% recent five-day cost-adjusted
  profit per copied trade, 15% copy-cost coverage and 15% adverse-position carry quality, using
  cross-sectional percentile ranks.
  Source money is converted to USD first, then source P/L is scaled from the 30-day average closed
  execution size to that Demo product's actual minimum lot. Estimated copy cost is the product
  default round-trip spread at the same minimum lot plus a 25% execution reserve, with rebates
  excluded. Runtime quote spread is priced by the selected Demo terminal's one-lot profit
  calculation in its account currency, not by raw quote difference times contract size when the
  quote currency differs. MT5 close counts and lots both use exit/reversal Deals, so partial closes cannot divide
  unrelated opening volume. The 30-day cost-adjusted comprehensive P/L must be positive; seven-day
  cost coverage must be at least one before percentile ranks are calculated; failed rows cannot
  move qualified-account ranks. Missing or non-finite cost evidence fails closed. Excessive
  cashflow-adjusted equity MDD, incomplete intraday floating-equity coverage, extreme short holding
  and severe weekend holding remain non-compensable hard failures. Cashflow-adjusted equity begins
  at the first positive funded observation: earlier zero-equity rows are pre-funding state and the
  first observation's funding is not subtracted from itself. Actual platform equity below zero is
  the `negative_equity` hard gate, and only authoritative platform daily/current evidence may set it;
  an incomplete reconstructed snapshot path cannot. Capital reaching zero after later deposits/withdrawals are removed
  is the separate `cashflow_adjusted_capital_exhaustion` hard gate. Daily loss uses only the bounded
  31-day evidence window and never searches older history for an anchor. A newly funded account uses
  its first positive funded observation as its first-day baseline. Real-time quote age, source
  staleness, signal latency and expiry remain active; new-risk signal age is capped by five seconds
  and holding P25 divided by three.
- Carry risk is a bounded candidate-stage calculation, never a full-universe Tick replay. It combines
  55% observed maximum floating-loss depth relative to 8%, 30% maximum underwater duration relative
  to 24 hours and 15% maximum simultaneous losing positions relative to five. The resulting 0-100
  score maps to `carry quality = 1 - score/100`. A score at least 70, observed 30-day floating-loss
  ratio at least 10%, underwater duration at least 48 hours or eight simultaneous losing positions
  is a non-compensable build-time rejection. Carry risk does not remove an already selected sleeve
  from intraday activity or alter an open copied Position; existing per-client loss budgets and
  portfolio loss limits remain authoritative during trading. The first version uses bounded 30-day
  equity drawdown and reconstructed losing-position paths as conservative historical proxies, plus
  exact current position aggregates; it does not claim Tick-level MAE precision.
- Every ten seconds the copier refreshes client Demo loss budgets, realized trading P/L and
  authoritative current open risk from selected physical sources. Every 15 minutes it re-ranks the
  current monitor/reserve range. Every hour it reads bounded one/four-hour increments for the
  accepted daily factor-ready universe; this can reorder or remove sleeves but cannot bypass a
  historical quality warning. The complete 30-day build runs at 05:15 Beijing. An incomplete refresh is
  rejected rather than treated as zero.
- Restart and hourly membership changes never authorize missed source increases or reversals.
  Offline reductions and closes may only reduce Demo risk; current positions first seen at restart
  or during entry shadow remain monitor-only until they close.
- A persisted open source Position without an actual owned Demo Ticket is also monitor-only after
  restart, even when its prior state was copy-eligible. Exact comment-plus-product recovery runs
  first; only a uniquely recovered Ticket remains managed. The orphan source mapping is removed on
  source close and can never create a replacement order.
- A fresh sleeve that is hard-eligible, activity-eligible, minimum-lot feasible and in the active
  zone enters `ACTIVE` on its first 15-minute ranking and takes its current `live_base_weight`
  directly. Normal entry does not require a ranking count or observation window. A persisted legacy
  `ENTRY_SHADOW` promotes on its next qualified ranking, while a qualification or activity loss
  returns it to monitor. `-DemoFastActivation` remains a compatible launcher/status option but is no
  longer required for direct activation. Terminal, operational, ownership, signal-expiry and risk
  gates remain mandatory. Loss-limit recovery shadows remain separate and unchanged.

- Copy origin detection uses explicit source identifiers in comments/magic fields and reports each
  source separately. MT5 reconstructed trades use only the opening deal's CPT comment as the source
  Position ID; a closing comment displayed after ` / ` is not a second source identifier.
- Follower profit is shown per follower and source order; net profit includes gross profit,
  commission, fee, swap and taxes in display currency. Source and follower account totals retain
  source precision until aggregation and must reconcile after display rounding. MT5 export detail
  retains one row per Position; the copy workbook is organized by source owner, not by the queried
  follower, and contains only owner totals, follower summaries and matched follower orders.
- EA comment grouping always queries the authoritative opening Comment exactly before considering a
  structural template. Dynamic fallback is allowed only after every exact provider succeeds and the
  exact identity has fewer than two valid routed accounts; provider failure is never interpreted as
  an empty exact result. Same-server EA matches retain Comment plus MT5 `ExpertID` or MT4 `MAGIC`;
  cross-server exact named matches retain Comment evidence.
- `CPT-SS#id`, `CPT #id`, `@route@source@route`, `channel/channel/source` and long
  `account-source` structures are labelled `可能是跟单路由`. They remain visible with member profit
  detail in the EA dialog but have `countedAsEa=false` and are excluded from all EA headline counts,
  lots and profit totals. Dynamic EA templates cover order references, stable EA instance fields,
  CID fields and Grid/Layer/Order levels. Unknown stable-text/long-number formats are fingerprinted
  and learned locally. System close/stop-out, funding/credit, origin-reference and contact-only
  comments are excluded before exact lookup and cannot be restored by automatic learning.
- An MT5 account with no usable opening Comment may use a same-server no-comment fallback. It never
  matches a numeric prefix. At least five complete non-zero ExpertIDs, 80% overlap in both directions,
  matching symbol/direction within two seconds, three distinct times and a 60-second span are required.
  Qualifying groups remain `可能是跟单路由`, have `countedAsEa=false` and do not change EA KPIs.
- Relationship-network scoring is an investigation-priority rule: same-CRM-user, current `LastIP`,
  EA/route, Copy, CRM-rebate and qualified Toxic sync facts contribute through the ACC-REL-003
  strength table, but never produce an automated fraud conclusion or trading action. A current
  `LastIP` is an observation of shared current login IP, not proof of shared device ownership.

## Toxic and market-pushing

Detectors operate on the selected account source and order set. Market-pushing evidence may include
recurring peer accounts, open/close synchronization and tick evidence. Missing quote providers or
partial evidence must degrade explicitly; unavailable evidence must not be interpreted as a clean
result. Detection never changes an account or trade.

Push-discovery lifetime trading net is derived from the platform accounting identity rather than a
full trade-row scan: MT5 current `Balance` minus all `Action>=2` ledger net, and MT4 current
`BALANCE` minus `CMD=6` balance-row profit. The deposit limit still sums only qualifying positive
deposit rows. Money scaling is applied after the raw account-currency identity.
Lifetime profit, deposit and active-ratio restrictions may be evaluated after structure scoring for
query efficiency, but must be applied to every structurally eligible account before deep-queue rank
truncation. Ranked candidates may be evaluated progressively and stop once the configured Top-N is
filled; an unprofiled lower-ranked candidate cannot displace a higher-ranked qualified candidate.
Lifetime fields cannot change the structure score or its ordering.

Platform push discovery applies a fixed economic-evidence definition after structural ranking.
An account must have positive lifetime trading net before expensive deep analysis. A completed
deep result is listed only when its suspected push intervals also have positive normalized net and
either (a) at least 100 display-currency units of net profit, or (b) at least 50 units and a return
of at least 10% on cumulative qualifying deposits. Both boundaries are inclusive. Missing/zero
deposit cannot satisfy the relative branch but may satisfy the 100-unit absolute branch. Optional
discovery filters still control candidate breadth; disabling them cannot waive this final
classification requirement. Economic rejections are auditable exclusions, not detector failures.

Bonus arbitrage is evaluated from historical funded-credit cycles, not current Credit. A cycle
tracks confirmed cash funding, initial promotional credit, credit restores/removals, trades,
withdrawal attempts and reversals, completed withdrawals, internal transfers and related-account
opposing trades. Credit lifetime is dynamic. A complete profitable extraction loop may reach high
or severe risk; locked profit without extraction is capped at warning. During the complete cycle,
historical cumulative closed trading loss of at least 75% of cash plus Credit reaches warning. A
negative-balance reset/clearing event, cumulative closed loss reaching 100% of cash plus Credit, or
a current negative balance/equity reaches at least severe. Later recovery, deposit or reset does not
erase that historical low point. Same-time closes are netted before comparison. Credit presence,
ordinary volume, profit, loss or account linkage alone cannot establish bonus abuse. A later
completed extraction loop is not downgraded by the unpaired-sacrifice cap. Missing promotion terms
must remain an explicit limitation.
Promotional Credit must be at least 20% of the paired cash deposit for every bonus-arbitrage path.
The exact 20% boundary qualifies. A lower-ratio cycle remains evidence-only, is capped at 39 and
cannot trigger extraction, locked-profit, sacrifice or repeated-cycle escalation.
Before any extraction, heavy positioning anywhere inside an eligible promotional-Credit cycle
reaches high risk. Heavy positioning uses the standard margin level `equity / used margin * 100%`;
the cycle's lowest value at or below 200% qualifies, and a value at or below 100% is labelled extreme
liquidation pressure. Lower values mean fuller positions and greater liquidation risk. Historical
used margin is estimated from opening price, contract size and configured leverage; current open
positions prefer actual account equity and Margin. Direction concentration, withdrawal and a visible
opposite account are not required. Evidence records the first lowest-margin timestamp, equity, used
margin, concurrent standard lots and orders still open at that point; displayed order detail is capped
at 50 without changing full totals or score. Visible five-second opposite matches covering at least 40% of lots
increase confidence and evidence strength only; their absence is a limitation, not clearing
evidence, and does not lower the preventive-path score.

Platform bonus discovery treats a recent positive Credit/Bonus row only as a candidate signal. It
adds no score. After minimum-grant and handled-account filtering, candidates with recognized deposits
are ranked by current occupied margin divided by cumulative qualifying deposits, descending.
Accounts without a usable deposit follow them; explicit bonus evidence, normalized grant amount,
count and recency break ties or provide the fallback order. The operator's deep-account limit then
bounds the queue evaluated by the complete historical cycle model. Candidate ordering and optional
filters do not change the account score.

Feature documents contain the detailed current behavior and acceptance samples for each rule.

Heavy-position timing detection first requires account-relative economic exposure and only then
classifies timing. The candidate/high/severe references are 30%/50%/70% estimated margin over
historical event equity, 10%/20%/35% stress loss over equity, 2x/3x/5x the account's normal batch
exposure and 70%/85%/95% net-direction concentration. Configured leverage is used both to estimate
margin and as a small context signal; leverage alone cannot create a finding, and gross
notional/equity remains visible so high leverage cannot conceal the position. Friday exposure held
through closure is weekend risk; concentrated `+08:00` 21:45–22:30 entry is opening risk; reopening
additions after a weekend position form a combined event. Profit or loss is descriptive, not a gate.
Estimated margin is peak gross notional divided by configured leverage. Estimated margin/equity rises
as the position becomes fuller; estimated margin level is event equity divided by estimated margin times
100% and falls as the position becomes fuller. Five-minute batch opening/closing strengthens evidence.
A peer counts only when canonical symbols match, both positions are fully closed, and both opening and
final closing times differ by no more than five seconds across any configured AC/DBG MT4/MT5 source.
Same-direction pairs receive coordination evidence; opposite-direction pairs additionally require at
least 80% lot similarity and are separately disclosed
as suspected hedge clues and do not receive coordination points. Opening-only candidate proximity is
ranking evidence only and cannot enter a final result. Peak lots, concurrent entry-order
count and the exact peak order identifiers are evidence fields. A completed event is marked penetrated
when actual event loss exceeds reconstructed event equity; negative-balance reset/clear ledger comments
without that calculation are only suspected evidence. Open events or unreliable equity reconstruction
return `数据不足`, with unclosed orders and unreliable historical equity named separately. Staggered additions and long holding are counterevidence.

Platform heavy-position discovery may apply three independent optional result thresholds after the
complete account analysis: minimum position is `estimated margin / event equity` expressed as a UI
percentage, minimum lots is the event's peak concurrent lots, and minimum profit is event net profit
in display currency. Blank values impose no restriction. These thresholds do not change the score;
enabled thresholds with unavailable evidence do not qualify. Client-side ranking sorts the already
returned rows descending by profit, position or score and never changes detector output.

`平台内多账户对锁` is a separate factual query, not a heavy-position or account-internal reverse-leg
score. A pair is returned only when the canonical symbol is the same, directions are opposite, both
positions are fully closed, both opening and final closing differ by at most five seconds and the smaller
lot size is at least 80% of the larger. The feature discards same-direction matches and labels every returned pair
as suspected rather than confirmed hedging. A no-match conclusion is valid only when every configured
physical source completed; partial coverage or no closed target order is data-insufficient.

## K-line quote validation and closed-market display

- Resolve a candidate family from exact name, normalized suffix/Roll form, configured aliases and
  M1 endpoint evidence; `UT100` belongs to the `NAS100Roll` family.
- Validate open and close endpoints for at most five evenly sampled orders. Same-source quotes need
  at least 60% envelope hits and normalized median distance no greater than 2. Explicit fallback
  quotes need at least 80% hits or every endpoint within tolerance. One bounded near-match route is
  permitted only with at least 70% raw hits, 90% endpoint tolerance hits, median normalized distance
  no greater than 0.25 and maximum normalized distance no greater than 1.25.
- Try existing GMT/GMT+3 modes before expanding to allowed integer offsets GMT-4 through GMT+4.
- Never infer an arbitrary whole-series price shift. Apply and disclose only a provider-configured
  correction.
- A symbol failure is non-fatal when another symbol succeeds. All-symbol failure is terminal.
- Quote gaps over five minutes split aggregation. Gaps over sixty minutes are closed/no-quote spans.
  Compressed mode labels boundaries; elapsed-time mode leaves blank time. Missing-minute trades use
  warning markers at their real timestamps.

# Score-propagated Kuzu relationship investigation

`ACC-REL-003` uses a local direct-account evidence projection. The seed starts at 100 and each
residual score forwards through one relation as `residual × fixed relation strength × 0.96`. A node
is visible once it has a contribution; it only forwards when its combined noisy-OR score meets the
operator threshold. Duplicate evidence within one relation family retains the maximum contribution;
different families combine as `100 × (1 - product(1 - contribution/100))`. The displayed score is
an investigation priority, not a fraud decision. `login_ip` is current `LastIP` only. Toxic sync
uses only governed main/heavy orders with the complete open/close synchronization and opposite-lot
requirements owned by `TOX-POSITION-001`. The implementation has 2,000-node and 10,000-expansion
safety caps, a 12-second discovery budget and reports truncation rather than implying complete coverage.
The replaced account relationship endpoint applies this scorer to a request-scoped temporary Kuzu
projection and reads the next account only if its score remains at least the operator threshold.
It obtains cross-account MT5 peers from same-server current `LastIP` and, when requested, Toxic
sync evidence from completed same-symbol orders whose opening and closing timestamps are both within
five seconds; opposite directions additionally require at least 80% lot similarity. The implementation
limits account discovery to 100 and 12 seconds, limits each evidence source wait to six seconds, and
limits opt-in Toxic checks to two high-score accounts. It marks truncation or query-budget exhaustion.
