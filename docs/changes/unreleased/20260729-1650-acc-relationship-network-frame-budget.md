---
change_id: 20260729-1650-acc-relationship-network-frame-budget
features: ["ACC-REL-001", "ACC-DETAIL-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# ACC-REL-001: Coalesce relationship-network interaction rendering

## Before and after

The relationship graph already limited node drawing to animation frames, but pointer movement still
calculated SVG coordinates before that frame, scanned every visible edge, and left pan and wheel
transforms unbounded. A completed node drag also reached the node click handler, rebuilding the
complete SVG and evidence pane.

Pointer input now records only the latest coordinates until the next animation frame. Node movement
uses a prebuilt incident-edge index; pan and zoom also coalesce stage transforms. Movement of four or
more screen pixels suppresses the post-drag click. Ordinary node and edge selection changes the local
selection classes and evidence pane without recreating graph DOM. Filter changes, aggregate expansion
and reset retain their existing full-render behavior.

## Impact

This is a legacy account-page rendering optimization on `127.0.0.1:8777`. The relationship API,
evidence, labels, filtering, aggregation, data routing and all read-only provider behavior are unchanged.
No local authority data or remote database/MT state is written.

## Documentation updated

Updated ACC-REL-001 and the relationship-network performance regression requirements in the test
strategy.

## Verification

Passed on 2026-07-29:

- Full verification completed: `302 passed, 1 warning` for Python/legacy tests, `20 passed` for
  frontend tests, and the Vite production build passed.
- Production `8777/8766` was restarted with the governed scripts; both readiness checks passed.
- Browser acceptance at `/account/233015?platform=MT5&server=AC%20CN%20MT5` generated 11 entities,
  19 relationships and 59 evidence entries. A 25-point drag moved a non-selected account while the
  selected subject remained unchanged and all five relation labels remained visible. Node selection,
  frame-limited pan, wheel zoom, relation-type filtering and reset all completed successfully.

## Deployment and rollback

Restore the previous legacy relationship interaction block and restart only the K_desk web processes.
No migration or data restoration is required.
