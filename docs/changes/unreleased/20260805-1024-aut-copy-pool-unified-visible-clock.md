---
change_id: 20260805-1024-aut-copy-pool-unified-visible-clock
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Use one visible clock across the copy-pool header

## Before and after

The top-right status clock used the browser-side ticking clock while the pinned Demo account identity
line still rendered the last account snapshot timestamp. Both values were unlabeled wall-clock times,
so their expected refresh cadence was unclear and they visibly diverged.

Both locations now render the same reactive browser clock. Snapshot freshness remains available only
through the dedicated stale-state, source-age and account-data indicators.

## Impact

This changes presentation only. Dashboard data, Demo snapshots, trading state, risk gates and order
execution are unchanged.

## Verification

The Vue fake-time regression supplies an intentionally old Demo snapshot timestamp, then requires the
page clock and Demo identity clock to match before and after an exact one-second advance.

## Documentation updated

Updated the AUT-POOL-001 UI contract to require one shared visible clock across both header locations.

## Deployment and rollback

Deploy by rebuilding the frontend and restarting only 8777. Rollback restores the Demo identity line's
snapshot timestamp; Producer and Demo execution do not require a restart in either direction.
