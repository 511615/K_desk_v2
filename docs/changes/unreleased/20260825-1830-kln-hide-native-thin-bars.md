---
change_id: 20260825-1830-kln-hide-native-thin-bars
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Display only the readable lower-pane bars

## Before and after

Both the native Lightweight Charts histogram columns and the custom readable overlay were visible.
The thin native bars correctly met the dashed zero axis while the wider overlay was separately
drawn, producing two contradictory bar shapes. Native Profit and Volume column colours are now
transparent; their data remains for the existing scale and coordinate mapping, while the custom
8px-to-18px bars are the only visible columns.

## Impact

Values, signs, zero-axis coordinate, scale, filters, time mapping and data payloads are unchanged.
Only the duplicate thin visual columns are removed.

## Documentation updated

Updated `KLN-RENDER-001` with the transparent-native/visible-overlay rendering rule.

## Verification

The renderer regression first failed while it required transparent native panel columns, then passed
after both native histogram data series used the transparent colour. Browser screenshot acceptance
confirms that no thin bar remains beside a wide bar.

## Deployment and rollback

No API, data, remote-state or MetaTrader Manager operation is involved. Reverting this change only
restores the duplicate thin native bars.
