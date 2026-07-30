---
change_id: 20260727-1000-fin-hierarchy-live2-routing-correction
features: ["FIN-HIERARCHY-001", "ACC-SEARCH-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Correct hierarchy routing for DBG MT5 Live2

## Before and after

The July 23 Live2 registry change correctly connected the general account, finance, automation,
Toxic, scan and K-line paths, but the hierarchy net-deposit module still maintained an independent
AC-only source list and fixed server-code predicate. It therefore omitted DBG MT5 Live2 and could
misroute a non-AC code 2 hierarchy account to the shared AC MT4 source.

Hierarchy subject lookup, descendant account loading, per-account metrics and product discovery now
derive their route set from the central source registry. Accounts use exact `(CRM schema,
mt_server_code)` matching, including `crm_vn` code 5 to `crm_vn_mt5_live2`; code 2 remains on
`mt5_export_new`. DBG CRM ambiguity choices now expose `dbg-cn:` and `dbg-vn:` targets.

## Impact

`GET /api/hierarchy-products` and `GET /api/hierarchy-net-deposit` gain correct DBG and Live2
coverage. Paths, parameters, response fields, ports, aggregation formulas and AC behavior are
unchanged. Remote access remains read-only.

## Documentation updated

Added the missing `FIN-HIERARCHY-001` current-state feature and corrected the routing, API and test
authorities. The earlier immutable Live2 record remains unchanged so the correction is auditable.

## Verification

Focused tests cover exact code 2/code 5 routing, unsupported-code rejection, dynamic CRM code SQL,
DBG-qualified targets and physical-source product de-duplication. Full verification and read-only
Live2 API acceptance are required before deployment.

## Deployment and rollback

Restart the account service so the governed legacy module reloads. Rollback restores the previous
hierarchy module and restarts only the account service; no SQLite or remote database rollback is
required because this feature performs reads only.
