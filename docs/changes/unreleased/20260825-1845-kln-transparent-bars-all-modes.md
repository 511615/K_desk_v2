---
change_id: 20260825-1845-kln-transparent-bars-all-modes
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Keep native lower-pane bars invisible in every display mode

## Before and after

The ordinary Profit display made the native histogram transparent, but its grouped-bar display
path could still provide visible native colours. Both paths now make native columns transparent and
leave the custom 8px-to-18px overlay as the sole visible bar.

## Impact

Grouping changes neither values nor the zero-axis coordinate. It only prevents a thin native
column from returning when a user switches the grouping mode.

## Documentation updated

The existing `KLN-RENDER-001` contract already defines native lower-pane columns as transparent
and the custom overlay as the only visible bar; this correction now applies that rule to both data
paths.

## Verification

Focused dynamic-bar regression, the complete lightweight renderer suite, account response cache
test and inline account-page regression pass.

## Deployment and rollback

No API, data or MetaTrader Manager operation is involved. Reverting only restores the incorrect
grouped-mode native colours.
