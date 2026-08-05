---
change_id: 20260805-1010-aut-copy-pool-independent-header-clock
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Keep the copy-pool header clock moving during slow dashboard reads

## Before and after

The header timestamp previously rendered `payload.updatedAt`. It could remain unchanged while a
dashboard request was slow or the Producer snapshot was between refreshes, making the operations
clock appear frozen even when the browser and copier were still running.

The header now renders a browser-side clock that checks the local time four times per second and
therefore advances at each visible second boundary independently of API polling. Producer freshness,
source age and stale-state warnings remain separate evidence and are not masked by the local clock.

## Verification

The Vue component test uses fake time to require an exact one-second visible increment without any
dashboard refresh. Existing dashboard, Demo ledger, pool-tier and manual-control tests remain green.

## Impact

Only the copy-pool header timestamp rendering changes. The dashboard contract and every trading,
risk and persistence path remain unchanged.

## Documentation updated

Updated the AUT-POOL-001 current-state UI behavior to distinguish the independent operator clock
from Producer freshness evidence.

## Deployment and rollback

This is a presentation-only change. It does not alter the dashboard API, Producer snapshots, pool
selection, risk gates or Demo execution. Rollback restores the header's snapshot timestamp and removes
the local interval; all trading services continue unchanged.
