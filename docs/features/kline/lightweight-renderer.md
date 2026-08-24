---
feature_id: KLN-RENDER-001
title: Lightweight Charts trade renderer
module: kline
status: active
apis: ["POST /api/kline/generate-from-db", "GET /output/{name}"]
code: ["legacy/tools/trade_kline_tool/lightweight_trade_kline.py", "legacy/tools/trade_kline_tool/build_enhanced_trade_kline_from_cache.py", "legacy/tools/trade_kline_tool/generate_trade_kline_from_statement.py", "legacy/tools/trade_kline_tool/fused_trade_kline_features.py", "legacy/tools/trade_kline_tool/position_fused_trade_kline.py"]
tests: ["tests/test_lightweight_trade_kline.py"]
depends_on: ["KLN-DB-001", "KLN-TIMELINE-001"]
last_verified_version: 2.1.1
last_verified_date: 2026-08-21
---

# Lightweight Charts trade renderer

## Purpose and user entry

Replace the legacy canvas renderer while retaining the established trade evidence payload. The
generated artifact is opened from the existing K-line task result or `/output/{name}`.

## UI and behavior

The artifact keeps symbol selection, compressed/real time axis, order count limit, buy/sell and close
markers, holding lines, Profit/volume/position panes, filters, time-window positioning, summary
metrics, order table and optional funds-event replay. Lightweight Charts supplies native crosshair,
pan, zoom and responsive resize behavior.

## API contract

No endpoint or artifact name changes. The generator accepts `--offline-cache` and
`--quote-cache-dir` as additive CLI options.

## Data, routing and read-only constraints

The renderer consumes normalized trades, cached/external M1 bars and mapping metadata. It never
imports MetaTrader5, opens a Terminal connection, or writes a remote database. Quote ingestion stays
in the upstream read-only adapter.

## Business rules and units

The account, symbol, cent-account scaling, price correction, time mode, missing-minute handling and
timeline fields use the existing contracts. Profit, volume and holding filters use the existing
normalized order columns.

## Loading, empty and failure behavior

`--offline-cache` fails with `QUOTE_CACHE_REQUIRED` when the mapping is missing and records
`QUOTE_CACHE_MISSING` for an individual missing symbol cache. The browser remains usable for symbols
whose cache was accepted.

## Code and dependencies

The renderer is `lightweight_trade_kline.py` and loads pinned Lightweight Charts 5.0.8 in the
artifact. It shares cache normalization helpers with the legacy generator.

## Tests and acceptance

`tests/test_lightweight_trade_kline.py` verifies series, markers, filters, timeline payload and the
absence of an MT5 dependency in rendered HTML. Python compilation and the existing K-line tests must
pass before promotion.

## Compatibility and deprecation

Existing API paths, artifact names and payload fields remain unchanged. Production ports are not
changed by this feature; promotion requires separate parity verification and cutover.

The current renderer follows the supplied production artifact's interaction contract: paired
`隐藏停盘 / 显示停盘` controls, display limit in the toolbar, filters on their own row, overlay pane
switcher, range status, original order-table columns and position snapshot cards. Nodes keep the
legacy semantics without ticket text: directional triangles, close squares and dashed holding lines.
The presentation uses the dark TradingView-style palette; marker colors are light/blue/purple only
to preserve contrast on that dark surface. Trade nodes are rendered in a transparent overlay using
the order's normalized open/close plot price and the chart time coordinate. Buy/sell triangles are
small (4px side, 7px height) and sit on the exact execution quote rather than using the native
`aboveBar`/`belowBar` placement; close squares use the exact close quote. The overlay is repositioned
after fit, pan, zoom and resize so nodes remain attached to their quotes.

The Profit indicator uses one symmetric absolute-value scale for positive and negative values and a
shared dashed zero baseline. Profit bars are therefore anchored to the same baseline; positive bars
extend upward and negative bars downward with equal visual magnitude.

Holding lines use a higher-contrast purple (`rgba(192,145,255,alpha)`) with density-aware opacity
from 0.58 to 0.92 and a minimum width of 1.25px, so the legacy dashed evidence remains readable on
the dark TradingView-style background.

Orders with second-level timestamps map to the nearest M1 quote bar, matching the legacy canvas
renderer. The same nearest-bar index drives the buy/sell node, close node, holding line and Profit
or Volume indicator bar, so every plotted order shares one horizontal time coordinate.
