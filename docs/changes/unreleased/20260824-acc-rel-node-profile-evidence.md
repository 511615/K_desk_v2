---
change_id: ACC-REL-017
features: ["ACC-REL-001", "ACC-REL-003", "ACC-DETAIL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add lazy account profiles and auditable relation evidence

## Before and after

Before, Galaxy account selection exposed only the legacy relationship cards and visible edges did not
have one stable, presentation-safe evidence contract. Behavior synchronization could be difficult to
distinguish from identified copy trading. After, selected accounts load a bounded profile, tags,
coverage, account-detail link and up to eight explainable recommendations. Every visible evidence edge
or aggregate relation resolves to a stable detail payload; duplicate evidence is consolidated and
multiple relation families are displayed as a bundle rather than overlapping lines.

## Change

- Added snapshot-bound `node-profile` and `relation-detail` read-only APIs.
- Added centralized `account-profile-v1` behavior rules with minimum-sample protection.
- Preserved nonblank database status and made blank-only `B` fallback explicit.
- Added abortable, sequence-guarded and cached Galaxy profile/relation inspection.
- Renamed same-CRM presentation to `同名账户` and removed SQL, table and internal CRM keys.
- Kept identified copy, open/close synchronization and suspected opposite lock as separate facts.
- Added stable relation deduplication, multi-relation bundles, pagination and coverage disclosure.

## Impact

The existing relationship-network response, Galaxy URL, account-detail URL and port 8777 service
contract remain compatible. The new APIs are additive. Remote AC/DBG sources remain read-only; no MT
Manager state operation or source schema change is introduced. Slow cross-server matching continues in
the existing isolated background expansion and does not block profile interaction.

## Documentation updated

- `ACC-REL-001`
- `ACC-REL-003`
- `ACC-DETAIL-001`
- `docs/PORTS_AND_APIS.md`
- `docs/BUSINESS_RULES.md`
- `docs/TEST_STRATEGY.md`

## Verification

Focused application/API tests, Python compile, Ruff, rendered Galaxy JavaScript syntax, governance
validation and generated registry/OpenAPI checks are required before promotion. The work is verified
in the isolated feature worktree and is not deployed while the independent memory optimization is in
progress.

## Deployment and rollback

Promote only after isolated verification and after the independent memory-optimization change has
finished or been coordinated. Remove the two additive API routes, the relationship-inspection service
and the appended Galaxy inspection layer to roll back. Existing graph responses and account-detail
routes require no data rollback.
