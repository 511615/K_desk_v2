---
change_id: 20260806-1130-acc-new-account-crm-route-display
features: ["ACC-SEARCH-001", "ACC-DETAIL-001"]
title: Preserve the CRM-confirmed server for new accounts with no orders
change_type: bug-fix
status: unreleased
compatibility: compatible
---

## Before and after

A login confirmed by its CRM server mapping but without a matching MT4/MT5 trading row was removed
from account lookup. The account detail page consequently had no source identity and displayed an
unidentified platform. Lookup and detail now preserve the confirmed platform, logical server and
account metadata while explicitly reporting that the new account has no trading orders.

## Impact

`exists` remains false and all order-derived values remain empty or zero. No financial calculation,
route fallback, local record or remote database state is changed. The read-only lookup response adds
no required fields and keeps the existing response shape.

## Documentation updated

- `docs/features/account/account-search.md`
- `docs/features/account/account-detail-legacy.md`
- `docs/DATA_AND_ROUTING.md`

## Deployment and rollback

Deploy by restarting only the account service on port 8777. Rollback restores the prior lookup
behavior; it does not require a data migration or affect the K-line service on port 8766.

## Verification

Focused regression tests cover the CRM-confirmed zero-order lookup and direct detail request. Live
read-only verification checks AC GB MT5 login 954059, which has no deals and must still identify
its server.
