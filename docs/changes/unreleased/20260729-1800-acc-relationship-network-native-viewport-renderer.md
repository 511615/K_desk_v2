---
change_id: 20260729-1800-acc-relationship-network-native-viewport-renderer
features: ["ACC-REL-001", "ACC-DETAIL-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# ACC-REL-001: Render the relationship network directly in the visible viewport

## Before and after

The previous graph drew a text-heavy Canvas into a CSS-composited stage. Browser pan and zoom scaled
that existing Canvas texture, which was not smooth enough on the operator workstation.

The legacy account page now uses one native-resolution Canvas and a camera-based renderer. Pointer
input is coalesced with `requestAnimationFrame`, and each frame draws only the currently visible nodes,
relationships and labels. Edge-label widths are cached. There is no CSS stage transform, no DOM/SVG graph
rebuild and no evidence-pane render while a pointer gesture is in progress.

## Impact

Only the client rendering of the `关系网络` dialog on the legacy account page changes. The existing API,
page cache, filters, aggregate expansion, relation labels, evidence detail, account URLs and read-only
providers remain unchanged. This change writes no SQLite, MySQL, MT4 or MT5 data.

## Documentation updated

Updated ACC-REL-001, ACC-DETAIL-001 and the relationship-network performance requirements in the test
strategy.

## Verification

Passed on 2026-07-29:

- Inline legacy JavaScript parsed with the bundled Node runtime.
- Focused legacy-page tests passed.
- Fast and Full verification passed: `303 passed, 1 warning` for Python/legacy tests, `20 passed` for
  frontend tests, and the Vite production build passed.
- Production `8777/8766` was restarted with the governed scripts and both readiness checks passed.
- Browser acceptance at `/account/233015?platform=MT5&server=AC%20CN%20MT5` generated 11 entities,
  19 relationships and 59 evidence records. The native Canvas was nonblank at `840 x 521`; node drag,
  cursor-centred wheel zoom, relation filtering, aggregate expansion and reset completed without browser
  console errors.

## Deployment and rollback

No migration is required. The production service can be restarted after verification. Rollback restores the
previous renderer and restarts only the K_desk processes; it does not change any account, ledger, cache or
provider state.
