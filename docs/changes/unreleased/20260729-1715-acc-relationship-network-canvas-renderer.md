---
change_id: 20260729-1715-acc-relationship-network-canvas-renderer
features: ["ACC-REL-001", "ACC-DETAIL-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# ACC-REL-001: Render relationship interaction on Canvas

## Before and after

The graph used an SVG stage. Even after frame coalescing, moving a node or transforming the stage
caused browser SVG layout and paint work for paths, labels and text, producing visibly stepped drag
and wheel interactions on the operator's workstation.

The graph now draws its complete visible evidence model on a high-DPI Canvas. One animation frame
per gesture applies pending node movement, panning or coalesced wheel input and draws the result.
Canvas geometry supplies node/edge hit testing, and all Chinese labels, relation filters, aggregate
expansion, evidence detail and reset behavior remain available. Wheel zoom is cursor-centred and
uses continuous exponential scaling instead of the former fixed 10% increments.

## Impact

This affects only the client-side presentation of the legacy `8777` account detail dialog. The
relationship API, data evidence, labels, filter meanings, cached response, routes and all read-only
database/MT provider behavior are unchanged. No local authority data or remote system is written.

## Documentation updated

Updated ACC-REL-001 and the relationship-network performance regression requirements in the test
strategy.

## Verification

Passed on 2026-07-29:

- Full verification completed: `303 passed, 1 warning` for Python/legacy tests, `20 passed` for
  frontend tests, and the Vite production build passed.
- Production `8777/8766` was restarted with the governed scripts; both readiness checks passed.
- Browser acceptance at `/account/233015?platform=MT5&server=AC%20CN%20MT5` generated 11 entities,
  19 relationships and 59 evidence entries. The Canvas was nonblank with readable Chinese labels.
  A 25-point node drag moved the account and its connected labels without changing the selected
  subject; a subsequent click selected that account. Pan, cursor-centred continuous wheel zoom,
  reset and relation-type filter toggle completed without browser-console errors.

## Deployment and rollback

No migration is required. Rollback restores the previous SVG relationship renderer and restarts only
the K_desk web processes; it does not alter account, ledger, cache or provider data.
