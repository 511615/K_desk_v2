---
change_id: 20260729-1900-aut-copy-pool-execution-quality-implementation
features: ["AUT-POOL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Implement execution-quality factors and dynamic schedules

## Before and after

Before this change, the producer's accepted pool did not have an executable real-trade Tick delay
factor, cashflow-adjusted floating-equity drawdown, holding-path quality or a consumed hourly
discovery schedule. Fifteen-minute ranking repeated static daily rows, reserve clients had no
working promotion path and restart could approve an offline increase on an already mapped source
Position.

The producer now builds all supported account-product sleeves across eleven logical routes with
real entry/exit Tick replay, 20/60-day/current MDD, overnight/weekend/long-loss evidence and the
fixed 20/15/15/10/20/10/10 factor model. Thirty unique clients form the monitor population and up
to seventy form reserve, with product floors, a 40% product cap and explicit fallback evidence.
Risk runs every 10 seconds, current-range ranking every 15 minutes, bounded factor-ready-universe
discovery every hour and the complete build at 05:15 Beijing.

Hourly discovery reads only current-session one/four-hour P/L, profiles and open positions. It
cannot waive a daily historical hard gate. New sleeves require two active-zone ranks and ten healthy
shadow minutes. Current source positions are monitor-only; retiring owners remain internally
available for same-day Ticket/P&L attribution. Restart accepts missed reductions and closes but
never chases an offline increase or reversal. Daily rebuild resets the old-position boundary while
preserving an execution-suspended sleeve state.

## Impact

`GET /api/copy-pool/dashboard` remains read-only and backward compatible. Pool rows add hourly
score, one/four-hour net P/L, current comprehensive 20-day P/L and hourly hard/activity eligibility.
Source coverage adds bounded hourly-discovery counts and timestamps. The dark `8777` dashboard
shows historical-to-hourly score movement, recent P/L and the current comprehensive-profit gate;
account links and source Position-to-Demo Ticket detail remain unchanged.

Remote AC/DBG MySQL, ACCMGlobal-Demo quotes and MT state remain read-only during build and preflight.
K_desk reads local snapshots only. No MT4/MT5 Manager mutation path was added. Producer, Shadow and
Demo Live remain stopped until the full read-only preflight and Shadow acceptance gates pass.

## Verification

Focused producer tests cover Tick replay, factor readiness, equity reconstruction, unique-client
ranking, hourly schedule consumption, pool rotation, offline increase suppression and independent
Ticket behavior. K_desk tests cover the additive snapshot projection; frontend unit tests and the
production Vue build cover localization and rendering. Fast and Full governance verification are
required before handoff.

## Documentation updated

- `docs/features/automation/dynamic-copy-pool-monitor.md` records current factor, population,
  schedule, restart and UI behavior.
- `docs/BUSINESS_RULES.md`, `docs/DATA_AND_ROUTING.md`, `docs/PORTS_AND_APIS.md`,
  `docs/OPERATIONS.md` and `docs/TEST_STRATEGY.md` record their respective authorities.
- `docs/plans/AUT-POOL-001-execution-quality-remediation.md` records that implementation is present
  while read-only preflight and Shadow acceptance remain pending.

## Deployment and rollback

Stop the external producer, restore the previous producer files and remove the additive public
columns. The existing dashboard tolerates their absence. No database, SQLite or MT migration is
required. Never roll back by editing account, trade or Manager state.
