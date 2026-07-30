---
change_id: 20260722-2000-tox-bonus-margin-ranking
features: ["TOX-BONUS-SCAN-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Rank bonus candidates by margin over deposit

## Before and after

The platform scan truncated its deep queue by explicit bonus evidence, grant amount, count and
recency. A large old grant could consume a slot ahead of an account currently using a large share of
its deposited cash as margin. After the existing handled-account and minimum-grant filters, the scan
now ranks candidates by current occupied margin divided by cumulative qualifying deposits. The
deep-account limit and handled-account exclusion remain directly editable in the workbench.

## Correctness

Both current Margin and cumulative deposits use the account's confirmed USD/USC money scale.
Deposits follow the detector's positive `DEP-`/`CRM-DP-` definition from registration or at most 400
days; `DEP-RS` reversals are excluded. Candidates with a recognized positive deposit rank ahead of
unknown-denominator accounts. Explicit bonus evidence, grant amount, count and recency remain
tie-breakers and the failure fallback. The ratio controls queue priority only and adds no risk score.

## Impact

No request field or database schema changes. Completed scan rows add `currentMargin`, `depositTotal`
and nullable `marginToDeposit`. Candidate profile and deposit reads are batched by indexed login and
bounded time. A ranking read failure is additive partial-failure evidence and does not drop the
candidate or fail successful sources.

## Documentation updated

Updated `TOX-BONUS-SCAN-001`, API, business-rule, data-routing and test-strategy authorities.

## Verification

Tests cover ratio-first deep selection, exact projected fields, fallback to the prior grant order,
MT5 fee-aware deposit amounts and reversal/non-deposit exclusion. Full verification and production
acceptance are recorded at handoff.

## Deployment and rollback

No migration is required. Restart the discovery worker and account service after the production
frontend build. Rollback restores grant-evidence ordering; existing completed job snapshots remain
readable because the response fields are additive.
