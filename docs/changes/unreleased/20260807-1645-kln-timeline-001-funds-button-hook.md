---
change_id: 20260807-1645-kln-timeline-funds-button-hook
features: ["KLN-TIMELINE-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Repair K-line funds-panel switch hook

## Before and after

The generated chart exposes a `资金` button, but the replay module attempted to wrap a nonexistent
`drawBottomPanel` function. That runtime reference error stopped the remainder of the module,
including the button click binding, from loading.

The module now wraps the actual `drawKdeskBottomPanel` function and uses the chart's scheduled draw
path after selection. Selecting `资金` activates the existing lower K-line panel and renders the
Balance/Credit replay there.

## Impact

Only the standalone K-line HTML interaction changes. Cached source replay, chart generation data,
remote read-only access, APIs, account data and the continuous event table remain unchanged.

## Documentation updated

Updated `KLN-TIMELINE-001` acceptance language for actual lower-panel hook activation.

## Verification

Targeted tests assert the generated artifact wraps `drawKdeskBottomPanel`, not the obsolete name.
The complete generated 6003593 HTML was executed in a local browser-DOM harness: no runtime errors,
`资金` changes to active, and the virtual event table renders its bounded row window. Full K_desk
verification is required before release.

## Deployment and rollback

Release through the standard production script. Rollback restores the previous artifact module;
no cached or remote data changes.
