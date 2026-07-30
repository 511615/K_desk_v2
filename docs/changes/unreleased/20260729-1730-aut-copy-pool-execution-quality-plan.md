---
change_id: 20260729-1730-aut-copy-pool-execution-quality-plan
features: ["AUT-POOL-001"]
change_type: design
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Execution-quality remediation plan

## Before and after

Before this record, the independent-execution change had no governed implementation plan for real-
trade Tick delay replay, cashflow-adjusted equity MDD, overnight/weekend quality or multi-cadence
ranking. An approved but not-yet-implemented plan now defines those workstreams, a 30 monitor plus
70 reserve ranking population and the required acceptance gates. Those counts are unique client
`account_key` counts: qualified `account x product` sleeves rank and are admitted independently,
while every client's loss allowance is aggregated at client level across its sleeves. Sleeve floors
protect product coverage, an initial 40% per-product unique-account cap prevents one product from
dominating the monitoring pool, and an explicit recorded fallback handles an infeasible floor/cap
allocation. The current feature behavior does not change until implementation and acceptance.

## Impact

ACCMGlobal-Demo XAUUSD benchmarks show that local vector replay is inexpensive relative to historical
Tick acquisition and storage. The design uses one daily-partitioned product cache shared by all
customers and prohibits per-customer Tick downloads. The benchmark is explicitly performance-only
and cannot produce DelayScore or customer eligibility.

There is no API, database, producer scheduling, order or UI runtime impact in this design-only change.

## Documentation updated

- `docs/plans/AUT-POOL-001-execution-quality-remediation.md` records the complete proposed model,
  performance evidence, data contract, rollout and acceptance matrix.
- `docs/plans/README.md` defines the non-authoritative status of plan documents.
- `docs/README.md` links approved future plans separately from current feature behavior.

## Verification

Governance validation must accept the plan/change record, and the existing AUT-POOL-001 current-state
contracts and Full suite must remain unchanged. Tick benchmark code is verified separately and its
output must continue to state `factorReady=false` until it consumes real customer trades.

## Deployment and rollback

No endpoint, database route, order behavior or MT state changes in this design-only record. Existing
independent Demo Live prohibition remains. Rollback removes the plan and benchmark artifact without
data migration.
