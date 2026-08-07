---
change_id: 20260806-1145-acc-zero-order-wording
features: ["ACC-SEARCH-001", "ACC-DETAIL-001"]
title: Use account-first wording for zero-order accounts
change_type: ui
status: unreleased
compatibility: compatible
---

## Before and after

Search and detail user-facing zero-order messages now say `账户暂未做单` rather than describing
the underlying database state. A genuinely missing Login still displays `未找到该账号`.

## Impact

CRM-confirmed platform/server identity, `exists=false`, order counts and all route behavior remain
unchanged. This is a compatible presentation-only change with no local or remote data write.

## Documentation updated

- `docs/features/account/account-search.md`
- `docs/features/account/account-detail-legacy.md`

## Verification

Focused zero-order CRM-route regression tests and the production lookup/detail requests for account
954059 verify the new wording while retaining its `MT5 / AC GB MT5` identity.

## Deployment and rollback

Deploy by restarting only the account service on port 8777. Rollback restores the prior wording;
no database migration, task restart or K-line service restart is required.
