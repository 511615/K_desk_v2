---
change_id: 20260811-acc-rel-radar-progress
features: ["ACC-REL-003"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Show live relationship-expansion progress in the overview

## Before and after

The concentric relationship overview showed only a text progress message while background evidence
expansion was running. It did not provide an immediately visible indication that the screen was
still polling and discovering accounts.

## Impact

The canvas board now receives a translucent rotating radar sweep while its visible status is
`后台扩散中`. The animation continues across polling updates and automatically disappears when the
job is complete, failed or idle. The overlay never receives pointer input, so selecting nodes,
wheel zoom and drag pan retain their existing behaviour.

## Documentation updated

Updated ACC-REL-003 current-state behavior and the relationship-network regression authority.

## Verification

The account-page API regression verifies the page includes the accessible radar overlay, indefinite
animation, status observer and non-intercepting pointer behavior. Fast and Full governed checks are
required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No API, database, Kuzu projection, MT Manager
or remote provider state changes. Roll back by restoring the previous verified account-service
commit and restarting only 8777.
