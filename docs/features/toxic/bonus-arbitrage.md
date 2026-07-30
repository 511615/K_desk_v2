---
feature_id: TOX-BONUS-001
title: Bonus-arbitrage cycle detection
module: toxic
status: active
apis: ["GET /api/toxic/check-types", "POST /api/accounts/by-login/{login}/toxic-checks", "GET /api/toxic/jobs/{job_id}"]
code: ["src/kdesk/domain/bonus_arbitrage.py", "src/kdesk/application/bonus_arbitrage.py", "src/kdesk/infrastructure/bonus_arbitrage.py", "src/kdesk/worker/runner.py"]
tests: ["tests/test_bonus_arbitrage.py", "tests/test_worker.py"]
depends_on: ["JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Bonus-arbitrage cycle detection

## Purpose and user entry

Detect historical abuse of promotional credit from the existing Toxic `赠金套利` option. The
detector reconstructs funded credit cycles even when the current Credit value is zero and explains
the funding, trading, margin pressure, withdrawal or transfer, credit-removal and related-account evidence.

## UI and behavior

The existing account Toxic dialog remains the entry point. A result shows the strongest cycle in
the summary and returns up to ten structured evidence cycles with event IDs, trade IDs, amounts,
profit, attempted and completed extraction, the full-cycle minimum margin level, equity, used margin,
concurrent standard lots, its exact time and up to 50 orders that formed that point, open-position counts,
historical worst funded loss, negative-balance reset events, current negative balance/equity,
timing, related accounts and opposing-order matches.
Current Credit is display context only and cannot clear or establish historical suspicion.

## API contract

No endpoint or request field changes. The `bonus_arbitrage` result preserves the common Toxic
fields and adds an `evidence.cycles` object plus source metadata. Existing clients that only read
score, level, summary, metrics and evidence order IDs remain compatible.

## Data, routing and read-only constraints

The requested platform and server identify the account through CRM `(schema, server code, login)`;
the numeric login alone is not a route. DBG MT5 Live2 resolves through `crm_vn` code 5 to
`crm_vn_mt5_live2`; code 2 remains a separate `mt5_export_new` route. The adapter reads MT5 deal actions and executions or MT4
balance/credit rows and market trades. Opening-only MT5 positions and MT4 sentinel open positions
remain in the normalized trade set so prevention does not wait for a close. Requested windows include a seven-day funding boundary;
unbounded account checks use registration history capped at 400 days. Same-CRM-user accounts are
read only as possible coordination evidence. All queries use indexed login/time or CRM identity
predicates. No MT, CRM or trade state is changed.

Related-account order matching indexes normalized symbol, opposite direction and parsed open time.
Only trades inside the documented five-second synchronization window are compared, while one-to-one
consumption, closest-time priority and lot-similarity rules remain unchanged. This prevents large
same-user histories from degrading into all-pairs comparisons.
Within one platform scan, account mappings, current profiles, same-user families and identical
bounded history reads are reused through a thread-safe, 64-history bounded cache. The cache is
discarded with the scan and never extends an account's registration/history boundary.

MT5 executions retain Price and ContractSize, MT4 trades retain open/close price, and both profiles
retain leverage plus current Margin/MarginLevel. Cent/USC scaling applies to monetary amounts only;
standard lots stay unscaled. MT5 `Action=3` and MT4 `CMD=7` credit movements are separated into initial grants, temporary
restores and removals. Cash deposits, withdrawals, withdrawal reversals, resets and internal
transfers remain distinct. Confirmed Cent/USC monetary amounts use the documented `0.01` scale;
standard lots remain unchanged.

## Business rules and units

A cycle begins with confirmed promotional credit paired to cash funding. It remains active while
the historical credit balance remains active; it is not split at a fixed number of hours or days.
The score combines funding confirmation (10), closure and extraction (30), trading economics or
sacrifice (35), related-account coordination (15), and repeated cycles (up to 10).

The main positive chain is cash plus credit, profitable trading, matching withdrawal or transfer,
and credit removal. Reversed withdrawal requests remain evidence but are labelled attempted rather
than completed extraction. A high-credit, high-return, high-win-rate cycle with removed Credit but
no extraction is capped at warning. Historical funded loss is evaluated independently: consuming
at least 75% of cash plus Credit reaches warning, while a confirmed negative-balance reset, a
cumulative closed trading loss reaching 100% of cash plus Credit, or a currently negative balance
or equity reaches at least severe. Later profit, deposit or reset entries cannot erase the earlier
lowest point. Same-timestamp closes are netted before the lowest point is evaluated so row ordering
cannot manufacture a temporary breach. A recovered near-breach that later forms a completed
extraction loop keeps the stronger extraction conclusion; the unpaired-sacrifice cap applies only
when no extraction loop exists. The presence of Credit, ordinary volume, profit, loss or a related
account alone never establishes abuse.

Prevention does not require extraction. After the inclusive 20% Credit/cash eligibility gate, a cycle
enters the heavy-position path when its lowest margin level anywhere in the active Credit cycle is at
or below 200%. Margin level uses `equity / used margin * 100%`; lower values mean fuller positions and
greater liquidation risk, and values at or below 100% are labelled extreme pressure. Historical used
margin is reconstructed from opening price, contract size and leverage while equity is reversed from
the current account and loaded ledger; because historical floating P/L snapshots are unavailable, the
result labels these values as estimates. A current active state prefers actual Equity and Margin. This
path reaches at least high risk (75) without a withdrawal or visible opposing leg. At least 40% visible opposite
synchronized lot coverage raises confidence and strengthens the evidence explanation, but does not
change whether the account is flagged or its preventive-path score. The result states when an
external hedge remains unverified.

Minimum-margin evidence incrementally replays every open, close and funding event for the complete
Credit cycle. The result records the first lowest timestamp, equity, used margin, concurrent standard
lots, total concurrent order count and up to 50 exact order/position rows. Opposite synchronization remains suspected hedge evidence,
not a confirmed hedge: it requires the same normalized symbol, opposite direction, opening within
five seconds and at least 70% lot similarity. Absence of a visible pair does not lower risk.

Every positive path has a hard funding requirement: promotional Credit must be at least 20% of the
paired cash deposit in that cycle. Ratios are evaluated with numeric boundary tolerance, so an
exact 20% promotion qualifies. A below-threshold cycle remains visible as evidence but cannot be an
extractor, locked-profit or sacrifice cycle, cannot contribute to repeated-extractor escalation and
is capped at 39 (`无明显风险`) regardless of extraction or peer evidence. The result states the
required and observed ratios explicitly.

Scores 40, 60, 75 and 90 map to concern, warning, high and severe. Every result states that missing
promotion terms prevent an automated policy-violation finding.

## Loading, empty and failure behavior

The durable Toxic job reports a historical bonus-cycle stage after legacy order checks. Missing
bonus grants returns an explicit evidence limitation. Route or read failures replace only the
bonus result with `证据不可用`; they do not discard other selected Toxic results.

## Code and dependencies

Pure cycle construction and scoring are in domain code. The application service owns the use case,
the infrastructure adapter owns read-only legacy-routed SQL, and the persistent worker replaces the
old trade-only placeholder result before job completion.

## Tests and acceptance

Tests cover complete profit extraction, the inclusive 20% boundary, 10% and 18.18% hard-gate
rejection, low-ratio breach rejection, preventive bonus-cycle heavy-position risk with balanced or
one-way orders, exact minimum-margin timestamp/order membership, confidence-only visible synchronization,
light and low-ratio counterexamples, late-cycle eligibility, current
MT4/MT5 position retention, negative-balance resets, recovered historical breaches, current
negative balance/equity, 75% near-breach warning, same-time close netting, repeated cycles,
one-to-one peer-match parity, linearithmic large-history performance, Cent lot preservation and worker result replacement.
Read-only validation uses the `赠金套利` sheet in `用户画像.xlsx` and an unlabeled same-month
promotional-credit cohort as a false-positive pressure test.

## Compatibility and deprecation

The `bonus_arbitrage` type ID, Toxic endpoints, job persistence and other detector results are
unchanged. The historical cycle result replaces the previous current-Credit placeholder score.
