---
change_id: 20260813-acc-rel-004-edge-hit-community-collapse
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Account relationship graph: clickable edges and canonical communities

- Date: 2026-08-13
- Feature: account relationship risk expansion (`KUZU-REL`)
- Scope: read-only canvas interaction and presentation; no database schema or write path changes.

## Before and after

Same-CRM members were still rendered as one line per account, relation lines other than copy-order
lines had no hit target, and the expand/merge control used inconsistent keys. This made a graph
look like a starburst and made a selected relation community impossible to inspect reliably.

## Impact

- Canonicalize a community as `source account + relation family` (`edgeCommunityKey`).
- In overview and selected-branch views, render one representative edge per community by default;
  preserve `groupCount` and the member nodes. Explicit expand toggles emit the member edges.
- Register every rendered relation edge for hit testing. A click outside a node selects the nearest
  edge, highlights it, and refreshes the detail panel; the existing copy-order evidence dialog remains
  available through the same edge target.
- Use the same community key for detail controls and ring-band toggles so expand/merge does not
  affect unrelated communities.

## Documentation updated

- `docs/features/account/score-propagated-kuzu-investigation.md`
- This change record.

## Deployment and rollback

- Deploy the account service on port 8777 only after verification.
- Roll back by reverting this change record's implementation commit; no database migration is needed.

## Verification

- Extracted page JavaScript passes Node syntax check.
- `tests/test_api.py -k kuzu_risk_page` passes.
- Full production verification and the 8777-only deployment are required before release.
