---
change_id: 20260720-1600-tox-push-equivalent-fast-paths
features: ["TOX-PUSH-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# Add equivalent fast paths for push detection

## Before and after

Full-platform structure screening reconstructed candidate orders in 50-login batches. On a shared
DBG MT5 export, every batch repeated a large historical login-index scan; one 320-account source
took 126.98 seconds even though the requested one-day time index contained a small bounded slice.
Order reconstruction now scans the existing MT5 12-hour and MT4 daily shards through time indexes,
then performs exact candidate filtering and complete-position reconstruction. The login-batch path
remains the automatic compatibility fallback.

Single-account market-pushing checks queried every same-platform source sequentially and requested
one Terminal Tick range per sampled order. Independent source queries now run concurrently and are
reassembled in the original source order. Nearby Tick windows with a total span no longer than 15
minutes are fetched once and sliced back to the original per-order boundaries; an empty slice is
retried with the original request.

Structure scoring was also serial even though each account is independent. It now runs in
125-account batches with no more than two child processes, restores results to input order and
retries the full stage serially if process execution is unavailable.

## Correctness

No score, threshold, order filter, sample limit, history scope, peer definition or Tick formula
changes. A read-only same-input comparison on DBG GB MT5 reconstructed the same 320 accounts and
2,420 normalized orders with an identical full-content hash. A single-account comparison produced
identical synchronization and Tick result payloads before and after the fast paths.

## Impact

Read-only SQL routing, full-platform order-load progress, cross-account query scheduling and
historical Tick retrieval. Public request and response fields remain compatible; no migration is
required.

## Documentation updated

Market-pushing current state, data/routing authority and test strategy.

## Verification

Focused tests cover time/position index selection, cross-shard deal de-duplication, concurrent
source ordering, exact Tick slicing and serial/parallel score equivalence. On the production one-day candidate set, AC GB MT5 retained
1,612 accounts and 53,638 orders while dropping from 34.3 to 10.0 seconds; DBG GB MT5 retained 320
accounts and 2,420 orders while dropping from 126.98 to 1.50 seconds. For account 36090 on the same
1,702-order input, synchronization retained an identical payload and dropped from 4.57 to 1.76
seconds; Tick retained an identical payload and dropped from 4.54 to 3.99 seconds.
A final production-path scan processed 4,425 candidates, found 682 structural candidates, completed
one all-history deep check and returned zero failures in 55.7 seconds. The earlier production-path
baseline processed 3,966 candidates in 149.6 seconds. The two-process screen path did not fall back.

## Deployment and rollback

The discovery subprocess loads the new path on its next job. The persistent interactive worker must
restart before single-account checks use the new helpers. Rollback restores sequential source and
per-order Tick reads plus login-batch discovery reconstruction; no stored data needs conversion.
