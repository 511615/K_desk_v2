---
feature_id: KLN-DB-001
title: Database K-line generation
module: kline
status: active
apis: ["POST /api/kline/generate-from-db", "POST /api/uploads", "POST /api/jobs/{job_id}/generate", "GET /output/{name}"]
code: [".env.example", "config/kline_quote_sources.example.json", "frontend/src/kdesk-theme.css", "frontend/src/pages/AccountPage.vue", "src/kdesk/domain/kline.py", "src/kdesk/application/kline_generation.py", "src/kdesk/application/kline_timeline_cache.py", "src/kdesk/infrastructure/quote_sources.py", "src/kdesk/api/account_app.py", "src/kdesk/api/kline_app.py", "src/kdesk/worker/runner.py", "scripts/start_prod.ps1", "legacy/tools/trade_kline_tool/generate_trade_kline_from_statement.py", "legacy/tools/trade_kline_tool/build_enhanced_trade_kline_from_cache.py", "legacy/tools/trade_kline_tool/API.md", "legacy/tools/trade_kline_tool/README.md"]
tests: ["tests/test_api.py", "tests/test_kline.py", "tests/test_kline_timeline_cache.py", "tests/test_worker.py"]
depends_on: ["JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-12
---

# Database K-line generation

## Purpose and user entry

Generate buy/sell K-line evidence from account databases or uploaded statements and expose the
result through account detail and the K-line task center.

## UI and behavior

Statement upload first performs a durable inspection, then the K-line task center automatically
submits generation for every parsed symbol and keeps polling the generation job. Users see durable
progress/events and receive a direct link when the generated HTML chart is ready; a completed
inspection alone is not presented as a completed chart.
The production account page opens the task center on the production K-line port `8766`; port `8866`
remains development-only.
Production child processes inherit a pinned main-checkout `PYTHONPATH` and disabled user-site
packages, so K-line submissions and their Worker consumers always use the same production source
tree and SQLite runtime.
New HTML preserves the established white high-contrast chart workspace and remains standalone for
iframe, direct and offline use. It defaults to a compressed quote-index axis with visible market-break labels; the
`隐藏停盘 / 显示停盘` segmented control expands actual elapsed time without manufacturing bars.
Buy opens use upward arrows, sell opens use downward arrows and closes use squares. A missing-quote
endpoint keeps the same directional/square outline as an anomaly marker.
Interactive charts precompute bar positions, locate visible ranges and crosshair bars with binary
search, and aggregate dense candles by horizontal canvas pixel so pan, zoom and crosshair movement
remain responsive on long M1 histories without changing underlying trade or quote data. Compressed
mode also binary-selects visible gap markers and groups dense boundaries by canvas pixel while
retaining exact break labels after zoom-in.

## API contract

Account and K-line endpoints submit jobs, poll by job ID, cancel and serve safe artifact names.
Job results retain `chart`, `status` and `message` and add `partial`, `symbols[]`, `failures[]` and
`quoteSources[]`. Failure rows contain symbol, stage, code, attempted sources, metrics and reason.
Database chart requests additively accept `includeTimeline=false|true` and
`refreshTimelineCache=false|true`. The replay is omitted unless explicitly selected; when selected,
the complete account-route replay is cache-backed as specified by `KLN-TIMELINE-001`. No endpoint or
chart URL changes.

## Data, routing and read-only constraints

Database and MT5 quote access is read-only. Uploads/artifacts remain inside configured runtime directories.
Database order lookup includes DBG MT5 Live2 through `crm_vn` code 5 / `crm_vn_mt5_live2`; quote
selection still follows the returned logical server and the configured provider registry.
Production starts K-line work with a dedicated local quote Terminal. `KDESK_KLINE_QUOTE_TERMINAL`
can override its executable path from the user environment; if it is not set, the validated isolated
`D:\risk\mt5_backtest_terminal\terminal64.exe` is used. Startup fails explicitly when that executable
is unavailable instead of silently falling back to a stale interactive Terminal.
`KDESK_KLINE_QUOTE_SOURCES` may point to a local credential-free JSON registry. Database orders use
their platform/server same-source route first; only route-declared fallback providers are eligible.
Uploaded reports evaluate the allowed provider pool and select the highest-confidence accepted source.
Without a registry, the current legacy `default` Terminal is the universal read-only fallback for
database tasks and is evaluated under the stricter fallback acceptance gate. An explicit registry may
still constrain server routes; a missing configured route fails with `NO_SAME_SOURCE_PROVIDER` and
includes the requested route plus configured provider identities.

## Business rules and units

Symbol candidates are scored rather than resolved by first fuzzy match. `UT100` maps to the NAS100
roll family and standard dotted broker suffixes (including G/P), ECN/PRO/E/Roll variants remain
compatible. Alignment samples up to five
evenly distributed orders at both endpoints. GMT and GMT+3 are tried first; offsets GMT-4 through
GMT+4 are considered only after initial rejection. Same-source acceptance requires 60% raw M1
envelope hits and normalized median distance at most 2; fallback requires 80% hits or every endpoint
within tolerance. A narrowly bounded fallback near-match is also accepted only with at least 70% raw
hits, 90% endpoint tolerance hits, median normalized distance at most 0.25 and maximum normalized
distance at most 1.25. Price correction is applied only when declared by the selected provider.

Gaps over five minutes form segment boundaries and gaps over sixty minutes are labelled closed/no
quote. Long-history aggregation occurs within each segment. Missing-minute trades retain their real
time and use hollow warning markers rather than moving to the next quote.

The development renderer is now Lightweight Charts 5.0.8. It consumes the same normalized payload
and keeps symbol selection, filters, order markers, holding lines, Profit/volume/position panes,
time-window positioning, summary metrics, order table and optional funds replay. Quote acquisition
is separated from rendering: `generate_trade_kline_from_statement.py --offline-cache` reads an
existing mapping and M1 cache only, so it does not initialize MT5. The cache is produced by the
upstream read-only quote adapter and can later be replaced by a live Terminal feed without changing
the browser contract.

## Loading, empty and failure behavior

Invalid uploads, unavailable quotes and unsafe paths fail explicitly. A failed symbol does not block
accepted symbols; the job fails only when no symbol is accepted. Jobs survive web restart and retain
structured failure details in the existing SQLite result JSON.
The production launcher verifies any listener already occupying `8777` or `8766` through its local
readiness runtime and current main-worktree Uvicorn supervisor before accepting it. 8777 must report
`profile=prod` and production `kdesk.sqlite`; 8766 must report that same file as `workerQueue`.
A K_desk listener with another runtime, owner or unreadable readiness is replaced together with its
Uvicorn supervisor, then the complete production set (both web services, one interactive Worker and
discovery Workers) must pass readiness. This prevents an accidentally started old/dev web process
from accepting K-line jobs without a matching production Worker.
Protected unrelated processes are skipped during local process enumeration so stop/start recovery
continues when Windows denies inspection of another process.
An MT5 IPC initialization failure is reported as a structured source failure. The production launcher
prevents the known stale-interactive-Terminal route by selecting the dedicated quote Terminal before
the web and worker processes start.

## Code and dependencies

FastAPI validates/submits; the worker owns quote sessions and generator execution.

## Tests and acceptance

Tests cover routing priority, suffix and UT100 aliases, acceptance gates, offset expansion, rejected
anomaly profiles, partial success, structured results, gap segmentation and white chart controls.

## Compatibility and deprecation

Existing chart URLs, ports, parameters, mapping organization and old cache naming remain compatible.
Provider-qualified caches are preferred for new output; old caches remain readable. Historical HTML
is never rebuilt or overwritten by this change.
