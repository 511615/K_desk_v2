---
change_id: 20260813-aut-ea-exact-comment-global-aggregation
features: ["AUT-EA-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# EA exact Comment global aggregation

## Before and after

Before, exact Comment membership was split by same-server ExpertID/MAGIC and by seed server.
After, the complete Comment is the single exact grouping key across all configured servers on the
selected platform; identifiers remain evidence fields.

## Problem

The EA query used a composite `(Comment, ExpertID/MAGIC)` identity on same-server rows and
retained the seed server in the merge key. One Comment such as `手动下单3` was therefore split into
multiple cards and accounts using the same Comment on other configured servers were omitted.

## Change

- Exact Comment identity is now `platform + complete Comment`; ExpertID/MAGIC remains row-level
  evidence and no longer gates membership.
- Exact Comment seeds are merged across all logical servers on the selected platform.
- Duplicate seed cards are collapsed before group construction, while each member retains its own
  database, server and observed ExpertID/MAGIC.
- Dynamic Comment templates and no-comment ExpertID sequence fallback keep their existing bounded
  safeguards and scoped matching rules.

## Impact

The API keeps the existing paths and additive fields. The visible result may contain more members
and fewer duplicate cards because accounts using the same Comment are now intentionally aggregated.

## Documentation updated

Updated `docs/features/automation/ea-comment-profit.md` and generated governance artifacts.

## Verification

- Added regression coverage for one Comment across different ExpertIDs and different servers.
- Existing EA, API, report and legacy compatibility tests remain required before deployment.
- Remote MySQL/MT sources remain read-only; no Manager or trading state is changed.

## Deployment and rollback

Revert this change record's paired code commit and restart only the 8777 account service; the prior
same-server identifier gate is restored without changing remote data.
