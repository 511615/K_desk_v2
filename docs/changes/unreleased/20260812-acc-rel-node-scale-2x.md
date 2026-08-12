---
change_id: 20260812-acc-rel-node-scale-2x
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Double relationship-graph node size

## Before and after

The relationship graph's account and IB nodes were too small to read the in-node database status and
terminal markers comfortably. Account circles, IB glyphs, database-status badges and terminal badges
now render at 2× the prior canvas radius. The selection hit target remains larger than the visual node,
so the enlarged glyphs are easy to select at normal zoom.

## Impact

This is canvas-only presentation behavior. It does not alter expansion, relationship evidence,
propagation scores, API data, database reads, or write any external or local system.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- API page contract test checks the 2× node scale and enlarged click target.
- Inline JavaScript parsing and the complete K_desk verification suite pass before deployment.

## Deployment and rollback

Restart only the verified production account-service process bound to port 8777. Roll back by
restarting the previous tracked revision; no migration or data rollback is needed.
