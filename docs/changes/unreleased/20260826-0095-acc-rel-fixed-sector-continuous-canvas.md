---
change_id: 20260826-0095-acc-rel-fixed-sector-continuous-canvas
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Make fixed-sector investigation a continuous canvas

## Before and after

The fixed-sector projection inherited the Galaxy canvas magnifier limits (10%–250%). Dense nested
sectors could therefore look oversized while the operator could not zoom far enough out for context
or far enough in to inspect a packed mother sector.

## Change

- Give only `graph_type=fixed-sector` a broad 0.2%–256× pointer-centred zoom range and retain
  unconstrained drag pan.
- Keep parent sectors, embedded child sectors, account instances and raw evidence lines under the
  same Canvas transform; double-click restores the complete root fit.
- Reduce default fixed-sector account radii and cap evidence-line hit tolerance in screen space so a
  high zoom remains selectable without a large invisible click area.
- Replace the long canvas instruction paragraph with a compact interaction/status caption.

## Impact

Presentation and interaction only. The expansion request key, read-only source queries, scores,
snapshot payload, global locator, node profile and relation-display request IDs are unchanged. Galaxy
and focus-force keep their existing zoom limits and layouts.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Fixed-sector Playwright regression proves zoom travels above the former 250% cap and below the
  former 10% floor, then double-click refits before sector expansion and nested account navigation.
- The same regression retains the no-extra-query assertion, complete de-duplicated locator assertion,
  nested mother-sector assertion and node-profile assertion.
- Visual artifact is reviewed after the real fixed-sector route completes.

## Deployment and rollback

Deploy through the controlled release workflow. Rollback is revision-only; no data migration, remote
write, source-routing or account-state change is involved.
