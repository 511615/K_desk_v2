# K_desk production ports and APIs

## Production services

| Service | Bind address | Port | Purpose |
| --- | --- | ---: | --- |
| Account workbench | `127.0.0.1` | `8777` | Main Vue UI, account APIs, ledger, analytics and task submission |
| K-line task center | `127.0.0.1` | `8766` | Statement upload, K-line task management and generated chart files |
| Background worker | no listening port | - | Persistent K-line, Toxic, push and rebate-discovery jobs |

Development ports `8877/8866` are reserved for isolated testing and are stopped after production cutover. Vite may use `5177` only during frontend development; production does not require Node.js or Vite.

## Account service (`8777`)

### Pages and health

- `GET /` - account risk workbench
- `GET /copy-pool` - read-only dynamic customer-pool and Demo execution monitor
- `GET /copy-pool/accounts/{alias}` - private server-side alias redirect to the compatible account detail route
- `GET /account/{login}` - account detail page
- `GET /health/live` - process liveness
- `GET /health/ready` - service and SQLite readiness
- `GET /api/meta` - version, profile and capability metadata

### Ledger and local data

- `GET /api/accounts`
- `GET /api/accounts/by-login/{login}/ledger`
- `POST /api/accounts/mark`
- `POST /api/accounts/mark-batch`
- `PUT /api/accounts/{record_id}`
- `DELETE /api/accounts/{record_id}`
- `GET /api/accounts/{record_id}/history`
- `GET|POST /api/quick-actions`
- `DELETE /api/quick-actions/{name}`
- `GET /download/problematic_accounts.xlsx`

### Account analytics

- `GET /api/accounts/by-login/{login}/detail`
- `GET /api/accounts/by-login/{login}/risk-panels`
- `GET /api/accounts/by-login/{login}/historical-funds` - full account-wide read-only replay of
  trade, balance, Credit and daily-anchor facts for the selected platform/server; external cashflow,
  internal transfer and compensation-style entries remain classified separately. MT5 backtrace does
  not query the unindexed daily view; it returns a current-account-calibrated balance/Credit replay with explicit snapshot
  coverage rather than failing the complete ledger response; intraday equity is not fabricated
- `GET /api/accounts/by-login/{login}/automation-analysis`
- `GET /api/accounts/by-login/{login}/relationship-network` - additive evidence-only relationship
  graph for same-CRM-user accounts, current-account IP observations, EA/route features, Copy and
  rebate facts; supports existing platform/server/symbol/time filters and returns partial coverage
  without risk scores or relationship-strength classifications
- `GET /api/accounts/by-login/{login}/copy-origins` - accepts optional `platform`, `server`,
  `symbol`, `start` and `end`; `start/end` filter by opening time and blank values mean full history
- `GET /api/accounts/by-login/{login}/copy-group-profit` - accepts the same filters, including the
  opening-time range for Signal trade and time-scoped rebate totals
- `GET /kuzu-demo` - isolated local Kuzu evidence-graph trial page; no legacy page behavior changes
- `GET /api/kuzu-demo/graph?depth=1|2|3` - bounded read-only traversal of the local Kuzu demo file
- `GET /api/accounts/by-login/{login}/ea-comment-profit` - member rows additively expose
  `expertIds`, `matchClue` and `matchClues`; groups expose `expertId` and `matchRule`. Conservative
  no-comment MT5 route groups additively expose `signatureType=expert-sequence`, `sharedExpertIds`
  and `expertSequence`; they remain excluded from `eaSummary`
- `GET /api/accounts/by-login/{login}/copy-report.xlsx` - CPT/Signal group and follower profit
  workbook; consumes exactly the same optional filters as the JSON endpoints
- `GET /api/accounts/by-login/{login}/ea-report.xlsx` - EA comment group and account profit workbook
- `GET /api/accounts/by-login/{login}/login-ips`
- `GET /api/accounts/by-login/{login}/orders`
- `GET /api/account-lookup`
- `GET /api/account-lookup-finance`
- `GET /api/account-logs`
- `GET /api/copy-pool/dashboard` - bounded local snapshot projection; pool rows expose the trading
  Login, platform/server, alias, normalized product, activity state, holding distribution,
  product/client/base/effective weights and detail link. Additive `clientRisks`, `copyPositions`,
  `ticketMappings` and `exposures` project customer-owned Demo execution without returning private
  composite keys or comments. Status and timeline rows additively expose `accountLogin`, identifying
  the Demo account that produced each equity sample. Source events and Demo order events remain compatible;
  additive `demoAccount` projects the pinned Login's account summary, actual open positions and a
  bounded recent MT5 Deal ledger. Position/Deal rows expose public Ticket, product, direction,
  volume, price, P/L and strategy-ownership fields, but never MT5 Comment, Magic or private source keys.
  `sourceCoverage` reports eleven logical routes, nine
  physical sources, build funnels, selected counts, freshness, latency and source errors. Pool rows
  additively expose realized P/L, floating P/L, dynamic evaluation, open position count, all-symbol
  gross lots, XAUUSD gross/net lots, hedge ratio, oldest-open age, floating-loss ratio,
  margin/equity and the build-time open-risk multiplier. `/account/{login}` does not fetch or embed
  this dashboard; copy-pool state is shown only on `/copy-pool`.
- `PUT /api/copy-pool/controls` - loopback-only, strictly validated manual control update for
  automatic new exposure, equity-floor, daily-loss and cycle-loss gates plus one-shot recovery
  shadow. The response and dashboard expose only switch state, revision and update metadata; the
  producer consumes the atomic local file and audit log without an MT Manager operation.
- The same dashboard additively exposes `currentCopies`, with one row per currently owned Demo
  Ticket. Each row contains the real source Login, server/platform, product/direction, source
  Position, source and Demo lots/open evidence, entry delay, exact source-position floating P/L,
  Demo source-comment realized/floating/total P/L and the compatible account-detail link. Missing
  legacy per-position P/L remains `null`; account-level profit is never allocated to a Ticket.
- `GET /api/copy-pool/dashboard` additively projects v6 execution-quality and product-fallback fields: per-sleeve pool
  tier, factor readiness/base score/reason codes, delay compatibility fields, drawdown
  coverage, holding/overnight/weekend quality, and mapped dynamic sleeve/scheduler state. Fields are
  snapshot-derived only; unknown private sleeve keys are omitted rather than returned. V0.1 returns
  `historicalDelayFactorEnabled=false` and `delayFactorStatus=deferred_v0_1`; delay compatibility
  values are not scoring or hard-gate evidence.
- The same pool rows additively expose the v7 `factorModel`, hard-filtered percentile scores for
  cost-adjusted profit, recent cost-adjusted profit and cost coverage, plus minimum-lot normalized
  five/20-day copied P/L, estimated cost, after-cost P/L, per-trade values and coverage evidence.
  Existing fields and URLs remain compatible.
- Pool `effectiveWeight`, status `activeWeights`, product `activeWeight` and `activeCopyClients`
  represent final executable dynamic sleeves rather than source-quality weights. Additive
  `riskManagedClients` separately reports client risk-ledger membership.
- `sourceCoverage` additively exposes actual monitor/reserve/active counts, selected and active
  products, and whether sparse product coverage required a product-weight cap fallback.
- The same response additively projects hourly score, one/four-hour net P/L, current comprehensive
  20-day P/L, hourly hard/activity eligibility and bounded hourly-discovery coverage. K_desk reads
  these from local snapshots and never runs discovery queries itself.
- `GET /api/rebate-churning/accounts/{account}` - omitting `start` and `end` returns full verified
  history for every routed account in the displayed tree and sets `query.fullHistory=true`
- `GET /api/rebate-churning/ibs/{environment}/{ib_id}` - complete expandable recipient-IB tree
- `GET /api/trades/summary`
- `GET /api/hierarchy-products` - products from every configured route-backed physical source,
  including the independent DBG MT5 Live2 schema
- `GET /api/hierarchy-net-deposit` - hierarchy finance by exact CRM/server route; supports existing
  `gb:`/`cn:` and additive `dbg-cn:`/`dbg-vn:` CRM user selectors

### Persistent jobs

- `POST /api/kline/generate-from-db`
- `GET /api/kline/jobs/{job_id}`
- `GET /api/toxic/check-types`
- `POST /api/accounts/by-login/{login}/toxic-checks`
- `GET /api/toxic/jobs/{job_id}`
  - `internal_lock_arbitrage` additively returns `evidence.hedgeQuery` and top-level result
    `internalLock`, containing opposite-only synchronized open/close account and order evidence plus
    physical-source coverage; opposite pairs require at least 80% lot similarity
- `POST /api/push-discovery/start`
- `GET /api/push-discovery/active` - current running discovery job, otherwise latest queued job,
  used to restore workbench progress after navigation
- `GET /api/push-discovery/jobs/{job_id}` - completed discovery results include successful
  `results` plus additive `failureTotal`, `failureSummary` and `failures` fields for non-fatal
  source/account failures
- `POST /api/rebate-churning/scans` - submit a durable confirmed-rebate scan (default 7, maximum 31 days)
- `GET /api/rebate-churning/scans/{job_id}` - progress, summaries, IB ranking and partial failures
- `POST /api/bonus-arbitrage/scans` - submit a durable cross-platform positive-Credit candidate scan
- `GET /api/bonus-arbitrage/scans/active` - restore the active bonus-arbitrage discovery job
- `GET /api/bonus-arbitrage/scans/{job_id}` - progress, concise account ranking including additive
  current-margin/deposit priority fields, cycle-minimum margin level/equity/used-margin plus concurrent
  standard-lot/order evidence, visible
  suspected-hedge order pairs, and partial candidate/ranking/deep failures
- `POST /api/position-risk/scans` - submit a durable heavy-position timing scan (default 30, maximum
  90 days); additively accepts nullable non-negative `minPositionPercent`, `minLots` and `minProfit`
- `GET /api/position-risk/scans/active` - restore the active heavy-position timing scan
- `GET /api/position-risk/scans/{job_id}` - progress, applied optional filters, leverage/exposure ranking, additive peak-order,
  estimated-margin amount/ratio/level, penetration gaps, cross-platform synchronized open/close order
  pairs, peer-source coverage and partial failures
- `POST /api/jobs/{job_id}/cancel`
- `GET /chart-file/{name}`

## K-line service (`8766`)

- `GET /` - K-line task center
- `GET /health/live`
- `GET /health/ready`
- `GET /api/recent`
- `POST /api/uploads`
- `POST /api/jobs/{job_id}/generate`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `GET /output/{name}`

K-line job `result` keeps the existing `chart`, `status` and `message` fields and additively exposes
`partial`, accepted `symbols`, structured `failures`, read-only `quoteSources` and an optional
timeline coverage summary for generated database charts. Existing request
parameters, output names, `8777/8766` ports, iframe previews and direct chart links are unchanged.

## Operations

- Start production: `pwsh -File D:\risk\K_desk_v2\scripts\start_prod.ps1`
- Stop production: `pwsh -File D:\risk\K_desk_v2\scripts\stop_prod.ps1`
- Health check: `pwsh -File D:\risk\K_desk_v2\scripts\health_check_prod.ps1`
- Roll back: `pwsh -File D:\risk\K_desk_v2\scripts\rollback_to_legacy.ps1 -ConfirmRollback ROLLBACK-KDESK`

All services bind only to localhost. MySQL, MT4 and MT5 integrations are outbound read-only data providers and do not add a K_desk listening port.
