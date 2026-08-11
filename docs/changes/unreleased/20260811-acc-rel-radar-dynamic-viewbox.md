---
change_id: 20260811-acc-rel-radar-dynamic-viewbox
features: ["ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Preserve a circular subject-locked radar sweep

## Before and after

Removing SVG letterboxing by non-uniformly stretching a fixed square viewBox aligned the radar
origin, but distorted its circular scan fan into an ellipse on wide graph boards.

## Impact

The radar now sets its SVG viewBox to the Canvas's current pixel width and height and rebuilds the
fan radius from those dimensions. The page retains one-to-one Canvas positioning while preserving a
circular rotating sweep across wide, narrow, resized and relaid-out boards.

## Documentation updated

Updated ACC-REL-003 current-state behavior and relationship-network test expectations.

## Verification

The account-page regression requires dynamic SVG viewBox and scan-fan construction in addition to
subject-coordinate positioning. Fast and Full governed checks are required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No API, database, Kuzu graph, remote provider
or MT Manager state changes. Roll back by restoring the preceding verified account-service commit
and restarting 8777.
