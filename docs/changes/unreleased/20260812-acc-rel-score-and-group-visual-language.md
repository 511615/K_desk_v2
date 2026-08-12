---
change_id: 20260812-acc-rel-score-and-group-visual-language
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Restore score, shape and relation-family meaning in the overview

## Before and after

The global overview had visible clusters but did not make the distinction between node score, node
identity and cluster relationship type explicit enough. Its minimum zoom was also too high for a
large four-ring result to fit on a smaller display.

Node fill now follows propagated investigation score from red through orange to light yellow, while
threshold-stopped accounts remain green. Node geometry is now explicit: circles are trading accounts,
hexagons are IB identity nodes and diamonds are stopped accounts. Relation bands are independently
coloured and labelled: CRM blue, LastIP purple, EA cyan, Copy pink, rebate gold, IB indigo, same-name
teal and Toxic rose. The wheel minimum is 10%, click hit detection adapts to zoom, and double-click
re-fits the complete map.

## Impact and compatibility

This is a local Canvas/UI change only. Relationship facts, scores, propagation, API responses, Kuzu
projection, source routing and all read-only safety budgets remain unchanged.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` with the independent node-score, node-shape and
relationship-band visual encodings and the extended zoom behavior.

## Verification

The Kuzu page contract test now requires the score palette, node-shape and relationship-theme functions
as well as the visible 10% zoom guidance. Full governed verification is required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No database, CRM, MT4, MT5 Manager, Kuzu persistent
data or 8766 service changes. Rollback is the prior verified account-service commit.
