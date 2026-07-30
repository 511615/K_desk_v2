---
change_id: 20260729-1610-acc-relationship-network-clarity-performance
features: ["ACC-REL-001", "ACC-DETAIL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# ACC-REL-001: Label evidence edges and smooth node dragging

## Before and after

The network graph previously made operators infer a relationship from the endpoint shapes and the
right-side detail pane. Each visible edge now displays a high-contrast relation-type label directly
on the graph, including same-CRM-user, login-IP, EA/route, Copy and CRM-rebate evidence.

Dragging a node previously rebuilt every SVG node, edge and the evidence pane on every pointer event.
It now updates only the dragged node and its connected paths/labels, limited to one browser animation
frame. Selection, filters, aggregation expansion, pan/zoom and evidence semantics are unchanged.

## Impact

The existing read-only `relationship-network` API and all data evidence are unchanged. This is a
legacy account-page presentation/performance change on the existing localhost `8777` service only;
no remote database, MT4/MT5 Manager or local authority data is written.

## Documentation updated

Updated ACC-REL-001 and the test strategy with visible-edge-label and frame-limited-drag behavior.

## Deployment and rollback

No migration is required. Rollback restores the preceding legacy page implementation and removes
only the additive graph labels/local rendering optimization.

## Verification

Passed on 2026-07-29:

- `scripts/verify_change.ps1 -Mode Fast` completed successfully.
- `scripts/verify_change.ps1 -Mode Full` completed successfully: `302 passed, 1 warning`
  for Python/legacy tests, `20 passed` for frontend tests, and the Vite production build passed.
- Production `8777/8766` was restarted with the governed scripts; both readiness checks passed.
- Browser acceptance at `/account/233015?platform=MT5&server=AC%20CN%20MT5` generated 11 entities,
  19 relationships and 59 evidence entries. Five visible relation labels remained readable during a
  node drag, and `恢复视图` restored the original layout.
