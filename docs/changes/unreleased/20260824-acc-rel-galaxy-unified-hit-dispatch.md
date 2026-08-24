---
change_id: 20260824-acc-rel-galaxy-unified-hit-dispatch
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# ACC-REL-023 — Galaxy unified hit dispatcher

- Features: `ACC-REL-001`, `ACC-REL-003`
- Scope: `K_desk_v2_rel_dev` clone on port `8977` only
- Status: implemented, awaiting user acceptance

## Problem

The compatibility galaxy canvas had accumulated multiple capture- and bubble-phase click listeners.
Several listeners also called the mutating ring layout function during hit testing. The same gesture
could therefore see different coordinates, trigger more than one action, or be consumed by the wrong
node, group or edge target.

Collapsed community members also retained their original account IDs in the render-edge key even
though they shared one visible group anchor. This allowed multiple edges of the same relation family
to survive deduplication and appear as two or more lines to one collapsed group.

## Change

Add one earliest capture-phase dispatcher that consumes every galaxy canvas click. Its targets are
rebuilt once after each completed render and remain immutable until the next render. The fixed hit
priority is collapse marker, visible node, collapsed group boundary/anchor, relation edge and blank
canvas. Hidden collapsed members are not node targets, and click classification never calls layout.
Legacy listeners remain in place for source compatibility but cannot receive a dispatched click.
Render-edge deduplication now uses the visible endpoint identity: expanded accounts keep their own
IDs, while every hidden member of a collapsed community resolves to the same `group:<group_key>`
endpoint. Different relation families remain separate, but duplicate same-family lines are removed.

## Verification

- API regression test locks the dispatcher, immutable frame and hit priority.
- API regression test locks visible-endpoint edge deduplication for collapsed communities.
- Rendered JavaScript syntax is checked with Node.
- Port `8977` is restarted and health/page checks are run.
- Production port `8777` is not modified or restarted.

## Before and after

Before, competing listeners and mutable hit geometry caused missed or duplicate actions. After, one immutable-frame
dispatcher applies deterministic priority and visible-endpoint edge deduplication.

## Impact

Improves click reliability and removes duplicate lines without changing backend evidence or scores.

## Documentation updated

Updated relationship workspace behavior, test strategy and this change record.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back the release snapshot if input dispatch regresses.
