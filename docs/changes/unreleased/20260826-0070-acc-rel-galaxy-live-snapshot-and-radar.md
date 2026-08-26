---
change_id: 20260826-0070-acc-rel-galaxy-live-snapshot-and-radar
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Repair Galaxy live-snapshot relationship inspection

## Before and after

Galaxy retained relation edges from earlier expansion snapshots. A line that had already been
replaced by newer evidence could remain visible and clickable, while the relation-display endpoint
correctly rejected that old edge with a 404 or a snapshot 409. The shared table then showed the raw
technical error. The Galaxy reuse of the focus-view radar also painted a full-canvas scan wedge that
looked like an erroneous relation line. Finally, the legacy detail control could offer a community
toggle for non-CRM relations.

Galaxy now preserves returned account nodes for orientation but replaces its relation-edge set from
the newest snapshot. A stale click synchronises the graph and shows an explicit non-technical update
notice; a current edge opens the usual populated relation table. The scan fan is removed from Galaxy,
and only same-CRM controls can expand a relationship community.

## Change

- Replace, rather than accumulate, Galaxy relation edges on incremental snapshots.
- Let active expansion table reads use the newest snapshot; complete snapshots remain revision-bound.
- Refresh/retry stale reads safely and render a graph-synchronised notice if the exact edge vanished.
- Remove the Galaxy radar fan and retain text-only progress.
- Add a real 216056 Playwright regression that opens a same-CRM track and an actual current IB line.

## Impact

This is a client presentation and read-only snapshot-recovery repair. It does not change source
evidence, relationship propagation, scoring, database routing, API schemas or remote state.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`
- `docs/TEST_STRATEGY.md`

## Verification

- API/page renderer tests cover same-CRM-only expansion, current-edge replacement, snapshot recovery
  and no Galaxy radar overlay.
- The real 216056 Galaxy browser test verifies collapsed/expanded screenshots, account labels,
  constrained internal CRM lines and a populated IB relation-display table.
- Full repository verification and production visual validation are required before handoff.

## Deployment and rollback

Deploy through the standard development promotion and production release scripts. No migration or
remote-state rollback is required; a release rollback restores only the prior client presentation.
