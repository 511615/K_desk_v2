---
change_id: ACC-REL-017
features: ["ACC-REL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Galaxy duplicate-edge rendering fix

## Root cause

The Galaxy page has several compatibility, community-bridge and root-chain render layers. The
same logical evidence could reach the canvas more than once, and the selected-edge overlay made
the duplicate look like a second relationship. The old render boundary keyed only on the raw
edge object and did not canonicalize endpoint direction or relation-family aliases.

## Change

The final canvas render boundary now canonicalizes each edge by endpoint pair and normalized
relation family. Symmetric evidence uses an unordered endpoint pair; directed IB/ownership
evidence keeps source and target direction. A duplicate is skipped before drawing and before
adding the edge to hit-testing, so it cannot create a second visible curve or a second clickable
target. Distinct relation families remain separate and retain their own labels and colours.

The selected-edge white dashed overlay remains disabled; selection is represented by the existing
node/path/evidence-panel state rather than a second line.

## Verification

- `py_compile` passed for `src/kdesk/api/kuzu_risk_page.py`.
- Galaxy page/API regression test passed (`tests/test_api.py -k 'legacy_galaxy or galaxy_page or galaxy'`).
- Served 8977 page returned HTTP 200 and contains the canonical render deduplication code.
- Production port 8777 was not modified or restarted.

## Rollback

Remove this unreleased change from the 8977 relationship clone and restart only the clone.

## Before and after

Before, duplicate logical evidence could render as parallel lines. After, the final render boundary
canonicalizes visible endpoints and relation families so one logical relationship renders once.

## Impact

Presentation and hit-testing only; relationship discovery, scoring, API contracts and source data are unchanged.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` current-state relationship documentation and this change record.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back to the preceding release snapshot if
duplicate-edge rendering or interaction regressions occur.
