---
change_id: 20260723-1000-data-dbg-mt5-live2-routing
features: ["ACC-SEARCH-001", "ACC-DETAIL-001", "FIN-COMP-001", "FIN-REBATE-001", "AUT-COPY-001", "AUT-FOLLOWER-001", "AUT-EA-001", "FIN-REBATE-AUDIT-001", "FIN-REBATE-SCAN-001", "KLN-DB-001", "TOX-PUSH-001", "TOX-BONUS-001", "TOX-BONUS-SCAN-001", "TOX-POSITION-001", "TOX-POSITION-SCAN-001", "TOX-HEDGE-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Add DBG MT5 Live2 routing

## Before and after

K_desk previously exposed ten logical trading routes. DBG Vietnam CRM server code 5 now resolves to
the independent `crm_vn_mt5_live2` MT5 schema as logical server `DBG MT5 Live2`. Existing
`crm_vn` server code 2 continues to resolve to `mt5_export_new`; the new source does not replace or
merge that route. Compatibility aliases `DBG MT5` and `DBG GB MT5 Live2` remain account-route
validated before any trading query.

The central source registry automatically extends account search/detail, finance, rebate, same-name,
Copy, EA, K-line order lookup, hierarchy, bonus, position-risk and hedge queries. Market-pushing adds
the new schema's verified `INDEX_TIME` and `INDEX_POSITIONID` names. Dynamic EA discovery includes
the new schema's verified Comment index path.

## Impact

The logical route count changes from ten to eleven and cross-platform peer discovery covers nine
deduplicated physical trade sources. API paths, JSON fields, ports, SQLite schema, financial formulas
and cashflow classification are unchanged. Remote CRM and trading access remains SELECT-only.

## Documentation updated

Updated the data-routing and test authorities, every affected current-state feature document, the
read-only release matrix, and the `query-ac-dbg-database` routing/schema/query references.

## Verification

Unit tests pin `crm_vn` code 5 to `crm_vn_mt5_live2`, retain code 2 on `mt5_export_new`, include
Live2 in dynamic EA targets and require the verified push-discovery indexes. Read-only live acceptance
uses account 5200101 for lookup, finance and order routing.

## Deployment and rollback

Restart the account service and interactive/discovery workers so they load the extended registry.
Rollback removes the Live2 source plus its index/EA entries and restarts those processes. No local or
remote data rollback is required.
