---
change_id: 20260826-0094-acc-rel-fixed-sector-embedded-subsectors
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Embed fixed-sector drill-down inside the mother sector

## Before and after

The initial fixed-sector drill-down retained the outer layer but placed its next layer as a separate
small radial map. It visually resembled a jump to another space and compressed dense child branches.

## Change

- Increase the root sector radius and reserve the inner portion of every populated sector for nested
  detail.
- Keep direct first-layer account instances in the outer portion of their mother sector.
- On account selection, render only that account's immediate next-layer business sectors as smaller
  radial child bands inside the selected mother sector; no external mini-map or inter-space connector
  is drawn.
- Preserve all previously visible outer sectors, profile selection, raw relation IDs, line inspection,
  expansion scores and snapshot data. Child-sector navigation is presentation-only and performs no
  additional relationship-network request.
- Keep the global locator semantically de-duplicated and complete, independent of nested visibility.

## Impact

Read-only client projection and interaction only. Database routing, remote reads, expansion,
propagation, scores, API payloads and relation-detail contracts are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Browser regression checks the outer direct layer, sector evidence expansion, embedded nested layer,
  account profile selection, no extra relationship expansion request and complete de-duplicated locator.
- Visual browser artifact is reviewed for the absence of external child canvases and cross-space lines.

## Deployment and rollback

Deploy through the controlled release workflow. Rollback is revision-only; no data migration or
external source effect exists.
