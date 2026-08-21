---
change_id: 20260821-kln-legacy-marker-and-profit-baseline
features: ["KLN-RENDER-001"]
change_type: compatibility
status: unreleased
compatibility: compatible
---

## Before and after

The previous dark preview used light filled triangles and let the Profit histogram choose an
asymmetric automatic scale. The renderer now uses the legacy-style dark triangles with a subtle
light outline, while keeping the small exact-price placement. Profit bars share a symmetric
absolute-value scale and a dashed zero reference line, so positive and negative bars use one common
baseline and equal magnitude is drawn with equal height.

## Impact

This affects only the isolated Lightweight K-line artifact. Quote/trade payloads, API contracts,
production ports, remote read-only data sources and account calculations are unchanged.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` and retained the exact-price marker contract.

## Verification

Focused renderer, K-line timeline and Worker tests pass (26 tests). The regenerated `33305774`
sample has a 720px chart, 600 exact-price marker nodes, a Profit zero series, and no browser
console errors or warnings.

## Deployment and rollback

Development-only change on `feature/kln-live-demo`; production services were not restarted. Revert
the change commit to restore the prior marker colors and automatic Profit scale.
