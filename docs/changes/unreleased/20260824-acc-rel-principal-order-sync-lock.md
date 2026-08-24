---
change_id: 20260824-acc-rel-principal-order-sync-lock
features: ["ACC-REL-001", "ACC-REL-003", "TOX-PUSH-001", "TOX-HEDGE-001"]
change_type: change
status: unreleased
compatibility: compatible
---

# Principal-order open/close synchronization and opposite-lock relationships

## Why

The relationship graph needs auditable full-platform trade-behaviour clues without copying every
historical order into the graph or drawing one parallel edge for every matching order pair.

## Change

- Reuse the governed push-analysis principal-order rule per symbol: retain all when fewer than five
  closed entry orders exist; otherwise retain the largest orders covering at least 95% of volume with
  a five-order floor.
- Detect same-symbol, same-direction peers whose opening and final closing differ by at most two
  seconds and recur on at least `max(2, ceil(5% of principal orders))` principal orders.
- Detect suspected opposite locks on the same symbol when direction is opposite, opening and final
  closing differ by at most five seconds and lot similarity is at least 80%.
- Aggregate all matched order pairs for one peer and detection type into one relationship edge. Keep
  at most 20 order-pair examples as click-through evidence.
- Preserve AC/DBG MT4+MT5 physical-source coverage and report partial scans instead of treating them
  as complete no-match results.

## Compatibility and safety

The existing `include_toxic` request flag and `toxic_sync_same` / `toxic_sync_opposite` relation IDs
remain compatible. Labels and evidence become more explicit. All remote data access remains bounded
and read-only; no MT4/MT5 Manager or source-database state is changed.

## Verification

- `tests/test_trade_relationship_detection.py`
- `tests/test_relationship_risk.py`
- API and relationship regression suite

## Before and after

Before, trade-behavior relationships lacked one bounded principal-order contract. After, synchronized and opposite-lock
evidence is aggregated per peer with explicit coverage and auditable examples.

## Impact

Adds optional read-only trade evidence when requested; default relationship requests and existing relation IDs remain compatible.

## Documentation updated

Updated relationship, market-pushing, cross-account-hedge, routing and test-strategy current-state documentation.

## Deployment and rollback

Promote through dev to main and restart the account service. Disable the optional Toxic flag or roll back the release
snapshot if trade-evidence discovery regresses.
