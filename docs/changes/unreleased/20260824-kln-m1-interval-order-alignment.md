---
change_id: 20260824-kln-m1-interval-order-alignment
features: ["KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

An intermediate nearest-minute rule still selected the following M1 bar for orders in the latter
half of a minute. MT5 M1 timestamps denote the opening time of their one-minute interval, so the
renderer now maps each order to the most recent bar at or before its timestamp. This places the
node and its lower-panel bar on the correct candle interval.

## Impact

Only display-time M1 interval alignment changes in the isolated K-line artifact. Execution prices,
cached bars, results, APIs and production services remain unchanged.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the M1 interval contract.

## Verification

For all 2,922 open/close points of the `33305774` sample, matching the containing M1 interval puts
2,850 within the cached bid high/low envelope, compared with 2,417 for nearest-minute matching.
The remaining differences are expected bid/ask-side executions or cached quote limitations. Focused
tests pass (26 tests) and the browser reports no errors or warnings.

## Deployment and rollback

Development-only change on `feature/kln-live-demo`; production was not restarted. Reverting this
commit returns to nearest-minute matching.
