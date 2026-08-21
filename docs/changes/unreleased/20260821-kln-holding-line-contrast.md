---
change_id: 20260821-kln-holding-line-contrast
features: ["KLN-RENDER-001"]
change_type: ui
status: unreleased
compatibility: compatible
---

## Before and after

Holding lines were rendered with a low-alpha purple that blended into the dark grid when many
orders were visible. They now use a brighter purple and density-aware opacity/width while retaining
the legacy dashed style and the same open/close price endpoints.

## Impact

Only visual contrast changes in the isolated Lightweight K-line artifact. Order mapping, price
coordinates, Profit values, quote payloads and production services are unchanged.

## Documentation updated

Updated `docs/features/kline/lightweight-renderer.md` with the contrast contract.

## Verification

Focused renderer, K-line timeline and Worker tests pass (26 tests). The regenerated sample shows the
brighter dashed lines and browser console errors/warnings remain empty.

## Deployment and rollback

Development-only change on `feature/kln-live-demo`; production was not restarted. Reverting this
commit restores the prior low-alpha purple line style.
