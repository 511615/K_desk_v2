---
change_id: 20260826-0090-acc-rel-nearest-visible-edge-hit
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Select the nearest visible Galaxy relationship edge

## Before and after

The Galaxy hit frame checked relationship edges in insertion order. When an expanded same-CRM
member line passed close to a direct-IB root path, a click inside both hit areas could open the
earlier IB edge's relation-display table even though the visible intended line was same-CRM.

## Change

- Retain the existing node, relation-track and blank-canvas priority order.
- Resolve competing relationship-edge hits by the shortest distance to the painted route; an exact
  distance tie selects the later-painted route, which is the visible top relation.
- Extend the production-style Galaxy browser regression to assert both the dispatched
  `relation-display` edge ID and the rendered table label are the clicked raw `same_crm_user` fact.

## Impact

Canvas interaction only. Graph evidence, relationship expansion, scoring, APIs, remote data access,
account data and K-line behavior are unchanged. All data access remains read-only.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Galaxy page contract asserts nearest-edge hit selection.
- The real account 216056 Galaxy flow is run from a fresh QA process three times: expand a same-CRM
  track, click a member line, and verify the sole table request and header both identify
  `同名账户`.

## Deployment and rollback

Deploy through the controlled release workflow. Rollback restores the former insertion-order
edge-hit behavior and requires only a service restart; no data migration or repair is required.
