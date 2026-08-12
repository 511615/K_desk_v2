---
change_id: 20260812-acc-rel-visible-ring-layout
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Render every discovered relationship node distinctly in the overview

## Before and after

The concentric overview allocated positions by relationship-family sector. A dense family could put
many accounts at nearly identical coordinates, so the ring count could report dozens of nodes while
only a few dots were visually distinguishable.

Every returned account and concrete IB-identity node is now assigned one deterministic position on
the full circumference of its logical discovery ring. The board expands on desktop for deeper graphs,
reports the node/account total, and keeps the existing pointer-centred zoom, pan, selected-path and
detail behaviors. Relation type remains visible in the detailed evidence panel; it no longer controls
the global-node position.

## Impact and compatibility

This is a client-only presentation correction. It does not change relationship discovery, score
propagation, source routing, Kuzu projection, database access, response fields, or safety budgets.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` to record the one-node-per-coordinate global overview,
the removal of relationship-family sectors, and the visible total count.

## Verification

The Kuzu page contract regression asserts the new ring-layout function and visible-node operator
message. Full governed verification is required before production restart.

## Deployment and rollback

Deploy by restarting only the 8777 account service after verification. No database, CRM, MT4, MT5
Manager, Kuzu persistent data, or 8766 K-line service is changed. Rollback is the previous verified
account-service commit.
