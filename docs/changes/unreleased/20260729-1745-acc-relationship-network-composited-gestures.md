---
change_id: 20260729-1745-acc-relationship-network-composited-gestures
features: ["ACC-REL-001", "ACC-DETAIL-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# ACC-REL-001: Compose relationship gestures without full graph repaints

## Before and after

The previous Canvas implementation still repainted every node, relationship line and Chinese label on
each drag, pan or wheel frame. This left interaction bound to main-thread drawing even though the
underlying network data was static during a gesture.

The legacy detail page now renders a static high-DPI base Canvas and a transparent active-drag overlay
inside one CSS-composited stage. Panning and cursor-centred wheel zoom update only the stage's
`translate3d` and `scale` transform. Starting a node drag paints the base once without that node and its
incident relationships; each drag frame paints only that node and those relationships on the overlay.
Completing the drag repaints the base once and clears the overlay.

## Impact

This changes only browser presentation for the legacy relationship-network dialog on `127.0.0.1:8777`.
The relationship API, evidence, labels, filters, aggregate expansion, cache, routes and all read-only
providers are unchanged. No SQLite, MySQL, MT4 or MT5 state is written.

## Documentation updated

Updated ACC-REL-001, ACC-DETAIL-001 and the relationship-network performance regression requirements
in the test strategy.

## Verification

Passed on 2026-07-29:

- Fast and Full verification completed: `303 passed, 1 warning` for Python/legacy tests,
  `20 passed` for frontend tests, and the Vite production build passed.
- Production `8777/8766` was restarted with the governed scripts; both readiness checks returned
  `ready`.
- Browser acceptance at `/account/233015?platform=MT5&server=AC%20CN%20MT5` returned 11 entities,
  19 relationships and 59 evidence records. The rendered surface contained separate base and overlay
  Canvases plus a CSS `will-change: transform` stage. A node drag retained the selected subject;
  pan changed only the stage translation and wheel zoom changed only its scale. Reset restored all
  six relation filters and the initial transform. No browser-console errors were recorded.

## Deployment and rollback

No data migration is required. Rollback restores the preceding Canvas renderer and restarts only the
K_desk web processes; it does not alter accounts, ledger records, caches or provider data.
