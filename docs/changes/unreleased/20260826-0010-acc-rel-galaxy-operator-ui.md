---
change_id: 20260826-0010-acc-rel-galaxy-operator-ui
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: improvement
status: unreleased
compatibility: compatible
---

# Galaxy operator UI hierarchy

## Problem

The Galaxy page used duplicate header hints and exposed raw coverage prose in the selected-account
profile. Fixed desktop column widths also caused horizontal scrolling on narrower workstations.

## Before and after

- Removed the duplicate workflow and rule-status header text.
- Rebuilt the filters as a compact responsive control strip.
- Made the Galaxy three-panel workspace fit narrow desktop widths without a horizontal-scroll layout.
- Pinned a concise account profile at the top of the right panel: identity, database status, score,
  layer and expansion outcome.
- Removed the raw coverage card from that profile; auditable coverage remains in relationship evidence.
- Rephrased the selected-account context as a short operator-facing statement.

## Impact

The change affects only `graph_type=galaxy` presentation. Account discovery, relation evidence,
propagated scores, click semantics and all API responses are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

The page contract test checks the compact-presentation hook, the removed status element and the
plain-language profile renderer. Browser acceptance verifies the deployed page at desktop width.

## Deployment and rollback

This is presentation-only. No API, propagation, source-query or scoring behavior changes. Revert the
single feature commit to restore the previous layout.
