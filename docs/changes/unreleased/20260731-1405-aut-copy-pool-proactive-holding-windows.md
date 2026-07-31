---
change_id: 20260731-1405-aut-copy-pool-proactive-holding-windows
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Start MT5 holding reads with bounded windows

## Before and after

The first timeout-recovery version retained the original 20-day MT5 aggregate and subdivided only
after each 30-second failure. It prevented Producer exit, but a real daily rebuild repeatedly paid
the full timeout while shrinking several batches and remained unfinished after eighteen minutes.

MT5 holding reconstruction now starts with five-day Login-batch windows. A slow window splits the
Login list before splitting a singleton time range down to six hours. Position timestamps still
merge across all windows before duration and percentiles are calculated. MT4 keeps its fast indexed
aggregate and bounded fallback.

## Impact

The same complete 20-day history, products, accounts, samples and hard gates remain authoritative.
Only query scheduling changes. All databases remain read-only; pool construction still occurs before
MT5 initialization and cannot place a Demo order.

## Verification

The regression uses two Logins, forces both Login and time splits in every five-day MT5 window, and
places a Position opening and close on opposite sides of a window boundary. The result must retain
one sample with the exact 7,200-second duration. Fast and Full verification cover all governed suites.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing, operations and test strategy.

## Deployment and rollback

Stop the Producer before promotion, verify the Demo remains flat, and restart only from clean
`main`. Rollback restores timeout-first subdivision; it preserves data correctness but reintroduces
unacceptable daily startup latency on the observed source.
