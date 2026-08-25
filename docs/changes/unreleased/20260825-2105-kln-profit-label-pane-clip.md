---
change_id: 20260825-2105-kln-profit-label-pane-clip
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Keep Profit value labels inside the Profit pane

## Before and after

Overlay labels overlapped the main chart price axis. They now use an inset Profit-pane column and
the same pane clip boundary as the bars.

## Impact

Only label placement changes; Profit values and chart data are unchanged.

## Documentation updated

Updated the K-line renderer change record.

## Verification

The renderer suite passes with the clipped label coordinates.

## Deployment and rollback

No API or data change. Reverting restores the misplaced labels.
