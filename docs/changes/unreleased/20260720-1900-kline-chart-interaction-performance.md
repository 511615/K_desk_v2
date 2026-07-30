---
change_id: 20260720-1900-kline-chart-interaction-performance
features: ["KLN-DB-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Keep long K-line charts responsive

## Before and after

Every pan, zoom and crosshair frame rebuilt an array for every embedded M1 bar. Dense views also
created a string-keyed `Map` for up to 30,000 bars, and crosshair lookup scanned the complete series.
After several interactions this allocation and full-series work could saturate the browser main
thread.

Charts now precompute minute positions, find visible bounds and the nearest crosshair bar with binary
search, and combine dense candles sequentially by canvas pixel. Input synchronization reuses the
already-calculated visible bounds. Compressed mode binary-selects visible market gaps and groups
dense boundaries by canvas pixel instead of redrawing thousands of overlapping lines and labels.
Raw quote rows and trade coordinates remain unchanged.
Long account/time-range chart titles may wrap on mobile so the page itself does not gain a horizontal
scrollbar; wide trade tables remain contained in their own scroll area.

## Impact

Only newly built or explicitly regenerated chart HTML changes. Quote selection, validation,
white styling, marker shapes, filters, gap modes, URLs and SQLite are unchanged.

## Documentation updated

The `KLN-DB-001` current-state document now records the bounded interaction-rendering behavior.

## Verification

Focused static regressions prohibit the full-series crosshair reduction and per-frame `Map`.
The reported 23,662-bar/806-trade chart completed 24 full-history crosshair moves in 0.63 seconds
with a 28 ms follow-up probe. Eight zoom and five pan gestures completed in 1.99 seconds with a
44 ms probe and no browser errors. Expanded real-time-gap mode completed 24 moves in 0.85 seconds
with an 18 ms probe. Its pre/post embedded data payloads have the same SHA-256 digest.

The largest offline regression fixture contains 29,975 bars, 3,403 trades and 11,989 gap rows.
Its optimized full-history crosshair probes completed in about 1.34 seconds in compressed mode and
1.59 seconds in expanded mode. The 375 px mobile viewport has no horizontal page overflow or
overlapping controls; its canvas remains nonblank and 12 crosshair moves completed in 0.33 seconds
with a 19 ms probe. Fast and Full gates passed with 214 Python/legacy tests, 11 frontend tests and a
production frontend build.

## Deployment and rollback

Deploy the generator code for new charts. Only the explicitly reported `2014003` chart was replaced;
the previous HTML remains beside it as `.pre_interaction_fix.html`. The `7796498` historical chart
was not overwritten. Rollback restores the prior generator/HTML; no database or MT Manager action
is required.
