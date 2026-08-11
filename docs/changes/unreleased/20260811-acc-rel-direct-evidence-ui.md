---
change_id: 20260811-acc-rel-direct-evidence-ui
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Show direct relationship evidence without IB peer leakage

## Before and after

Before, the relationship detail renderer expanded every evidence family through an intermediate
connector. For `ib_direct_account`, this could put another client of the same IB into the card
labelled `直属上级 IB 本人交易账户`. The selected-account path could likewise show a longer score-ledger
route even when a direct evidence edge to the seed account existed.

After, the renderer keeps `ib_direct_account` peers to the immediate account-to-account evidence
edge. It does not traverse an IB-owned account to collect other clients of that IB. For path and
overview classification, a direct selected-account-to-seed edge takes precedence over an indirect
ledger route. For account 531424, an account such as 530969 that shares the current LastIP is shown
through the login-IP relationship and its direct path, not as the direct superior IB's own trading
account.

## Impact

This is a presentation-only correction. It does not change source routing, Kuzu projection,
relationship scoring, expansion thresholds, or any API response shape. The direct-IB card continues
to show only the IB user's verified own trading accounts.

## Documentation updated

`ACC-REL-001` and `ACC-REL-003` now define the direct-only IB peer rule and direct-evidence path
precedence.

## Verification

`tests/test_api.py` verifies that the Kuzu page contains the direct-evidence path rule and the
direct-only IB peer rule. Fast and Full governed verification are required before deployment.

## Deployment and rollback

Deploy only the verified 8777 account service from `main`. Roll back by restarting the previously
verified account-service commit; no data or database migration is involved.
