---
change_id: 20260825-2525-kln-position-pane-clarity
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Make all-product position-pane values self-explanatory

## Before and after

The `仓位` lower pane displayed blue and yellow all-product step lines with numeric values but
without a visible in-pane key. Its static legend also incorrectly described the yellow total-lot
series as margin usage. The pane now shows an in-chart key whenever it is active: blue is open
position count and yellow is total lots. The risk card now explicitly uses the title
`权益归零压力价`.

## Impact

This is a presentation-only correction for the direct inline K-line. The replayed position count,
total lots, funds, floating P/L, margin and risk-boundary calculations are unchanged. No endpoint,
stored data or trading behavior changes.

## Documentation updated

Updated `ACC-DETAIL-001` and `KLN-RENDER-001` with the active-pane legend, exact line semantics,
and the risk-card explanation.

## Verification

The renderer regression asserts the in-pane legend, the corrected labels, the visible risk-card
title and the active-pane show/hide behavior. K-line and legacy account tests plus JavaScript syntax
validation pass.

## Deployment and rollback

The release uses the normal controlled K_desk promotion and restart. Reverting this compatible
renderer markup/CSS/label change restores the prior ambiguous position-pane presentation; no data
migration or external state rollback is needed.
