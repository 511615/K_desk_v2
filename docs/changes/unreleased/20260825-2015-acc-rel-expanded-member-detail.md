---
change_id: 20260825-2015-acc-rel-expanded-member-detail
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Expanded same-CRM member labels and relation detail edges

## Problem

Expanding a same-CRM account community restored the member points but left their
account numbers hidden until selection. The visual-endpoint aggregation also kept
member relation lines collapsed, so an operator could not inspect every member's
actual relationship from the canvas.

## Before and after

Before, an expanded community could still use one visual endpoint and one
representative line. After this change, each expanded account point displays its
account number above the node. Every visible original account/IB relation incident
to an expanded same-CRM member is drawn separately and retains the original edge
ID. Clicking that line opens its existing read-only relation evidence detail.

## Impact

- Only `same_crm_user` remains eligible for a collapsible account community.
- LastIP, CID, EA, Copy, rebate, IB and trade facts remain direct relationship
  lines and do not create orbit bands.
- The relationship API, evidence IDs, scoring, source queries and read-only data
  constraints are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`
- `docs/TEST_STRATEGY.md`

## Verification

- Added Galaxy page-contract coverage for expanded account labels and original
  member-edge IDs.
- Added presentation-graph coverage that non-CRM account facts remain direct
  lines rather than relation groups.
- Fast and Full project verification are required before promotion and release.

## Deployment and rollback

This is a development-branch presentation change only until promoted. It can be
reverted independently without changing relationship source data or other account
features.
