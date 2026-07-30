---
change_id: 20260728-2130-aut-copy-pool-account-identity
features: ["AUT-POOL-001", "ACC-DETAIL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Show detailed accounts in the copy pool

## Before and after

The current-pool table showed only aliases such as `C001`. Operators could open the account detail
page but could not identify the trading Login or server while scanning the pool.

The table now shows the real trading Login as the primary clickable value, with alias and server on
a secondary line. Account search accepts either Login, alias or server. Compact contribution,
weight and event charts retain aliases to avoid widening dense monitoring rows.

## Impact

`GET /api/copy-pool/dashboard` additively exposes `accountLogin`, `accountPlatform` and
`accountServer` on each pool row. The service remains localhost-only and read-only. No private route
object, runtime-state Login map, password, credential, contact field, database write or MT operation
is exposed or performed.

## Documentation updated

Updated `dynamic-copy-pool-monitor.md`, `ARCHITECTURE.md`, `PORTS_AND_APIS.md`,
`DATA_AND_ROUTING.md` and `TEST_STRATEGY.md`. Generated registry and OpenAPI artifacts are refreshed.

## Verification

Fast and Full verification passed with 300 Python/legacy tests, 20 frontend tests and the production
Vue build. Browser acceptance on the production service confirmed 22 real Login labels, 22
alias/server context lines, no account-cell or page-level overflow, real Login search, alias search,
the existing detail redirect and an intentionally scrollable 319/1120-pixel table at 390x844. The
browser console had no warning or error entries.

## Deployment and rollback

Production account service `127.0.0.1:8777` was restarted from PID 18704 to PID 10960 after Full
verification. Readiness, production profile, fresh dashboard state and complete 22/22 detailed rows
were checked after startup. Port 8891 remained closed; K-line PID 18844, workers, databases and MT
services were untouched. Rollback removes the three additive identity fields and restores the
alias-only table cell without changing copier snapshots or account-detail routing.
