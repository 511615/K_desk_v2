---
change_id: 20260825-1640-kln-single-profit-zero-axis
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Use one visible zero axis for Profit bars

## Before and after

The lower Profit pane retained the native histogram current-value price line while the custom
readable red/green bars used the explicit dashed zero line. The extra coloured line could look like
a separate baseline for one side of the Profit bars. Native current-value lines are now disabled for
both Profit and Volume; the explicit zero line is the sole Profit baseline.

## Impact

Profit values, colours, bar coordinates, chart scale, filters and time mapping are unchanged. This
change removes only the duplicate visual guide.

## Documentation updated

Updated `KLN-RENDER-001` with the single-baseline rule for native and overlay Profit rendering.

## Verification

The renderer regression first failed while it required disabled native price lines, then passed after
the Profit and Volume histogram options were updated. Browser acceptance checks that only the dashed
Profit zero line remains under the custom bars.

## Deployment and rollback

No API, data, remote-state or MetaTrader Manager operation is involved. Reverting this change only
restores the former duplicate current-value guide.
