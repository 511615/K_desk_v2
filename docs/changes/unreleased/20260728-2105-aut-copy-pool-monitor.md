---
change_id: 20260728-2105-aut-copy-pool-monitor
features: ["AUT-POOL-001", "ACC-DETAIL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add the dynamic copy-pool monitor

## Before and after

K_desk had no product entry for the running dynamic customer-pool Demo experiment. Operators had
to inspect separate snapshot files and could not compare base/effective weights, source exposure,
target position, execution events and risk gates in one place.

The account workbench now links to a dark, read-only `动态跟单` dashboard. It refreshes local
copier snapshots every second, presents explicit customer weight changes and reasons, and combines
pool, target, actual position, equity, point spread, latency, P/L, execution events and safety gates.
Anonymous customer IDs link to the existing account-detail page through a private server-side map.

## Impact

Three additive GET routes are introduced. The dashboard reads local files only and performs no
remote database or MT query. Public responses contain aliases but no customer Login. There are no
database migrations, new listening ports, writer processes, order controls or MT Manager actions.

## Documentation updated

Added `dynamic-copy-pool-monitor.md` and updated architecture, API, data-routing, operations and test
authorities. The feature registry and generated API/governance artifacts are regenerated from the
current code and feature metadata.

## Verification

Fast and Full verification passed with 300 Python/legacy tests, 20 frontend tests and the production
Vue build. `copy_trading_live_demo.py` also passed Python compilation. Isolated browser acceptance
at 1440x1000 and 390x844 confirmed live 22-account data, readable Chinese labels, explicit
base/current/down-percentage/reason weight comparison, no page-level horizontal overflow, the
intentionally scrollable narrow-screen pool table, working A-class/search filters and a successful
anonymous C001 redirect to the compatible account detail route. The browser console had no warning
or error entries.

## Deployment and rollback

The production account service on `127.0.0.1:8777` was restarted from PID 7704 to PID 18704 with
the verified workspace and explicit read-only copy-pool snapshot path. Readiness, production profile,
the new dashboard API, 22 anonymous pool rows, 22 detail mappings, fresh source state and absence of
public Login fields were checked after startup. The isolated PID 15156 preview on port 8891 was
stopped. Existing K-line PID 18844 on port 8766 and all workers were left untouched; no database
migration or MT operation was run.

Rollback restarts only the account service from the prior code revision. Removing the navigation,
page/API composition and optional environment variable is sufficient; copier snapshots, K-line,
workers and the existing account-detail route are unaffected.
