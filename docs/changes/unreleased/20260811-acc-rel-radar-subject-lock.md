---
change_id: 20260811-acc-rel-radar-subject-lock
features: ["ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Lock the expansion radar to the problem account

## Before and after

The expansion radar was centered on the geometric center of the board. The problem account has a
deliberate off-center graph coordinate and can move on screen when the operator zooms or pans, so
the scan origin could no longer identify the active investigation account.

## Impact

Each graph redraw now projects the subject account's world coordinate through the current camera and
sets the radar SVG origin to that on-screen coordinate. The radar remains decorative and non-
interactive while following resize, relayout, zoom and pan.

## Documentation updated

Updated ACC-REL-003 current-state behavior and relationship-network test expectations.

## Verification

The account-page regression requires the subject-coordinate positioning helper and its radar SVG
transform. Fast and Full governed checks are required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No API, database, Kuzu graph, remote provider
or MT Manager state changes. Roll back by restoring the preceding verified account-service commit
and restarting 8777.
