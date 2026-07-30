# AUT-POOL-001 execution-quality remediation plan

Status: V0.1 full read-only preflight, Full verification and 30-minute Shadow acceptance passed

Current behavior authority: `docs/features/automation/dynamic-copy-pool-monitor.md`

Scope: external all-route producer, independent Demo execution, 8777 read-only projection

Deployment state: 8777 account service and post-acceptance Shadow running; Demo Live remains prohibited

## Objective

V0.1 scope decision (2026-07-29): historical Tick delay sensitivity is deferred to a later version.
Sections 1 and 7 remain the future design record, not V0.1 acceptance requirements. V0.1 performs
no Tick partition load and gives delay no score or hard-gate role. The other six factors normalize
to 25/18.75/18.75/12.5/12.5/12.5. Real-time quote/source freshness and signal expiry remain active,
using `min(5 seconds, holdP25 / 3)` until historical break-even delay is validated. The account
detail page also removes the embedded copy-experiment panel; monitoring stays on `/copy-pool`.

Read-only preflight result (2026-07-30): producer
`copy-pool-multisource-v6-weight-fallback` scanned 11/11 logical routes and 9/9 physical sources
without source failure, selected seven fully qualified monitor clients and six active sleeves, and
produced a 100% base-weight total. Only XAUUSD passed all current hard gates; other supported
products remained in the accepted universe but failed primarily on drawdown, negative-equity,
daily-loss, weekend-holding or evidence-coverage gates. Sparse product coverage is disclosed and
does not weaken those gates. The complete build took about 25.5 minutes and peaked near 1.9 GiB;
streaming source-history release remains a performance follow-up, not a Shadow acceptance waiver.

Shadow result (2026-07-30, 15:05-15:37 Beijing): the Capital10k Shadow ran more than 30 minutes
without live authorization. It retained zero strategy lots, zero Demo Ticket ownership, zero
duplicate events and no runtime error across 313 recorded status samples. Reconciliation reached
156 consecutive checks; all seven selected physical sources were healthy. The 15-minute rank and
hourly discovery schedules both executed. After hourly discovery, 12 monitor sleeves remained,
the six activity-eligible sleeves retained a 100% base-weight total, non-activity sleeves held zero
base weight, and the final executable weight remained zero. The 8777 projection matched producer
state. Continuous Shadow was restarted after acceptance so the dashboard remains current; Demo Live
was not enabled.

Extend the independent customer-position copier with quote-replayed delay robustness, cashflow-
adjusted equity drawdown, overnight/weekend quality and stable intraday ranking. Hard risk failures
must remain non-compensable: high historical profit cannot override delay-after-loss, excessive
drawdown, negative equity, stop-out compensation, extreme short holding or severe weekend holding.

## 1. Real-trade Tick delay replay

The delay factor must use each customer's actual opening and closing events. Uniformly sampled Tick
endpoints are useful only for performance benchmarks and are forbidden as customer-factor evidence.

For XAUUSD, replay every source position through ACCMGlobal-Demo `XAUUSD` bid/ask Tick data at
separate entry and exit delays of 0.5, 1, 2, 3 and 5 seconds. Position reconstruction must preserve
direction, volume-weighted partial entries/exits and source event time. A buy executes at ask and
closes at bid; a sell executes at bid and closes at ask. Demo bid/ask already contains spread, so
spread must not be charged twice. Additional slippage uses a measured adverse distribution by entry
and exit, symbol and session; commission and swap remain separate costs.

Each delay produces:

- stressed net profit and retained-profit ratio;
- stressed PF, PF retention and win-rate decline;
- entry and exit slippage separately;
- entry, exit and complete-trade executable ratios;
- average net profit versus expected copy cost;
- entry, exit and combined break-even delay.

A quote is executable only when the first valid two-sided quote after signal arrival is within the
maximum quote-wait window. Market closure, quote gaps and a signal older than its client budget are
not executable. The client signal budget is:

```text
allowedDelay = min(conservativeBreakEvenDelay, holdP25 / 3)
```

`conservativeBreakEvenDelay` is the minimum of exit and combined break-even delay. If the five-
second grid has not crossed zero, replay extends in bounded steps up to 30 seconds or `holdP25 / 3`,
whichever is smaller. Entry and exit expiry counters remain separate.

The proposed score is additive after all components are normalized to `[0, 1]`:

```text
DelayScore = 0.50 * retainedProfitAtActualP95
           + 0.30 * pfRetentionAtActualP95
           + 0.20 * executableRatioAtActualP95
```

The earlier draft's minus signs are rejected because they would reward lower PF retention and lower
executability. Delay hard gates are: stressed net profit above zero, stressed PF at least 1.05,
profit retention at least 40%, executable ratio at least 80%, conservative break-even delay at least
twice actual P95 latency and average net profit at least twice expected copy cost.

Every runtime signal records source event time, database arrival, risk-decision time, order-send,
Demo fill and close-fill time. Signals arriving beyond their budget are not chased, are recorded as
`signal_expired` and reduce copyability. Repeated expiry immediately removes the sleeve from the
active pool under a configurable count/window contract.

## 2. Cashflow-adjusted equity drawdown

Drawdown uses equity including floating P/L and removes deposits, withdrawals, Credit and other
non-trading cashflow effects:

```text
adjustedEquity = observedEquity - cumulativeNetExternalCashflow
MDD = max((priorAdjustedEquityPeak - laterAdjustedEquityLow) / priorAdjustedEquityPeak)
```

Required outputs are 20-day MDD, 60-day MDD, current peak drawdown, maximum daily loss, maximum
consecutive loss, drawdown recovery time and the worst reconstructable intraday floating drawdown.
Daily and intraday coverage are explicit. A route without sufficient equity/floating history cannot
be labelled clean and remains monitor-only until coverage is complete.

Initial hard gates are 20-day MDD at most 10%, 60-day MDD at most 20%, current peak drawdown at most
10%, maximum daily loss at most 8%, and no negative equity, balance breach or stop-out compensation
in 60 days. Passing accounts receive a separate return/MDD quality score; hard gates are never
offset by return.

## 3. Overnight, weekend and long-loss quality

The producer calculates per logical route using its verified platform trading clock:

- overnight ratio and cross-natural-day ratio;
- weekend count and weekend ratio;
- swap drag over positive gross profit;
- long-loss ratio using the same Tick path/MAE cache;
- additions made while a position remains in prolonged floating loss.

For the gold intraday pool, median holding remains 60 seconds through eight hours. P90 from eight to
24 hours is progressively penalized; P90 above 24 hours is excluded. Overnight below 10% is neutral,
10%-30% is linearly reduced, above 30% is materially reduced or routed to a future swing pool and
above 60% is excluded. Two or more weekend holds in 60 days, or a ratio above 3%, excludes the
intraday pool. Runtime retains the existing 12-hour add block and 24-hour client close/pause.

Friday server time 22:30 blocks new exposure and additions; 23:30 closes every remaining strategy
gold Ticket by actual Ticket set, including exact offsetting gross positions. A future gold swing
pool requires a separate lower budget and cannot share this intraday ranking.

## 4. Base factor model and hard gates

Proposed base-factor weights:

| Factor | Weight |
| --- | ---: |
| Five-day risk-adjusted return | 20% |
| Twenty-day risk-adjusted return | 15% |
| Spread-stressed return | 15% |
| PF and profit/loss structure | 10% |
| Tick-replayed delay robustness | 20% |
| Return / maximum drawdown | 10% |
| Holding, overnight and weekend quality | 10% |

The base score is multiplied by current floating-loss, margin, holding-risk and live execution-
quality coefficients. Negative equity/balance breach, stop-out compensation, excessive MDD,
delay-after-loss, extreme short holding and severe weekend holding are evaluated before scoring.

## 5. Ranking populations and schedule

The 30-account monitoring pool and 70-account standby pool are counted by unique client
`account_key`, never by sleeve. One client may retain multiple independently qualified
`account x product` sleeves. Ranking and admission occur at sleeve level, while the client's
daily loss allowance remains one client-level budget shared by all of its executable sleeves. The
active subset is determined by risk budget and minimum 0.01 lot feasibility rather than a fixed
count.

Product coverage is protected through sleeve floors so a liquid product cannot consume the entire
cross-sectional population. Initial assignment caps each product at 40% of unique monitoring-account
slots. If qualified sleeves cannot satisfy both the product floors and that cap, the build applies an
explicit, recorded `product_coverage_fallback`: it admits the next eligible sleeve by global rank,
records the unmet floor or cap, and never silently labels the resulting coverage as balanced.

| Cadence | Scope | Work |
| --- | --- | --- |
| 500 ms | active source events | independent open/add/reduce/close and signal latency |
| 10 seconds | active customer risk | floating P/L, margin, loss allowance, expiry and timeout |
| 15 minutes | active + monitor + reserve, about 100 | dynamic score and effective weight |
| 1 hour | all-database light discovery | cached history plus latest one/four-hour state |
| Daily 05:15 Beijing | all eligible accounts | complete history factors, MDD, holding and base weights |

Daily rebuilding must evaluate all accounts meeting minimum activity criteria and must not stop after
finding a route quota. Hourly discovery cannot repeat the full 60-day history query. The population
limits above do not prohibit one selected client from contributing more than one product sleeve.

A candidate must rank in the active region twice, then pass ten minutes of shadow observation before
orders are allowed. A small decline reduces weight; two consecutive qualified-region failures stop
copying. Hard risk, exhausted loss allowance or severe delay sets effective weight to zero immediately.

## 6. Weight and allowance state

Daily active base weights total 100%. Effective weight is:

```text
baseWeight * intradayPerformance * delay * holdingRisk * lossAllowance
```

Reduction may be immediate. Recovery is capped at five percentage points per 15 minutes and ten per
hour. A sleeve cannot exceed 120% of its daily base weight or 20% of active-pool risk budget. Released
budget stays idle until a separate 30-minute rebalance confirms another sleeve's strength; it is not
immediately renormalized in volatile conditions.

The client's daily loss allowance is fixed from start-of-day base weight. Intraday profit or temporary
weight increases cannot raise it. A daily rebuild creates a new allowance only at the next trading day.

## 7. Tick cache and measured cost

`D:\risk\benchmark_copy_delay_ticks.py` is a performance-only tool. It refuses non-Demo servers and
labels output `factorReady=false`. On 2026-07-29, ACCMGlobal-Demo XAUUSD measurements were:

| Interval | Ticks | MT5 array | Read time | Replay |
| --- | ---: | ---: | ---: | ---: |
| 2026-07-28 00:00-01:00 UTC, initial read | 25,187 | 1.44 MiB | 1.51 s | 10k x 15: 0.012 s |
| 2026-07-28 UTC, terminal-cached | 496,783 | 28.43 MiB | 0.295 s | 100k x 15: 0.463 s |
| 2026-07-20 through 24 UTC, mixed cache | 2,330,385 | 133.35 MiB | 2.68 s | 100k x 15: 0.448 s |

Observed density extrapolates to roughly 28-36 million raw Tick records and 1.6-2.1 GiB for 60
calendar days in the MT5 structured dtype. These are cache-conditioned measurements, not a full
60-day cold-seed guarantee.

Production design therefore uses one shared Tick cache per Demo product, partitioned by UTC day.
Only `time_msc`, bid and ask are retained in a 24-byte NumPy memory-mappable record plus metadata,
coverage, source identity and checksum. At observed density the projected 60-day working set is
about 0.64-0.87 GiB before filesystem compression. The full seed streams one day at a time; routine
updates append only missing partitions. Account replay reads shared partitions in bounded trade
batches and never downloads Tick data per customer.

Before implementation acceptance, benchmark the actual selected-customer gold trades, record cold
seed and warm incremental p50/p95, peak RSS, cache coverage, endpoint alignment miss rate and
partition corruption recovery. Full daily build and one-hour discovery each receive a measured time
budget only after this real-trade benchmark.

## 8. Data contract and UI additions

The producer will add, without exposing private account keys: entry/exit/combined delay metrics,
actual P95 latency, signal budget and expiry counts; 20/60-day/current drawdown and coverage;
overnight/weekend/long-loss metrics; population/rank state; next eligible transition; and factor/gate
reason codes. The 8777 page will show these as account-product fields and distributions, with raw
source Position to Demo Ticket ownership unchanged.

## 9. Acceptance and rollout

1. Synthetic tests cover Tick chunk boundaries, stable ordering, same-millisecond Tick retention,
   quote gaps, buy/sell price sides, independent entry/exit delays and PF edge states.
2. Real-trade replay reconciles source executions, costs and no-delay P/L before delay scoring.
3. Cashflow-adjusted equity controls reconcile daily and intraday coverage without treating missing
   snapshots as clean.
4. Overnight/weekend fixtures use each source's verified platform clock.
5. Ranking tests cover two-pass entry/exit hysteresis, ten-minute shadow and idle released budget.
6. Offline replay and Shadow produce identical sleeve state and no cross-customer Ticket mutation.
7. Only after the feature document, API snapshots and Full verification describe implemented behavior
   may Demo Live authorization be reconsidered.
