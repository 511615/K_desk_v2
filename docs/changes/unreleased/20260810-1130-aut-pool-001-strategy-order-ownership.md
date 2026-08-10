---
change_id: 20260810-1130-aut-pool-001-strategy-order-ownership
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: exclude non-model Demo orders

## Before and after

The pinned Demo ledger previously published and displayed every account Position and recent trading
Deal, using `strategy_owned` only as a label. Manual trades and other EAs could therefore appear in
the model's position count, floating P/L and Position-level history.

The Producer now emits only rows owned by Magic `26072801` and the approved fixed/independent Comment
namespace. The 8777 filesystem adapter and Vue page repeat the explicit ownership filter so legacy
snapshots cannot reintroduce other account activity. Account balance, equity and margin remain actual
account facts and are not presented as strategy-only equity.

## Impact

The current-position table, its floating-P/L total, closed-Position history and history row count now
contain only this copy model's orders. No MT order or account state is changed, and existing API field
names remain compatible.

## Documentation updated

Updated AUT-POOL-001 current behavior, data ownership/routing and test strategy. No API or OpenAPI
shape changed.

## Verification

Mixed fixtures cover owned and unowned open positions, opening/closing Deals and a deliberately large
external profit. Tests require the external rows and their P/L to be absent at Producer, API and UI
boundaries while the owned lifecycle remains unchanged.

## Deployment and rollback

Deploy the verified main revision to the single Producer and account-web service. No database, MT
account, order or Manager state is modified. Rollback restores the previous projection only; local
MT history remains unchanged.
