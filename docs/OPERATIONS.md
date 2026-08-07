# Operations runbook

## Services

| Process | Production | Development |
| --- | --- | --- |
| Account web | `127.0.0.1:8777` | `127.0.0.1:8877` |
| K-line web | `127.0.0.1:8766` | `127.0.0.1:8866` |
| Workers | one interactive Worker and two discovery Workers (push, rebate, bonus and position-risk discovery) | isolated dev queues |

Use `scripts/start_prod.ps1`, `stop_prod.ps1` and `health_check_prod.ps1`. The stop script verifies
port ownership before terminating a process. Production logs are under `runtime/prod/logs` and must
not contain credentials or sensitive account fields.
The default production start launches two discovery Workers so a long scan cannot serialize all
platform discovery tasks. `start_prod.ps1 -DiscoveryWorkers 1` is available for a constrained host.
The production health check reports both Worker queues in addition to the two HTTP services; a
missing Worker is a failed readiness result even when `8777` is still serving pages.
`scripts/start_prod.ps1 -AccountOnly` starts only the main account service on 8777 and intentionally
does not start 8766 or production workers; use it for the dedicated copy-pool deployment.

Production startup is fail-closed before migrations or process creation: the checkout must be on
`main`, `git status --porcelain` must be empty and `HEAD` must resolve. The launcher copies the
already verified `frontend/dist` into `runtime/prod/frontend-releases/<full-git-sha>` through a
unique staging directory, then sets `KDESK_FRONTEND_DIST` to that immutable release directory.
The running 8777 process never serves a development worktree's mutable `frontend/dist`; rebuilding
or switching a development branch therefore cannot replace the deployed UI.

The Vue index is served with `no-store`. Open workbench pages compare the deployed hashed entry
asset every 15 seconds and on focus, then reload when a deployment changes it; persistent jobs are
restored from browser storage or the active-job API.

The `动态跟单` page reads local copier snapshots from
`KDESK_COPY_POOL_OUTPUT_DIR`; when unset it uses
`<KDESK_LEGACY_OUTPUT>/copy_live_demo_capital10k`. The snapshot producer and K_desk web service are
independent processes. A source age above five seconds is displayed as stale. Operators diagnose
the producer and file permissions separately; K_desk must not restart the copier or place a repair
order. Keep `runtime_state_private.json` and `client_routes_private.json` local and out of logs.

If `events_public.csv` continues advancing while `status.json` stops, inspect the Producer log for
terminal identity changes or `AutoTrading disabled` errors. The Producer must remain the only copy
process. After the heartbeat fix, a failed terminal/ledger sample preserves the last verified Demo
account projection and advances `status.json` with an explicit error; do not delete snapshots or
start a second Producer. When AutoTrading is disabled during live operation, the phase is
`armed_waiting_autotrading`, no new broker reconciliation requests are sent, and polling continues.
Restore terminal permission on the already-selected Demo session, then verify status freshness and
account identity before allowing live execution to resume.

The governed production producer entry is
`services\copy_pool_runtime\run_copy_demo_live.ps1` in the checked-out production worktree. It loads
both AC and DBG Workbench read-only credentials into the process environment, starts the sibling
`copy_trading_multi_demo.py`, and restores the environment on exit. The launcher adds its own
directory and `D:\risk\pydeps` to `PYTHONPATH`; Terminal, Input and Output defaults remain under
`D:\risk`. This keeps the Producer code selected by the checked-out Git worktree while preserving
the existing external runtime resources. `-PreflightOnly
-ForceRebuild -Mode Shadow` performs a complete eleven-route build without initializing MT5 or
sending an order. A normal same-day restart restores the versioned accepted pool, then reads every
selected source's current positions and independent high-water mark before leaving shadow. Daily
rebuild failure keeps the Demo strategy flat and retries no more than once per minute. Existing
source positions are monitor-only; the producer never opens from an old target. Persisted source-to-
Demo Ticket ownership must exactly match current strategy Tickets before startup. Any unknown or
missing Ticket is an execution hard stop requiring operator review.
The launcher passes the explicitly approved Demo Login through `-DemoLogin` (currently `33304642`).
After MT5 IPC initialization, the Producer uses the portable terminal's saved account session to
select that Login on `ACCMGlobal-Demo` if another account is active, then verifies the exact Login,
Demo trade mode, hedging mode and connection before pinning it. The selection check tolerates the
terminal's asynchronous reconnect only by requiring three consecutive matching samples within ten
seconds; it never treats an intervening Live sample as approved. It does not read or persist an MT5
password. Selection failure or an unstable/mismatched post-selection identity aborts startup. Because MT5 may
disable AutoTrading after an account change, the Producer remains unable to send orders until the
operator enables AutoTrading once on the already selected Demo session; do not start a separate MT5
Python probe afterward. If later IPC reads return another Login/server, the Producer rejects the
sample and performs no sizing, status write or order action for that loop. The previous valid
snapshot then becomes stale rather than displaying another account's equity. Adding the identity
column rotates the old status timeline to a timestamped archive on the first upgraded startup.
The Producer also atomically refreshes `demo_account_public.json` every five seconds after the same
Login/server identity checks. Current positions come from the live terminal; the bounded 30-day,
200-Deal history query is cached for ten seconds. A failed or crossed-account sample cannot replace
the last valid public ledger. The 8777 process never initializes MT5 to serve this panel.
The Producer may self-recover a Ticket that was filled immediately before a process interruption
only when its retained 16-character comment and product uniquely match one persisted source-position
owner. It records the recovered ownership before resuming reconciliation. Ambiguous, foreign or
unmatched Tickets are never adopted and continue to require operator review.
After this recovery pass, a persisted open source Position with no actual Demo child Ticket is
retained as `restart_without_demo_ticket` monitor-only state until the source closes. It is not an
ownership mismatch and must not be repaired by manually relaunching or forcing a replacement order.
Positions with recovered or existing child Tickets remain under reduction, close and risk control.
The accepted cache is rejected unless metadata, route counts and source-health rows exactly cover
all configured eleven logical routes and nine physical sources; an older or partial cache forces a
new full preflight instead of entering Demo execution.
When a valid cache is restored, its accepted build day advances the daily scheduler guard before the
first loop and a fresh status snapshot is published immediately. This prevents a restart after 05:15
from launching a duplicate full build while the dashboard continues to show stale prior-day state.
The accepted cache producer is `copy-pool-multisource-v9-carry-risk` with factor schema
`cost-profit-recent-coverage-carry-v3`. A same-trading-day v6, v7 or v8 cache may be upgraded in
place only when its metadata, coverage and full private universe prove exact 11/11 logical-route,
9/9 physical-source and complete carry-risk evidence. A legacy universe without carry-risk evidence
forces a complete rebuild rather than treating missing evidence as safe. The upgrade preserves all
existing hard rejections and recomputes proportional positive-score weights without the retired
`0.55` activity floor; partial, older-day or malformed snapshots also force a complete rebuild. The
next 05:15 schedule always runs the complete v9 database build. Same-day migration rebases dynamic sleeve weights but restores
and validates persisted independent Demo Ticket ownership exactly like a normal restart. V0.1 complete builds do not
load historical Tick partitions. They still require drawdown and holding-quality gates in addition to
account-product selection, complete open-position risk or independent execution inputs. Bootstrap
and each ten-second refresh must read
complete selected-account floating P/L and position risk before weights are accepted. A partial-
source refresh is a runtime error and continues to block new exposure through source health.
The producer consumes four persisted schedules: client risk every 10 seconds, current-range rank
every 15 minutes, accepted-universe discovery every hour and a complete rebuild at 05:15 Beijing.
Hourly discovery reads only the daily factor-ready cache plus bounded session facts. A failed
discovery leaves the last accepted pool in place and retries no faster than once per minute. A
membership change seeds current source positions as monitor-only, retains same-day retiring Ticket
owners for attribution and never replays an offline source increase.
Successful hourly membership is persisted to the accepted same-day snapshot. A restart restores
that latest membership. If an older snapshot lacks hourly evidence, those values remain unknown and
the scheduler runs a bounded discovery immediately instead of publishing fabricated zeros.

`-AllowDemoMinLotOverride` is an explicit `ACCMGlobal-Demo`/`StagedLive` experiment switch. It may
open the minimum copied lot for each eligible independent source Position when whole-portfolio
stress, the product-direction cluster limit and margin still fit. It does not authorize trading by
itself: `-EnableLiveTrading`, terminal AutoTrading, healthy operational gates and a new
post-activation source signal remain mandatory.
For an active client in this exact mode, initialization floors the client's loss allowance at 20%
of the 1.5% cycle budget. This prevents a minimum-lot Ticket from being closed by a sub-dollar
weight-proportional allowance before the source strategy can be evaluated. Zero-weight clients and
all ordinary modes retain the normal weight-proportional allowance.
The owning source Position retains that minimum lot across reconciliation. A rolling 60-second guard
permits at most eight open requests; a ninth request enters execution hard stop and flattens strategy
Tickets. Investigate and deploy a tested fix before restarting rather than repeatedly relaunching an
unchanged Producer.
Manual risk controls are written only through the loopback 8777 endpoint and consumed from
`manual_controls.json` in the Producer output directory. Every update appends
`manual_controls_audit.jsonl`. Use the separate resume action after changing a gate; it starts
recovery shadow and requires the normal operational gates before live execution. Deleting or
hand-editing the file is not an approved reset procedure.
MT5 incremental polling coalesces every poll batch to the final source Position before execution. A
`batch_terminal_flat` event means the source opened and fully closed before the Producer could act;
no Demo Ticket is expected. If an open and immediate close order pair appears instead, stop the
Producer, keep 8777 running, verify the Demo is flat and deploy the batch-coalescing fix before retry.
Pending terminal transitions are private state. A broker/runtime failure leaves the failed Position
pending while independent sibling transitions continue and later events coalesce. Restart replays
only reductions/closes; unfilled opens become monitor-only and a reversal keeps only its closing leg.
Malformed pending state hard-stops startup. Do not delete private state to bypass a failure.
If an MT4 order appears materially later than the five-second/P25 entry budget, stop only the
Producer after the Demo is flat, preserve private state and inspect the physical source-time mapping
plus original entry timestamp. Reconciliation must report `signal_expired_no_copy` and must not
reopen that Position after the entry deadline. Keep 8777 running during repair.
After deploying an entry-deadline repair, reject the release if any first entry, addition or
opposite reversal leg is opened after its persisted risk-signal deadline. Verify that an expired
reversal may close old risk without creating the new leg. The dashboard `currentCopies` table must
show only actual owned Demo Tickets; source-position and Demo-comment P/L refresh on the existing
ten-second risk cycle and legacy unavailable values remain explicit rather than zero.
Daily MT5 holding history starts in five-day windows so routine startup does not repeatedly pay a
30-second timeout before subdividing. A slow window reconnects and splits Login, then time for a
remaining singleton. The build must produce complete evidence or fail explicitly; do not reuse
yesterday's pool or disable the holding gate to bypass a slow source.
Factor-history daily reads stop at the bounded 61-day lower limit and must never issue progressive
pre-window anchor lookups. Risk history, holding statistics and factor history may each load up to
four physical sources concurrently, but a physical source remains serial within each stage. Inspect
`build_stage_seconds` in accepted coverage before changing
batch sizes or concurrency; a failed source must prevent publication rather than produce a partial pool.

Normal entry activation is direct: a fresh hard/activity/minimum-lot-qualified sleeve in the active
zone enters `ACTIVE` on its first 15-minute ranking and receives its current live base weight. There
is no ordinary entry observation period. `-DemoFastActivation` remains accepted only as a
compatibility/status flag. An already persisted legacy `ENTRY_SHADOW` is promoted on its next
qualified ranking. Operational gates, terminal permission, ownership and factor qualification
remain mandatory; loss-recovery shadows are separate and are not bypassed.
The independent 25% client-risk utilization ceiling remains enabled. If direct or gradual effective
weights exceed it, the Producer scales every positive sleeve by the same ratio instead of removing
the budget excess from low-ranked sleeves first.
The status snapshot records requested and effective state. This option does not imply
`-EnableLiveTrading` and does not bypass any operational, ownership, risk or terminal gate.

The legacy net-target Live process must remain stopped. Initial deployment may run only `Shadow`
without `-EnableLiveTrading`; it may start the existing 8777 service but no additional web port.
Before Demo authorization, offline event replay must prove old-position suppression, exact A/B Ticket isolation,
partial-close/reverse order, restart mapping recovery, gross-position outage flatten and equality
between shadow and offline state. K_desk never starts, stops or repairs the producer.

## Change verification

Run `scripts/verify_change.ps1` with `Fast`, `Full` or `Release`. Full is required before production
deployment. Release additionally requires explicitly enabled read-only contract checks and live
health acceptance.

Install repository hooks once with `scripts/install_git_hooks.ps1`. Pre-commit runs Fast and
pre-push runs Full. Production remains checked out on `main`. Normal changes are made in a separate
`develop` worktree, verified there, merged into `main`, and deployed by a controlled restart. Do not
edit feature or Producer code in the running production worktree.

The production checkout must be the worktree currently on `main`; on this host that checkout is
`D:\risk\K_desk_v2_main`. `D:\risk\K_desk_v2` is an older feature worktree and is not a valid
production launcher while it remains off `main`. The development checkout is
`D:\risk\K_desk_v2_dev` on `develop`. A normal promotion requires a clean development worktree,
`verify_change.ps1 -Mode Full`, a committed and pushed `develop`, then a non-interactive merge into
`main`, another Full verification from the production checkout and a pushed `main`. Only after the
second verification may the 8777 account service or copy-pool Producer be restarted from `main`.
Runtime snapshots, credentials, terminals and logs stay outside both Git histories.

## Release sequence

1. Require a clean, recorded worktree and matching `2.x` version metadata.
2. Run Release verification and build the Vue assets.
3. Copy SQLite databases and compatibility workbook to a timestamped local rollback directory.
4. Stop only verified K_desk processes, run Alembic, start web/worker processes.
5. Check both readiness endpoints and representative account/legacy-page contracts.
6. On failure, stop the new processes, restore the snapshot and restart the prior version.

Use `scripts/release_prod.ps1 -Version <VERSION>`. It requires Release verification, creates
consistent SQLite backups with integrity checks, records a manifest, and attempts automatic data
restore/startup if migration or health acceptance fails.

GitHub stores code only. Local release snapshots protect deployment rollback but are not disaster
recovery for disk loss.

## Incident triage

Check readiness, process ownership, latest error logs, SQLite free space/lock state, remote provider
availability and job events in that order. Do not retry remote calls indefinitely. Never use an MT
Manager write operation as a recovery action.

## K-line quote sources

Production K-line jobs use the dedicated read-only quote Terminal at
`D:\risk\mt5_backtest_terminal\terminal64.exe` by default. Set the user environment variable
`KDESK_KLINE_QUOTE_TERMINAL` to use another dedicated `terminal64.exe`; `start_prod.ps1` validates
the path before launching services. Do not point it to an operator's interactive Terminal. A source
that returns MT5 `IPC timeout` is unavailable and must be replaced or restarted separately; K_desk
does not perform any account or trade operation during quote access.

Set `KDESK_KLINE_QUOTE_SOURCES` to a local JSON based on
`config/kline_quote_sources.example.json`. Keep it credential-free. Routes list same-source providers
before explicitly allowed fallbacks. Deleting the variable retains the legacy single Terminal only
as the universal read-only fallback for uploaded reports and server-routed database jobs. Database
jobs apply the stricter fallback endpoint-validation gate so a divergent Terminal feed cannot
silently produce a misaligned chart.
Provider-qualified caches prevent cross-provider reuse and old cache files remain readable. Rollback
restores the prior code/config only; SQLite, historical charts and direct links require no migration.
