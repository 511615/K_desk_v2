---
change_id: 20260824-acc-rel-cid-and-same-name-display
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: change
status: unreleased
compatibility: compatible
---

# ACC-REL current CID and same-name presentation

- Feature IDs: `ACC-REL-001`, `ACC-REL-003`
- Scope: isolated 8977 relationship-network clone only.
- Added read-only MT5 same-server current `ClientID` (CID) peer discovery. Zero/null CID is ignored;
  MT4 and order-comment CID are not inferred.
- Reused the LastIP cohort controls: one lookup per cohort, bounded query timeout and heavy EA/Copy
  reuse for known cohort members.
- Renamed public same-CRM evidence to `同名账户` and removed internal CRM table/`user_id` wording from
  the detail panel.
- Added unit coverage for CID peer discovery, zero suppression, propagation and sanitized same-name
  evidence. Existing API and source routes remain backward-compatible.

## Before and after

Before, current MT5 CID peers were absent and same-CRM evidence exposed internal terminology. After, bounded CID
cohorts are available and the public relationship is presented as `同名账户` without raw schema identifiers.

## Impact

Adds read-only relationship evidence and simplifies display text; existing response fields and routes remain compatible.

## Documentation updated

Updated `ACC-REL-001`, `ACC-REL-003`, routing documentation, test strategy and this change record.

## Verification

CID peer, zero-suppression, propagation, sanitized evidence and API regression tests cover the change.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back the release snapshot to disable CID discovery.
