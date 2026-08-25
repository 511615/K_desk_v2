---
change_id: 20260825-1615-kln-lower-bar-pane-and-axis-labels
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Keep readable bars in the lower pane and compact the time axis

## Before and after

The readable custom Profit/Volume overlay used pane-local y coordinates against the full chart host.
It could therefore draw the thicker columns over the candle pane while the actual lower histogram
remained thin. It now offsets the values by the lower-pane origin and clips every custom column to
that pane. The lower Profit/Volume display therefore receives the 8px-to-18px dynamic width and the
candlestick pane cannot receive these columns.

Dense time-axis labels previously repeated the full `YYYY-MM-DD HH:MM` timestamp. The first source
node now carries the year/date, later day boundaries use `MM-DD`, and ordinary ticks use `HH:MM`.

## Impact

This is a visual renderer correction only. Trade data, M1 mapping, pane values, filters, API
contracts and read-only quote routing are unchanged.

## Documentation updated

Updated `KLN-RENDER-001` with the lower-pane coordinate/clip rule and compact time-axis labels.

## Verification

The renderer regression first failed while it required lower-pane geometry, clipping and compact
timestamp formatting, then passed after the renderer update. Browser acceptance checks the overlay
source and visual pane placement on the account-detail embed.

## Deployment and rollback

No API, data, remote-state or MetaTrader Manager operation is involved. Reverting this change
restores the previous overlay placement and timestamp text only.
