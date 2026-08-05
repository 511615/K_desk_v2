---
change_id: 20260805-1058-aut-copy-pool-beijing-time
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Standardize copy-pool time on Beijing time

## Before and after

The copy-pool page parsed API timestamps correctly but formatted them in the browser's local time
zone. Holding age and shadow countdown also called the system clock separately from the shared header
clock. The page therefore did not guarantee one explicit time zone and one dynamic clock source.

All wall-clock values now pass through one `Asia/Shanghai` formatter. The visible current clocks,
holding ages and shadow countdown use the same reactive runtime clock, while historical rows retain
their real event instant. Time-bearing headings identify Beijing time explicitly.

## Impact

This is a frontend presentation change. API timestamps, Producer files, source normalization, trading
state, risk gates and Demo orders are unchanged.

## Verification

Dedicated formatter tests cover UTC-to-Beijing conversion, existing `+08:00` instants and invalid
values. The component regression verifies the shared clock and a UTC Demo Deal rendered in Beijing
time. Existing copy-pool interaction and ledger tests remain green.

## Documentation updated

Updated AUT-POOL-001 with the centralized Beijing formatter and single reactive runtime-clock rule.

## Deployment and rollback

Deploy by rebuilding the frontend and restarting only 8777. Rollback removes the formatter and restores
browser-local rendering; Producer and Demo execution remain running in either direction.
