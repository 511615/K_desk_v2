---
change_id: 20260812-acc-rel-database-status-badge
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Render the routed database status in relationship nodes

## Before and after

The relationship graph incorrectly decorated account nodes with the local K_desk ledger `action`.
That is not the `数据库状态` shown in the account risk table. The relationship-core payload now reads
the bounded MT4/MT5 `Login/Status` mapping on the selected account's real data route and preserves it
as `databaseStatus` through the temporary Kuzu projection. Node badges render only that value; a
blank or unavailable value renders as `B`, never as a local action.

## Impact

The status read is one indexed, batched lookup alongside the existing CRM mapping read, not a trade
history scan. The graph remains read-only and does not write any MT4, MT5, CRM, AC, DBG or local
ledger state.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- API projection tests verify root and same-CRM account `databaseStatus` survive Kuzu scoring and
  no `localAction` field is emitted.
- Legacy relationship-core tests verify the routed MT5 status batch is attached to the payload.

## Deployment and rollback

Restart only the verified production account-service process bound to port 8777. Rollback is a
tracked-revision restart; no schema migration or external write is involved.
