---
change_id: 20260811-acc-rel-radar-aspect-ratio
features: ["ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Align the subject-locked radar with the wide Canvas board

## Before and after

The radar SVG kept its default square aspect ratio inside a wide graph board. Its calculated
percentage origin was correct in the SVG coordinate system, but browser side padding shifted the
visible sweep origin left of the problem-account Canvas node.

## Impact

The overlay SVG now fills the board's non-uniform coordinate plane. Radar percentage coordinates
therefore map one-to-one with Canvas coordinates, keeping the rotating sweep visibly centered on
the subject node on wide, narrow and resized boards.

## Documentation updated

Updated ACC-REL-003 current-state behavior and relationship-network test expectations.

## Verification

The account-page regression now requires the SVG aspect-ratio override alongside subject-coordinate
positioning. Fast and Full governed checks are required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No API, database, Kuzu graph, remote provider
or MT Manager state changes. Roll back by restoring the preceding verified account-service commit
and restarting 8777.
