---
change_id: 20260729-1830-acc-relationship-network-raster-cache
features: ["ACC-REL-001", "ACC-DETAIL-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# ACC-REL-001: Cache the static relationship scene during gestures

## Before and after

The native Canvas renderer still painted each visible relationship, label and node for every pan, zoom and
node-drag frame. It was correct but did not give sufficiently smooth interaction on the operator's machine.

The graph now pre-renders the stable 1000 by 620 world scene into a detached 3x raster Canvas. Pan and
wheel frames draw that cached scene once at the current camera transform. A node drag temporarily omits the
active node and its incident relations from the cache, then paints just those dynamic elements above it.
The complete cache is rebuilt only after a filter, aggregate expansion, selection, reset or completed node
drag. The client records frame and cache-build timing samples for browser acceptance diagnostics.
The latest values are also exposed through nonvisual Canvas `data-*` attributes for deterministic browser
acceptance without adding an operator-facing performance panel.

## Impact

Only browser presentation in the legacy account-detail relationship dialog changes. API payloads, filters,
relation labels, evidence detail, aggregation, page cache, URLs and read-only providers are unchanged. The
change writes no SQLite, MySQL, MT4 or MT5 data and does not require WebGL or GPU support.

## Documentation updated

Updated ACC-REL-001, ACC-DETAIL-001 and relationship-network performance requirements in the test strategy.

## Verification

Passed on 2026-07-29:

- Inline legacy JavaScript parsed with the bundled Node runtime and focused legacy-page tests passed.
- Fast and Full verification passed: `303 passed, 1 warning` for Python/legacy tests, `20 passed` for
  frontend tests, and the Vite production build passed.
- Production `8777/8766` was restarted with the governed scripts and both readiness checks passed.
- Browser acceptance at `/account/233015?platform=MT5&server=AC%20CN%20MT5` retained 11 entities,
  19 relationships and 59 evidence records with no browser-console errors. Initial static-cache build
  measured 5.50ms. A wheel zoom measured 0.10ms drawing time with no cache rebuild; a pan measured 0.30ms
  with no cache rebuild. The automated node-drag completion frame measured 14.40ms, including final scene
  composition, while its cache rebuild measured 0.20ms; it is a release-time operation rather than a
  recurring pan/zoom frame.

## Deployment and rollback

No migration is required. Rollback restores the previous direct native-Canvas renderer and restarts only
the K_desk services; it does not alter account, ledger, cache or provider state.
