---
change_id: 20260806-1115-aut-copy-pool-heartbeat-and-deal-semantics
features: ["AUT-POOL-001"]
title: Copy-pool heartbeat recovery and Demo deal realization semantics
change_type: bug-fix
status: unreleased
compatibility: compatible
---

The multi-source Producer now keeps publishing runtime status after a transient MT5 identity,
IPC, or Demo ledger snapshot failure. It retains the last verified account fields, records the
current error, and continues persistence/retry on later cycles. When AutoTrading falls back to
disabled after live activation, the Producer enters `armed_waiting_autotrading` and skips broker
reconciliation so repeated failed order requests cannot stall the dashboard or add duplicate risk.

The Demo history table now derives realization state by `positionId`: opening Deals are paired with
all matching closing Deals, mapped to a current open Position when present, or marked as lacking
realization evidence. This removes the misleading interpretation that an opening Deal's zero
realized P/L is the account's final result.

## Before and after

Previously one failed execution cycle could leave `status.json` frozen while source events kept
arriving, and a disabled terminal repeatedly retried the same broker operation. Opening Deals also
showed `0.00` without saying whether their Position remained open or had already closed. Status now
keeps advancing with explicit failure evidence, broker reconciliation pauses with AutoTrading, and
Deal rows report realization state using Position evidence.

## Impact

This changes Producer failure recovery and the read-only Demo ledger presentation. It does not alter
pool selection, sizing, remote database data, MT Manager state, or public endpoint compatibility.

## Documentation updated

- `docs/features/automation/dynamic-copy-pool-monitor.md`
- `docs/OPERATIONS.md`

## Deployment and rollback

Deploy by promoting the verified develop commit to main and restarting only the single Producer from
main without `-ForceRebuild`; 8777 remains running. Rollback stops that Producer, restores the prior
main revision and starts one Producer from the prior revision. Runtime snapshots remain compatible.

## Verification

- Producer regression tests cover permission fallback and heartbeat publication after ledger failure.
- Copy-pool page tests cover closed, open, and evidence-missing opening Deals plus closing Deals.
- No MT4/MT5 Manager operation was performed.
