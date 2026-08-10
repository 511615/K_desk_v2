---
change_id: 20260810-1142-aut-pool-001-strategy-ledger-labels
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: clarify account facts and strategy ledger labels

## Before and after

The ownership-filtered ledger still used generic account/equity and order-section labels. The page
now explicitly distinguishes actual Demo account equity from this model's daily P/L, current
positions and Position history.

## Impact

Only visible labels change. Existing response fields, financial calculations, orders and account
state are unchanged.

## Documentation updated

Updated the AUT-POOL-001 current-state UI contract. No API, data-routing or OpenAPI shape changed.

## Verification

The mounted-page regression requires the account-fact disclaimer and model-only P/L label while the
mixed external-order fixture remains absent.

## Deployment and rollback

Deploy the versioned 8777 frontend from verified main. Rollback restores the previous labels without
changing Producer state or MT data.
