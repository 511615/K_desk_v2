---
change_id: 20260804-1310-acc-server-alias-routing
features: ["ACC-DETAIL-001", "ACC-SEARCH-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# ACC-DETAIL-001: Accept logical server aliases in account detail

## Before and after

Account links emitted by the copy-pool monitor used logical names such as `DBG CN MT4 Live1`,
while the account detail source registry used canonical names such as `DBG MT4 CN1`. The detail
API treated the query parameter as an exact source name, selected no trading source, and rendered
the misleading combination of `数据库暂无订单` and `币种未识别`.

The source registry now declares the logical names as compatibility aliases. Account detail,
finance, risk-panel and automation queries can select the same read-only source through either
name; response rows continue to expose the canonical source name.

## Impact

This is a backward-compatible routing fix. It changes no database schema, financial calculation,
remote data, MT4/MT5 state, ports or response field names. The affected account `7798014` now
resolves `DBG CN MT4 Live1` to `DBG MT4 CN1` and returns its 57 closed orders and USD metadata.

## Documentation updated

Updated `ACC-DETAIL-001`, `ACC-SEARCH-001` and `DATA_AND_ROUTING.md` with the compatibility alias
contract.

## Deployment and rollback

Restart the localhost account service on port `8777` to load the registry change. Rollback is the
previous legacy registry module revision; no data migration or local-data restore is needed.

## Verification

The routing regression covers all current logical MT4 aliases and AC MT5 Live3 casing. API
verification must compare the old `DBG CN MT4 Live1` URL with canonical `DBG MT4 CN1` and confirm
identical account/source/order metadata.
