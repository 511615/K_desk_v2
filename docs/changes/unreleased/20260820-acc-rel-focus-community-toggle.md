---
change_id: ACC-REL-014
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Focus relationship community collapse and expansion

## Before and after

Before, the 8977 focus workspace rendered community ellipses as decoration. Clicking their edge did
not change the member/edge projection, so dense investigation results remained visually equivalent to
an all-expanded graph.

After, each community is collapsed by default. It shows one aggregate node, one aggregate edge,
member count and the highest member database status. Clicking the visible dashed boundary, its wider
transparent hit target, or the evidence-panel action expands only that community. Expanded communities
render their member accounts and individual evidence edges; the same action collapses them again.

The group boundary and aggregate node now switch on the primary pointer-down event instead of waiting
for a later click. Snapshot polling computes a stable graph signature and does not rebuild the SVG when
the graph data is unchanged; restarting a query invalidates the preceding polling generation. Panning
and wheel zoom are coalesced to one animation-frame render. A collapsed group's representative edge is
always anchored to the visible investigation subject and aggregate node, so an endpoint hidden by a
different collapsed group cannot leave an orphan line fragment on screen.

Collapsed groups no longer reuse arbitrary source-account coordinates. They are assigned deterministic
radial slots on multiple rings before rendering, so center-to-group spokes have distinct endpoints and
do not inherit crossings from hidden member geometry. Expanded groups keep their member-level layout.
The canvas adds a visible arrowhead to each evidence edge and keeps repeated expand/merge instructions
out of the canvas; the action remains available from the ring hit target and evidence panel.

## Impact

- UI and client-side presentation only.
- No relationship score, expansion rule, API response, database route or read-only constraint changes.
- Production port 8777 is not changed; this record belongs to the named 8977 relationship worktree.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Deployment and rollback

Restart only the 8977 clone service to load the updated server-rendered page. Rollback is removal of
this change from `feature/acc-rel-main-clone-8977`; the 8777 production checkout is unaffected.

## Verification

- Python page module compiles.
- Rendered inline JavaScript passes Node syntax checking.
- API page test pins collapsed/expanded boundary text, widened hit target, aggregate status and 5%
  minimum zoom.
- API page test pins pointer-down activation, unchanged-snapshot render suppression, animation-frame
  viewport rendering and visible-subject aggregate edge anchoring.
- Browser interaction verifies expansion and collapse from the physical ring boundary and confirms
  that an unchanged background poll preserves the existing SVG interaction node.
- 8977 `/api/meta` must continue to report `D:\risk\K_desk_v2_rel_dev` after restart.
