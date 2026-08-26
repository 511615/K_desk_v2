---
change_id: 20260826-0089-acc-rel-resolve-visual-edge-to-raw-evidence
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Resolve visual Galaxy paths to their raw relationship evidence

## Before and after

Galaxy draws presentation-only root-path lines as well as raw relationship lines. A click on an
overlapping path could send a synthetic `root|...` identifier to the relation-display endpoint. That
identifier is not an evidence edge, causing a 404 and a misleading graph-update notice.

## Change

- Resolve every clicked visual line to its matching raw relationship by ID, endpoints and relation
  type before requesting the shared relation display or legacy evidence panel.
- Retain the raw edge ID through snapshot refresh, so the table remains tied to an auditable
  relationship fact.

## Impact

Click handling only. Graph geometry, expansion, scores, source queries, account/K-line data and all
remote systems remain unchanged and read-only.

## Documentation updated

- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- API page contract requires visual-to-raw resolution before the relation-display request.
- Production Galaxy browser acceptance for account 216056 must show coverage metrics after an
  expanded same-CRM member-line click, never a graph-update notice.

## Deployment and rollback

Deploy through the controlled release workflow. Rollback is the previous client behavior and
restart; no migration or data repair is required.
