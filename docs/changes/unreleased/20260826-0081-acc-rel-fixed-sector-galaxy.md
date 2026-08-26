---
change_id: 20260826-0081-acc-rel-fixed-sector-galaxy
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Fixed-area Galaxy relationship projection

## Before and after

Galaxy mixed star-track communities and long cross-community evidence lines. It now projects the
unchanged investigation graph into a same-CRM centre plus eight permanent business sectors.

## Change

- Same-CRM accounts appear only in the centre; their outer evidence begins at a centre entry.
- IP, CID, EA, Copy, rebate, IB/CRM, sync and hedge evidence use independent fixed sectors.
- Repeated outer account instances retain one real account ID; edges retain raw relation IDs.
- Locator points are deduplicated real trading accounts; node and edge clicks retain profile and
  relation-display behavior respectively.

## Impact

Presentation-only; propagation, scoring, queries, routes and evidence APIs are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`
- `docs/TEST_STRATEGY.md`

## Verification

- Renderer/unit contract checks, governance Fast/Full checks and the 216056 candidate browser test.

## Deployment and rollback

Standard promotion/release only. Rollback restores the prior client renderer and needs no data repair.
