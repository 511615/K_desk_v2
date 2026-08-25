---
change_id: 20260825-2350-acc-rel-galaxy-node-hit-priority
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Make visible Galaxy accounts win over relationship-track clicks

## Before and after

An expanded account node is painted at twice its base size, while the interaction frame still used
the smaller pre-scale radius. A click on a visible node edge could therefore be classified as a
relation-track click and collapse the community instead of selecting the account. The old expanded
track marker also had higher priority than nodes.

## Change

The single capture dispatcher now resolves a live visible account before every other target and uses
the painted node radius plus a small pointer allowance. Expanded tracks no longer draw or register a
separate marker. Both collapsed and expanded relation arcs toggle only when their empty band is
clicked; a visible account node always selects and highlights that account.

## Impact

This is a Galaxy interaction correction only. Relationship discovery, propagation, evidence,
read-only sources, APIs, and account data are unchanged.

## Documentation updated

Updated the `ACC-REL-001` relationship-network and `ACC-REL-003` score-propagated investigation
current-state documents with the rendered-node-first hit rule and empty-band-only track toggle.

## Verification

The Galaxy API/page regression pins the rendered-radius helper, visible-node-first dispatcher path,
and relation-track toggle. The embedded JavaScript syntax and deployed browser interaction must be
checked before release.

## Deployment and rollback

Promote the verified dev commit and release from clean `main`. Rollback restores the prior application
revision and restarts 8777; no data migration or external-state rollback is required.
