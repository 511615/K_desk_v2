---
change_id: 20260826-0040-acc-rel-no-cross-community-expanded-edges
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Keep expanded CRM bands free of cross-community raw edges

## Before and after

Expanding a same-CRM Galaxy band added every visible raw account/IB edge incident to a member. IB
edges spanning logical rings were therefore redrawn across the whole workspace with large labels and
arrows, obscuring the star-track and making the expanded view unusable.

The expanded band now reveals its account members and numeric labels only. It does not inject
cross-community raw edges; those facts retain their normal relationship-track projection and existing
selectable local evidence lines remain available.

## Impact

This is a Galaxy presentation and interaction fix only. Relationship evidence, API payloads,
propagation, aggregation eligibility, selection semantics and data routing are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Replaced the Galaxy contract test that required injected raw member edges with one that prohibits
  them while retaining labels for expanded account members.
- Full repository verification and production browser inspection are required before release.

## Deployment and rollback

Deploy through the standard promotion and release scripts. Reverting restores the previous expanded
edge projection; no data migration or remote write is involved.
