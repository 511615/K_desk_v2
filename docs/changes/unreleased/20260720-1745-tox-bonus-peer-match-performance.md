---
change_id: 20260720-1745-tox-bonus-peer-match-performance
features: ["TOX-BONUS-001", "TOX-BONUS-SCAN-001", "JOB-RECOVERY-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# Index bonus peer-order matching

## Before and after

Related-account coordination compared every subject trade with every peer trade. Account 3066283
and three routed same-user accounts produced about 179,000 MT5 deal rows, leaving a platform scan
at the second deep account while one CPU core remained saturated. Matching now buckets peer trades
by normalized symbol and opposite direction, then uses a sorted open-time index to inspect only the
documented five-second window.
The matcher also checks the durable cancellation signal during long CPU loops rather than only
between deep accounts.
Platform discovery additionally scans up to four independent physical sources and deep-checks up
to three accounts concurrently; daily shards for one source remain serial. Daily event rows now
merge before one 500-login-batch CRM routing pass per physical source. Candidate mappings flow into
deep analysis, while profiles and same-user families are prefetched into a task-local cache.

## Correctness

The detector still consumes subject and peer trades one-to-one, prefers the smallest open-time
delta, breaks equal-time candidates by lot similarity and requires at least 70 percent volume
similarity. Parsed open and close times are cached only inside copied analysis rows; result fields,
scores, evidence IDs and database queries are unchanged.

## Impact

Single-account and platform bonus analysis no longer perform quadratic peer matching. APIs, task
payloads, SQLite schema, remote read-only routes, score thresholds and other detection features are
unchanged. Cancellation during related-account matching now exits the current deep account.
The bounded concurrency changes elapsed time only and retains the complete candidate and result set.
Task caches retain at most 64 identical history windows, never widen the account's query boundary,
and are released when the scan finishes. A six-worker deep trial was discarded after it increased
the same live scan from 346.9 to 372.8 seconds through database contention.

## Documentation updated

Updated `TOX-BONUS-001`, `TOX-BONUS-SCAN-001`, `JOB-RECOVERY-001` and the test strategy with indexed
peer-match behavior, responsive cancellation and the large-history regression requirement.

## Verification

Unit coverage compares collision and tie-breaking behavior, runs a 10,000 subject by 10,000 peer
fixture under a bounded runtime and verifies source/deep concurrency, batched route validation,
candidate route reuse and prefetch behavior. Read-only acceptance reran the same four-environment,
30-day, 100-account scan: the first indexed version completed in 346.9 seconds, and the final batch
and cache version completed in 237.5 seconds with 100 analyzed accounts and zero failures. All 100
accounts were common between the comparison runs, no risk level changed and account 3066283 stayed
at 41.3 concern. Two active accounts moved only 0.1 and 0.2 score while live data advanced between
runs.

## Deployment and rollback

No migration or API deployment is required. Restart the discovery and interactive workers only
after active jobs are cancelled or completed. Rollback restores the previous matcher; stored job
rows and prior results remain readable.

The production discovery worker was restarted after the prior cancelled scan had reached its
terminal state; the web and interactive worker stayed online. A controlled four-environment,
30-day production scan with deep limit 1 completed in 56.4 seconds with zero failures. Rollback
requires only restarting the discovery worker on the prior code; no stored rows need conversion.
