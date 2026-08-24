---
change_id: ACC-REL-016
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Galaxy community bridge rendering

## Before and after

Before, a collapsed outer-ring community could remain visually disconnected when all member-level
route edges were hidden by aggregation. After, each multi-member community receives the complete
visible subject-to-owner path and one final bridge from its actual parent account or parent community
to the visible community anchor when no equivalent route edge is already present.

## Change

The Galaxy compatibility renderer now maps every segment of the community owner's score-ledger
route to visible collapsed representatives, then adds one final presentation-only bridge to the
community anchor. If the source route is unavailable it uses an explicitly unresolved connector;
neither form creates database evidence, alters propagation scores, or expands singleton scattered
nodes.

When a community is expanded, its ring band remains visibly drawn as the collapse target, but is removed
from the member hit-test layout. Visible member nodes therefore receive click priority and can be
selected to show their path to the subject; clicking the retained community band toggles collapse.

## Impact

- UI presentation only; no score, expansion rule, API response or database query changes.
- The 8977 relationship clone is changed; production port 8777 is untouched.

## Documentation updated

- docs/features/account/score-propagated-kuzu-investigation.md
- docs/changes/unreleased/20260821-acc-rel-galaxy-community-bridges.md

## Deployment and rollback

Restart only the 8977 clone with scripts/stop_clone_8977.ps1 and scripts/start_clone_8977.ps1.
Rollback is removal of this unreleased change from the relationship clone; no production rollback
is required.

## Verification

- Python syntax compilation passed for kuzu_risk_page.py.
- Galaxy API/page regression tests passed.
- Expanded-member click precedence and band-hit guard are covered by page/static verification.
- 8977 clone restarted and returned HTTP 200.
- Production 8777 remained unchanged and returned HTTP 200.
