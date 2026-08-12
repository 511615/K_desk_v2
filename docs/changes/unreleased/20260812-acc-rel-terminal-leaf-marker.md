---
change_id: 20260812-acc-rel-terminal-leaf-marker
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Make completed relationship leaves visible in the overview

## Before and after

The score gradient kept high-propagation scores too close to the same red hue. Also, a first-ring
account that met the threshold and was queried but produced no new account child could appear as an
ordinary red account; the tiny check indicator was not reliable at overview scale.

The node score palette now covers red, orange, gold and yellow-green with a stronger hue separation.
After a complete, non-truncated discovery, each non-subject account without an account child receives
a large dark-green `叶` badge. A threshold-stopped account remains a green diamond with `止`; the two
terminal states are therefore distinguishable.

## Impact and compatibility

This is a Canvas presentation correction. It changes no discovery paths, evidence, scores, graph
membership, API contracts, source queries or read-only safety budgets.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` with the stronger score gradient and explicit terminal-leaf
definition.

## Verification

The page contract test requires the terminal-state and terminal-badge rendering functions and visible
leaf wording. Full governed verification is required before deployment.

## Deployment and rollback

Deploy by restarting only 8777. No database, CRM, MT4, MT5 Manager, Kuzu persistent data or 8766
service changes. Roll back to the preceding verified account-service commit.
