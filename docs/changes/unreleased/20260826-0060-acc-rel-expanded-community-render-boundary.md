---
change_id: 20260826-0060-acc-rel-expanded-community-render-boundary
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Restore the Galaxy expanded-community render boundary

## Before and after

The previous selectable internal-evidence repair switched render endpoint keys from a collapsed
same-CRM community to every member whenever that community was expanded. That switch was applied to
all incident relationship edges, not just the recovered internal `same_crm_user` evidence. Existing
cross-community IB, rebate and other tracks were therefore redrawn as many long individual curves,
creating duplicate arrows, stacked labels and an unusable Galaxy canvas.

The shared relation-display table also showed a terminal stale-snapshot message when its graph
snapshot advanced between an edge click and the table request, although the page could safely refresh
the current read-only snapshot.

After this repair, ordinary relations retain one collapsed-community star-track endpoint whether the
band is open or closed; only source-ID-backed internal CRM evidence is shown member-to-member.
The first stale table request refreshes the graph and retries its selected edge once.

## Change

Galaxy keeps the normal community endpoint for every ordinary relation, whether the same-CRM band is
collapsed or expanded. Only the explicitly recovered, source-ID-backed internal `same_crm_user`
evidence uses its individual account endpoints. This restores one star-track projection for all
cross-community facts while preserving selectable local CRM evidence lines.

The shared relation-display panel now refreshes the graph and retries the exact edge once on a 409.
It leaves a second conflict visible, preventing both retry loops and cross-revision evidence mixing.

## Impact

This is a presentation and stale-read recovery repair only. The relationship API schema, source
evidence, propagation, scoring, snapshot semantics, data routing and all remote data access remain
unchanged and read-only.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`
- `docs/TEST_STRATEGY.md`

## Verification

- Galaxy renderer contracts pin that only `expandedCommunityEvidence` uses raw member endpoints.
- Renderer contracts pin the one-time stale-snapshot callback in both focus and Galaxy views.
- Full repository verification and controlled production release are required before handoff.

## Deployment and rollback

Deploy through the standard development promotion and production release scripts. No migration or
remote-state rollback is required; a release rollback restores only the prior client presentation.
