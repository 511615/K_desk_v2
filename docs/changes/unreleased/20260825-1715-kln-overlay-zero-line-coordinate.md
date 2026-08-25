---
change_id: 20260825-1715-kln-overlay-zero-line-coordinate
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Anchor custom Profit bars to the visible zero line

## Before and after

The custom red/green Profit columns obtained their base from the histogram series. In the rendered
lower pane that coordinate was offset from the separately drawn dashed zero-line series, so both
colours met each other above the visible zero axis. The overlay now obtains its Profit base directly
from the zero-line series at value zero; red and green columns meet the same dashed axis.

## Impact

Only the custom-column y origin changes. Profit values, signs, colours, scale, filters, time mapping
and native chart data are unchanged.

## Documentation updated

Updated `KLN-RENDER-001` to specify that the overlay base is the actual visible zero-line coordinate.

## Verification

The renderer regression first failed while it required the overlay to read the zero-line series and
then passed after the exact coordinate was used. Browser acceptance reloads the inline chart and
checks the red and green columns against the dashed Profit zero axis.

## Deployment and rollback

No API, data, remote-state or MetaTrader Manager operation is involved. Reverting this change restores
the former histogram-derived base coordinate only.
