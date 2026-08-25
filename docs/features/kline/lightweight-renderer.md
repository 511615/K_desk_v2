---
feature_id: KLN-RENDER-001
title: Lightweight Charts trade renderer
module: kline
status: active
apis: ["GET /api/accounts/by-login/{login}/inline-kline", "POST /api/kline/generate-from-db", "GET /output/{name}"]
code: ["src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py", "legacy/tools/trade_kline_tool/lightweight_trade_kline.py", "legacy/tools/trade_kline_tool/build_enhanced_trade_kline_from_cache.py", "legacy/tools/trade_kline_tool/generate_trade_kline_from_statement.py", "legacy/tools/trade_kline_tool/fused_trade_kline_features.py", "legacy/tools/trade_kline_tool/position_fused_trade_kline.py"]
tests: ["tests/test_lightweight_trade_kline.py"]
depends_on: ["KLN-DB-001", "KLN-TIMELINE-001"]
last_verified_version: 2.1.4
last_verified_date: 2026-08-25
---

# Lightweight Charts trade renderer

## Purpose and user entry

Replace the legacy canvas renderer while retaining the established trade evidence payload. The
generated artifact is opened from the existing K-line task result or `/output/{name}`. The legacy
account detail can also render the same document directly above its order table through 8777,
without creating a task artifact.

## UI and behavior

The artifact keeps symbol selection, compressed/real time axis, order count limit, buy/sell and close
markers, holding lines, Profit/volume/position panes, filters, time-window positioning, summary
metrics, order table and optional funds-event replay. Lightweight Charts supplies native crosshair,
pan, zoom and responsive resize behavior. When embedded in the legacy account detail, the document
reports its rendered height to the parent; the parent validates the sending frame and expands the
embed so the account page owns scrolling instead of showing a nested K-line scrollbar.
Compressed time preserves the original quote timestamp labels on the horizontal axis. Its internal
continuous ordering must never expose the synthetic `2000-01-01` anchor used to remove market-closed
gaps; switching between compressed and real time changes spacing only, not displayed dates.

## API contract

No existing endpoint or artifact name changes. `GET /api/accounts/by-login/{login}/inline-kline`
is an additive 8777 route with `platform`, `server` and `recentOrders=1..300`; it returns the
direct HTML with private 60-second caching and no job/artifact identifier. The generator accepts
`--offline-cache` and `--quote-cache-dir` as additive CLI options.

## Data, routing and read-only constraints

The renderer consumes normalized trades, cached/external M1 bars and mapping metadata. It never
imports MetaTrader5, opens a Terminal connection, or writes a remote database. Quote ingestion stays
in the upstream read-only adapter. The inline account adapter may refresh its bounded local M1 quote
cache before calling the renderer; it does not create an HTML artifact or a durable K-line job.

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

`tests/test_lightweight_trade_kline.py` verifies series, markers, filters, timeline payload, embedded
height reporting, real quote labels in compressed time, readable dynamic lower-pane bar widths and
the absence of an MT5 dependency in rendered HTML. Release E2E verifies the server-rendered legacy
account page retains the inline K-line section and frame, which replaced the removed order-details
block. Python compilation and the existing K-line tests must pass before promotion.

## Compatibility and deprecation

Existing API paths, artifact names and payload fields remain unchanged. Production ports are not
changed by this feature; promotion requires separate parity verification and cutover.

The current renderer follows the supplied production artifact's interaction contract: paired
`隐藏停盘 / 显示停盘` controls, display limit in the toolbar, filters on their own row, overlay pane
switcher, range status, original order-table columns and position snapshot cards. Nodes keep the
legacy semantics without ticket text: directional triangles, red close squares and dashed holding lines.
The presentation uses the dark TradingView-style palette; marker colors are light/blue/purple only
to preserve contrast on that dark surface. Trade nodes are rendered in a transparent overlay using
the order's normalized open/close plot price and the chart time coordinate. Buy/sell triangles are
small (4px side, 7px height) and sit on the exact execution quote rather than using the native
`aboveBar`/`belowBar` placement; close squares use the exact close quote. The overlay is repositioned
after fit, pan, zoom, resize and vertical pane/price-scale dragging so nodes remain attached to their quotes.
The marker overlay is a child of the exact Lightweight Charts host, rather than a sibling of the
chart shell. Its x/y coordinates therefore share the candle canvas origin and price scale when the
browser lays out the right axis, preventing a horizontal left shift of evidence nodes.

The Profit indicator explicitly uses `base=0`, one symmetric absolute-value scale for positive and
negative values, and a shared high-contrast dashed zero baseline. Profit bars are therefore
anchored to the same baseline; profitable orders are red and extend upward, while losing orders are
green and extend downward with equal visual magnitude for equal absolute profit. Its visible right
price scale reports the actual Profit values for the current filtered bar set, making the bar height
auditable without relying on visual proportion alone.

The visible Profit and Volume bars use a chart-host overlay in addition to the native histogram data.
Each visible time bucket is grouped for this presentation and has a fixed minimum width of 8px, with
the width adapting to the current zoom level up to 18px. Filtering, symbol changes, pane switches,
panning, zooming and resize events redraw the overlay; the underlying order values and time mapping
remain unchanged. The account-detail embed requests this document with the browser `no-store`
directive and a page-load version query parameter, so a reload after a renderer deployment cannot
retain an older chart document. Its parent account-detail document is revalidated on every browser
refresh so this versioned embed loader itself cannot remain stale.
The overlay translates its pane-local price coordinates into the lower indicator pane, including the
4px separator between chart panes, and clips there, so a readable Profit/Volume bar can never cover
the candlestick pane or end above the visible Profit zero line. The horizontal axis emits the
full year/date only at the first source node, `MM-DD` at later midnight boundaries and compact
`HH:MM` labels otherwise; it preserves the original quote timestamps while preventing dense labels
from overlapping.
The Profit histogram and its custom overlay share the explicit dashed zero line as their only
baseline. Native last-value price lines are disabled for Profit and Volume, so the current value
cannot introduce a second coloured horizontal line that appears to shift one colour's origin.
The custom red/green bars take their base coordinate directly from the zero-line series rather than
from the histogram's coordinate conversion, guaranteeing that both colours meet the visible dashed
Profit zero axis even if Lightweight Charts applies different histogram geometry.
Pointer movement and release within the chart host schedule both overlay redraws, so dragging a
pane separator or vertical price scale immediately re-reads the zero-line coordinate and every
buy/sell/holding price coordinate instead of leaving bars or markers at their pre-drag position.
The native Profit/Volume histogram data remains present only to retain its established scale and
coordinate behavior, but its columns are transparent in both individual-order and grouped-bar
display modes. The visible bars are exclusively the custom 8px-to-18px overlay, so a thin native
bar cannot appear beside or through the readable column.

The chart stage uses a compact 620px vertical layout. Its lower Profit/volume/position pane has a
`0.6` stretch factor while the time scale keeps a 24px minimum height, reducing the visual weight of
the bar and time-label area without shrinking the main candlestick pane or changing chart data.

Holding lines use the legacy-style thin, rounded, semi-transparent purple dash
(`rgba(192,145,255,alpha)`, `5 4` dash). Density reduces opacity and width rather than adding a
halo, so holding evidence remains visible without obscuring candlesticks. The SVG overlay has an
explicit z-index above the Lightweight Charts canvas and below trade markers, so the chart
background cannot cover any in-plot portion of a holding line.

During pan, zoom and resize the overlay is recomputed at most once every 50 ms and receives one
final exact refresh after the interaction settles. It renders only orders intersecting the visible
bar range plus a three-bar boundary buffer. Holding lines, opening triangles and close squares are
batched into three SVG paths rather than creating one DOM node per order, so a large account's
off-screen history does not make drag interaction progressively slower. The visible data, order
limit, filters, execution prices and marker/line semantics are unchanged.

The time scale sets `minBarSpacing` to `0.01`, matching the legacy generated chart's full-axis
zoom-out behavior, then fits content on initial render. Users can expand the visible interval to
the entire embedded M1 history instead of stopping at a pixel-spacing floor. The generated payload
continues to cap display bars at 30,000, and viewport-scoped overlay batching remains active at
this limit.

M1 timestamps identify the start of a one-minute interval. Orders map to their containing M1 bar
(the most recent bar at or before the trade time), while the buy/sell node, close node and holding
line retain their second-level fraction within that interval. Earlier events appear to the left and
later events to the right without adding synthetic K bars or changing the M1 candle. Profit and
Volume indicators intentionally remain grouped to their containing M1 interval.

M1 OHLC bars are Bid values. Endpoint validation is direction-aware: buy opens and sell closes are
checked against the Bid high plus the recorded spread (Ask upper envelope); sell opens and buy closes
are checked against Bid. Markers retain the original execution quote instead of being clamped into a
wick, so a confirmed Ask execution may remain above a Bid-only candle.
