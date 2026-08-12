---
change_id: 20260812-acc-rel-directed-labels-and-local-actions
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Clear directed IB links and local account marks

## Before and after

Directed relationship lines showed only short text such as `IB 本人 →`, which did not identify the
source and target accounts. Trading nodes also lacked the operator's local action mark. Directed
lines now show `来源 → 目标（业务关系）`, including an explicit `直属上级 IB 本人账户` wording. Each
rendered trading account receives an additive `localAction` from the newest local ledger row; blank
or `待定` displays as `B`, and `T`/`TA`/`A` have a high-visibility ring.

## Impact

The relationship graph remains read-only. The action lookup is indexed, batched below SQLite's
variable limit and copies the response before decoration, so it neither scans the ledger nor mutates
the cached relationship-expansion result. Existing endpoint fields and rendering semantics remain
compatible.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Focused API tests verify that local action is added to relationship entities and the page includes
  directed-label and action-badge rendering functions.
- Full Python, frontend and governance verification is required before deployment.

## Deployment and rollback

Restart only the verified production account-service process bound to port 8777. Roll back by
restarting the previous tracked revision; no schema migration or external-system write is involved.
