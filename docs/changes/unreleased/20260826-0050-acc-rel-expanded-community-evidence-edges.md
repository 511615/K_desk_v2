---
change_id: 20260826-0050-acc-rel-expanded-community-evidence-edges
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Restore selectable evidence inside expanded CRM bands

## Problem

The preceding cross-community clutter guard removed injected raw member edges entirely. When an
operator expanded a same-CRM Galaxy band, the member accounts appeared but their own relationship
lines were absent, and a line that did remain could resolve to a synthetic aggregate rather than its
source evidence detail.

## Before and after

Before, expanding a CRM band showed the account points without their internal original relation
lines; the prior clutter guard correctly stopped cross-community arrows but was too broad. After,
the band restores only its internal same-CRM evidence lines, and each line opens the matching
relation detail.

## Change

Galaxy now restores only original `same_crm_user` evidence where both endpoints are visible members
of the same explicitly expanded community. It uses the raw relation ID for hit testing and evidence
inspection. The render-boundary deduplication also switches back to individual endpoint IDs for an
expanded band, while collapsed bands still deduplicate to their shared star-track endpoint.

Cross-community, cross-ring and member-to-IB raw edges are still excluded from this recovery pass;
they retain their normal relationship-track projection and cannot create the long arrows that the
previous fix removed. Internal recovered edges have no repeated canvas caption until selected, so
the track remains legible and the clicked relation detail supplies the evidence wording.

## Impact

This is a Galaxy presentation and click-hit repair only. The relationship API, evidence payload,
propagation, scoring, data routing and all remote data sources remain unchanged and read-only.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Added a Galaxy rendering contract that requires same-community endpoint checks, raw evidence IDs,
  expanded-member visibility and the selectable-edge focus bypass.
- The contract also rejects cross-community raw-edge recovery by requiring the source relationship
  family to match the expanded community family.
- Full repository verification and browser inspection of an expanded community are required before
  release.

## Deployment and rollback

Deploy through the standard development promotion and production release scripts. Releasing the
immediately previous production commit rolls back only this presentation behavior; no migration or
remote write is involved.
