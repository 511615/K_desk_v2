---
change_id: 20260812-acc-rel-selected-branch-edges
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Show the selected account's outward relationship branch

## Before and after

The Kuzu overview only displayed the selected account's ancestry route back to the problem account.
It did not make the already discovered outward path from that selected account visible, so operators
could not inspect how that node subsequently propagated into outer rings.

Selecting a non-root node now highlights its full discovered branch: its route from the problem account
and every descendant reachable through the graph's displayed parent relation. Each highlighted segment
is rendered with the fixed evidence-family colour and a compact readable relationship label.

## Impact

This is a Canvas-only presentation enhancement. It changes no score, traversal, relationship,
source-read, API, Kuzu-materialisation, or database behavior.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` with the selected account's outward-branch and labelled-edge
behavior.

## Verification

The Kuzu page contract test requires the selected-branch and labelled-edge renderers, including the
visible outward-branch guidance. Fast and Full governed verification are required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No database, CRM, MT4, MT5 Manager, Kuzu persistent
data or 8766 service changes. Roll back to the prior verified account-service commit.
