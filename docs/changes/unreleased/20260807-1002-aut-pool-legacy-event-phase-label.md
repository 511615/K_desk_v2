---
change_id: 20260807-1002-aut-pool-legacy-event-phase-label
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Legacy event phase label compatibility

## Before and after

The first event-cause release required the additive `decision` field before using a known failure
phase. A still-running older 8777 process omits that field even though it exposes `phase`, causing
the UI to fall back to a generic execution-gate message. The phase now determines rebuild, shadow
and AutoTrading failure labels independently of `decision`.

## Impact

This is a frontend compatibility fix only. Producer state, API schemas, order execution and MT
state are unchanged.

## Documentation updated

AUT-POOL-001 now states that event-time phase is authoritative for compatible payloads without an
additive decision field.

## Verification

Frontend helper and mounted-page regressions cover a `pool_rebuild_failed` event with no decision
field and require the explicit zero-target reason.

## Deployment and rollback

Deploy the updated main-branch frontend bundle. Rollback restores the prior phase-plus-decision
behavior and requires no data migration.
