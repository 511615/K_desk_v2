---
feature_id: TOX-HEDGE-001
title: Cross-account synchronized hedge query
module: toxic
status: active
apis: ["GET /api/toxic/check-types", "POST /api/accounts/by-login/{login}/toxic-checks", "GET /api/toxic/jobs/{job_id}"]
code: ["src/kdesk/application/hedge_detection.py", "src/kdesk/domain/position_risk.py", "src/kdesk/infrastructure/position_risk.py", "src/kdesk/worker/runner.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["tests/test_hedge_detection.py", "tests/test_position_risk.py", "tests/test_position_risk_infrastructure.py", "tests/test_worker.py"]
depends_on: ["TOX-POSITION-001", "JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Cross-account synchronized hedge query

## Purpose and user entry

The `平台内多账户对锁` item in the legacy account-detail Toxic dialog is a dedicated cross-account
query. It finds visible opposite orders for the selected account and does not run heavy-position,
penetration, same-direction coordination or any other Toxic rule as part of this result.

## UI and behavior

The result is presented as a query rather than a model score. Its leading number is the unique
suspected-account count. It shows the number of checked target orders, synchronized opposite order
pairs, completed physical sources and unclosed target positions excluded from verification. A first
table lists each suspected account with platform, logical server, database, pair count and subject/peer
lots. A second table lists exact subject and peer order/position/deal identifiers, symbol, directions,
lots, timestamps and opening/closing deltas. Account rows link to the correctly routed detail page.

## API contract

The existing type ID and Toxic endpoints remain unchanged. The replaced result row additively exposes
`evidence.hedgeQuery`; the completed job also exposes the same projection as `result.internalLock`.
Legacy fields and unrelated Toxic rows remain compatible.

## Data, routing and read-only constraints

The target account is resolved through the selected platform/server route. Its complete bounded
account-analysis history supplies target entries; open positions cannot prove synchronized closing and
are counted but excluded. The peer lookup deduplicates the configured logical routes to all nine
physical AC/DBG MT4 and MT5 trade sources. Shared physical rows are mapped back to their CRM-specific
logical server. Equivalent MT5 opening windows and MT4 opening/closing window pairs are queried once.
When a multi-target opening-window query reaches its row ceiling, the adapter
recursively splits the target batch and retains the union. It reports the source as incomplete only if
one target's own five-second window still reaches the ceiling. All remote access is indexed, bounded
and SELECT-only. MT5 opening SQL keeps its indexed five-second predicate and additively restricts each
target clause by canonical symbol prefix, opposite direction and the equivalent 80%-125% peer-lot
range. The same rules are rechecked before complete Position deals are loaded and again by the final
pure matcher.

## Business rules and units

A displayed pair requires the same canonical symbol, opposite direction, a fully closed target and peer
position, a lot similarity of `min(subject lots, peer lots) / max(subject lots, peer lots) >= 80%`,
an opening-time delta no greater than five seconds and a final-closing-time delta no greater
than five seconds. A match is named
`疑似对锁`; synchronization alone does not prove an arbitrage relationship. Same-direction matches are
discarded from this feature and cannot affect its result.

## Loading, empty and failure behavior

A full nine-source query with no match reports `未发现`. One or more source failures report partial
coverage and must not be phrased as a clean all-platform result. No closed target order reports
`数据不足`. Complete account/pair totals are retained; detail is capped at 500 pairs and the account
page displays at most 100 pair rows.

## Code and dependencies

Application code projects closed target entry orders and returns only opposite evidence that passes the
80% lot-similarity gate. It reuses the
pure synchronized-order matcher and read-only cross-platform peer adapter owned by position risk. The
Worker replaces the copied legacy account-internal lock row after the legacy task finishes.

## Tests and acceptance

Tests require opposite-only projection, exact target and peer provenance, open-position exclusion,
partial-failure language, nine-physical-source deduplication, Worker replacement and the dedicated
account-page result tables. A saturated multi-target fixture must split without losing rows.
Same-direction evidence must never appear in `hedgeQuery`.
Live acceptance on AC GB MT5 account 639631 must complete all nine physical sources and retain the
same 13 opposite synchronized pairs after SQL candidate pruning; the dense query should finish within
30 seconds on the production host.

## Compatibility and deprecation

`internal_lock_arbitrage`, `/account/{login}` and all existing Toxic job endpoints remain stable. The
copied account-internal reverse-leg heuristic remains only as rollback behavior and is no longer
authoritative after the Worker completes.
## Relationship-investigation reuse

`ACC-REL-003` can request optional opposite-direction principal-order timing evidence using this
feature's hedge semantics. Matches are bounded, aggregated per peer and reported with coverage;
the relationship view does not change hedge verdicts or any remote source state.
