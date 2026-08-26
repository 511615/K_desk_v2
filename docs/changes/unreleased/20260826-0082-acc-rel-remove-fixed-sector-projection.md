---
change_id: 20260826-0082-acc-rel-remove-fixed-sector-projection
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Decommission the obsolete fixed-sector Galaxy renderer

## Before and after

An experimental fixed-sector renderer remained in the repository after Galaxy returned to the
star-track presentation. Its runtime entry could be reconnected accidentally, producing large
cross-canvas arcs that do not match the accepted relationship semantics.

## Change

- Remove the fixed-sector runtime import, event dispatch and asset append from Galaxy. The retired
  module remains mapped as history but is not loaded or reachable by the page.
- Keep only same-CRM account components as collapsible star-track communities.
- Keep LastIP, CID, EA, copy, rebate, IB and trade facts as direct, clickable relation lines.
- Keep ordinary relation geometry direct; only expanded same-CRM member evidence can use a small
  bounded local lane for parallel line readability.

## Impact

Presentation-only. This does not change account discovery, relationship evidence, scores, expansion
rules, data access, or any remote state.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`
- `docs/feature-registry.json`

The feature mappings retain the retired path as immutable change history. It is not loaded or
reachable at runtime.

## Verification

- `tests/test_api.py` rejects any fixed-sector dispatch from Galaxy and checks the direct-route rule.
- The 216056 browser regression expands a same-CRM track, clicks a real member line, and requires a
  populated relation display table.

## Deployment and rollback

Standard promotion/release. Rollback restores the previous application version; no data repair is
needed.
