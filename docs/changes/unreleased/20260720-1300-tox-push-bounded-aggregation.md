---
change_id: 20260720-1300-tox-push-bounded-aggregation
features: ["TOX-PUSH-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Bound platform push candidate aggregation

## Before and after

Large MT5 candidate queries could wait 90 seconds, retry the entire source for up to 240 seconds,
and repeatedly scan the unindexed daily view for every 200 candidate accounts. Jobs appeared frozen
at 17 percent and could run longer than the worker lifecycle. Candidate windows now use bounded
MT5/MT4 time shards with adaptive split retry, live shard/profile progress, group-based currency
resolution and no daily-view query. Lifetime profile batches now use one query slot per physical
database, and the expensive active-day distinct count runs only when its filter is enabled. Profile
queries use 10-account indexed batches under a 45-second budget and reconnect with 5-account batches
after a transient timeout instead of failing the complete source.
Lifetime trading net is calculated by the equivalent platform identity `Balance - ledger net`
(`Action>=2` for MT5 and `CMD=6` for MT4), so the profile phase no longer scans every historical
trading row.
Optional lifetime filters are deferred until after structure scoring and applied to every structural
candidate considered for deep rank truncation. Ranked profiling stops after enough qualified
candidates fill the requested Top-N, preserving final queue ordering while avoiding lifetime queries
for ordinary and lower-ranked accounts that cannot enter this run's deep analysis.
Structure-screen order loading also uses bounded 50-account batches and reconnecting split retries
down to 5 accounts, preventing one transient batch timeout from dropping the complete server.

## Correctness

Profit and maximum lot merge exactly across shards. MT4 trade counts are additive. MT5 positions
can close across shard boundaries, so an account whose summed shard counts cross the configured
limit is re-counted by distinct position over the complete window before it can be excluded.
Read-only AC CN samples confirmed `Balance = trade net + ledger net` to floating-point tolerance.

## Impact

Push-discovery candidate SQL, transient-timeout behavior, per-database profile concurrency,
progress events and focused regression tests. Toxic scoring, deep-check inputs, API fields and
persisted job storage are unchanged.

## Documentation updated

Market-pushing current state, data/routing authority and test strategy.

## Verification

Focused tests cover shard sizes, merged values, exact MT5 boundary reconciliation and absence of
daily-view access. Read-only live checks on busy 12-hour windows completed in about 0.97 seconds for
AC CN MT5 and 1.98 seconds for DBG MT5 under a 45-second hard query budget.
A final production-path one-day scan screened all 3,966 window candidates, found 658 structural
candidates, profiled only the top 25 to fill a one-account deep limit, completed in 149.6 seconds and
returned zero partial failures. A three-day scan also crossed aggregation in about 10 seconds,
screened all 4,137 candidates and returned zero partial failures. The pre-fix comparison took 211.7
seconds while losing five aggregate sources before screening.

## Deployment and rollback

No API, storage migration, scoring or filter-default change. Rollback restores the previous
single-query aggregation; active durable jobs must be allowed to finish or fail before worker restart.
