---
change_id: 20260805-1100-acc-crm-lag-route-fallback
features: ["ACC-SEARCH-001", "ACC-DETAIL-001", "FIN-COMP-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Account route fallback for delayed CRM mapping

## Before and after

Account `309361` existed in the DBG MT5 export and had 47,242 deals, but did not yet have a CRM
`mt_users_account` mapping. The route guard treated that missing mapping as a missing account, so
search, detail, order, finance and dependent account analysis returned an empty database and no
currency metadata.

The shared route guard now accepts a transaction source only after CRM confirmation, or after a
strict fallback proves an indexed trade-user match is unique among independent same-host,
same-platform physical sources. Shared-schema secondary logical routes and duplicate matches remain
blocked. Lookup exposes `routeValidation=unique_trade_user_fallback` for the exceptional case.

## Impact

No endpoint, port, financial formula, local data or remote state changes. Existing CRM-confirmed
routes are unchanged. `DBG CN MT4 Live2` remains bound only to `crm_cn` code `3` and
`crm_cn_mt4_live2`; DBG MT5 Live2 remains bound only to `crm_vn` code `5` and
`crm_vn_mt5_live2`.

## Documentation updated

Updated account search, legacy detail, comprehensive finance, data routing and test strategy.

## Deployment and rollback

Restart only the localhost account service on `8777`. Roll back by restoring the previous account
registry module revision and restarting that service; no migration or local-data restore is needed.

## Verification

Regression tests cover CRM confirmation, unique trade-user fallback, duplicate-source rejection,
USC metadata, the `DBG CN MT4 Live2` alias/code/schema route and the independent DBG MT5 Live2
code-5 route. Live checks verify account `309361`, MT4 CN2 sample `8325931`, and MT5 Live2 sample
`5200101` through read-only APIs.
