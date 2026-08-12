---
change_id: 20260812-acc-rel-preserve-relation-band-colors
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Preserve relationship-band colours while selected

## Before and after

The Kuzu relationship overview now keeps every cluster band in its fixed evidence-family colour,
including when a user selects one of that cluster's members. Selection is represented solely by a
white dashed outline. Bands with sufficient angular space also show their short evidence-family
label, and common relationship aliases are normalised before palette selection. This prevents an
interaction highlight from being mistaken for relationship type and keeps the colour key auditable.

## Impact

This is a Canvas presentation correction. It does not alter scores, expansion, relationships,
source reads, API responses, Kuzu materialisation, or database access.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` with the fixed relationship-band colour, white selection
outline and visible relationship-label behavior.

## Verification

The Kuzu page contract test requires the group-label renderer and the visible white-selection legend.
Fast and Full governed verification are required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No database, CRM, MT4, MT5 Manager, Kuzu
persistent data or 8766 service changes. Roll back to the prior verified account-service commit.
