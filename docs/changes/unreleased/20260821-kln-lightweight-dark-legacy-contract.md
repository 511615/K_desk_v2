---
change_id: 20260821-kln-lightweight-dark-legacy-contract
features: ["KLN-RENDER-001"]
change_type: compatibility
status: unreleased
compatibility: compatible
---

## Before and after

The prior development sample mixed the old renderer's layout with a simplified control contract.
The renderer now follows the supplied production artifact's behavior: paired `隐藏停盘 / 显示停盘`
controls, display limit in the toolbar, a separate filter row, overlay pane controls, visible-range
status, legacy marker semantics and aggregate Profit-bar behavior. The visual shell is the approved
dark TradingView-style presentation.

## Impact

Only standalone development artifacts change. Quote routing remains external/cache-only and no
production service, remote database or MT terminal is modified.

## Documentation updated

Updated the Lightweight renderer feature contract with the production-reference behavior and dark
presentation rule.

## Verification

Renderer, K-line and Worker tests pass. A real cached account artifact was opened on the isolated
service; no browser errors occurred. Paired gap controls, Profit aggregation and the position pane
were exercised.

## Deployment and rollback

The change remains on `feature/kln-live-demo` and does not restart `8777/8766`. Reverting this
commit restores the preceding development presentation.
