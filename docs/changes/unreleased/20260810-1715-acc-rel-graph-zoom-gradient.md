---
change_id: 20260810-1715-acc-rel-graph-zoom-gradient
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: improvement
status: unreleased
compatibility: compatible
---

# Spreadable relationship-graph rendering

## Before and after

The relationship graph used a compact force layout and always rendered every edge label, which made
dense account clusters difficult to read. It now has a materially larger preferred edge distance and
repulsion radius, automatically fits the resulting full graph, and exposes mouse-wheel zoom plus
drag-to-pan for detailed inspection. Edge labels appear after zooming in so the overview remains
uncluttered while relationship types remain directly inspectable.

The subject account is always bright red. Other expandable accounts use a score-driven red-to-light
orange gradient, and accounts retained only as a stopped propagation clue are green.

## Impact

This changes only the `/kuzu-risk` canvas presentation. The propagated score, threshold rule,
relationship data, Kuzu projection, API shape, source routing, and read-only guarantees are unchanged.

## Documentation updated

Updated ACC-REL-001 and ACC-REL-003 current-state documents for the wide layout, colour semantics,
and graph navigation behavior.

## Verification

The account page contract test asserts that the returned Kuzu page contains the score colour function
and wheel-zoom handler. Fast and Full governed verification are run before deployment.

## Deployment and rollback

Deploy through the existing account-only `8777` startup path. Roll back by restarting `8777` from the
previous application commit; no database, Kuzu source, or remote-trading state is modified.
