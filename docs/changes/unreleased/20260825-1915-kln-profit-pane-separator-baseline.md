---
change_id: 20260825-1915-kln-profit-pane-separator-baseline
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Include the chart-pane separator in the Profit bar baseline

## Before and after

The custom readable Profit/Volume overlay translated pane-local coordinates by the heights of the
preceding panes only. Lightweight Charts also renders a 4px separator between panes, so every
custom bar was displayed four pixels above its dashed zero line. The translation now includes one
separator per preceding pane.

## Impact

Order values, signs, filters, scale and zero-line source are unchanged. Positive and negative
custom bars now meet the visible dashed zero axis exactly, matching the hidden native histogram.

## Documentation updated

Updated `KLN-RENDER-001` with the pane-separator coordinate rule.

## Verification

The dynamic-bar regression first failed without the separator contract, then passed after the
translation was corrected. The full renderer and inline account-page regressions also pass.

## Deployment and rollback

No API, data, remote state or MetaTrader Manager operation is involved. Reverting restores the
four-pixel visual offset only.
