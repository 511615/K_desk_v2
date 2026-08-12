---
change_id: 20260812-acc-rel-ib-direct-rebate-expansion
features: ["ACC-REL-003"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Expand through an IB's direct rebate personnel

## Before and after

The relationship graph could show a discovered trading account that belonged to an IB, but did not
materialize that IB as a graph node or use its directly evidenced rebate personnel as a follow-on
branch. This could hide an otherwise valid path such as a trading account to its CRM IB identity and
then to the IB's direct rebate accounts.

The graph now creates an explicit IB identity node when the owning CRM user has direct rebate
evidence. It emits each grouped direct rebate payee as a real account node, then lets eligible
accounts continue the existing IP, EA, Copy, CRM, rebate and optional Toxic discovery flow.

## Impact and compatibility

The CRM read is read-only and uses an exact `rebate_ib_id` index predicate. It groups raw rebate
rows to one account edge, has no time-history export, and limits one IB branch to 2,000 account
nodes. A branch that exceeds this safety limit is retained as explicitly truncated; the existing
global node, scoring and Kuzu projection safeguards remain in effect. Top-IB aggregates remain
aggregate-only and do not emit broad historic downlines.

Two directed graph relations are added: `ib_identity` is a lossless account-to-IB role projection,
and `ib_direct_rebate` carries the normal direct-rebate strength. They cannot feed score back into
their originating route, preventing visual role nodes from artificially increasing a score.

## Documentation updated

Updated ACC-REL-003 behavior, scoring and data-routing documentation. The overview now includes
concrete IB identity nodes as hexagons and explains the direct-rebate path in the detail panel.

## Verification

Focused propagation, relationship-risk and API tests pass. The new CRM aggregation was parsed,
and its read-only MySQL `EXPLAIN` selected the `rebate_ib_id` / `idx_covering` access path. Fast and
Full governed verification are required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 production account service after governed verification. No
database, CRM, MT4, MT5 Manager or Kuzu persistent data is written. Roll back by restoring the
preceding verified application commit and restarting 8777.
