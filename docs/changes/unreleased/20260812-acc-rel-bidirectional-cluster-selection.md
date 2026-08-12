---
change_id: 20260812-acc-rel-bidirectional-cluster-selection
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Resolve symmetric relationship clusters from every selected member

## Before and after

Selected-branch highlighting used the graph's first-discovery parent orientation. This made a member
of a symmetric same-CRM, LastIP, EA, Copy, same-name or Toxic group show a smaller result than a
different member of the same group.

Selection now first resolves the selected evidence-family component bidirectionally, then follows
the displayed discovery tree outward from every member of that component. Hierarchy and direct-IB
rebate branches remain directional and their relationship lines carry arrowheads. An obsolete duplicate
overview renderer was removed so there is one authoritative selection renderer.

## Impact

This corrects Canvas selection semantics only. It does not change score propagation, query traversal,
visible graph membership, source reads, APIs, Kuzu materialisation or database behavior.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` with the bidirectional symmetric-cluster and directional
hierarchy presentation rules.

## Verification

The Kuzu page contract test requires the relationship-cluster and relation-direction renderers and
asserts that only one overview renderer remains. Fast and Full governed verification are required
before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No database, CRM, MT4, MT5 Manager, Kuzu persistent
data or 8766 service changes. Roll back to the prior verified account-service commit.
