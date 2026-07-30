---
change_id: 20260721-1140-tox-bonus-ratio-hard-gate
features: ["TOX-BONUS-001", "TOX-BONUS-SCAN-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Require a material bonus-to-cash ratio

## Before and after

The cycle detector displayed `赠金 / 入金` but did not require it for completed extraction or
coordinated-sacrifice paths. A 10% promotion could therefore inherit 75/90-point extraction floors
and repeated cycles could raise it to 85/92. Every positive path now requires a cycle ratio of at
least 20%. Below-threshold cycles remain visible but are evidence-only and capped at 39.

## Correctness

The threshold is calibrated against the `赠金套利` worksheet: among 28 labeled accounts with a
reconstructable strongest cycle, the effective lower boundary is 20%, the median is 100% and 20
accounts are at least 50%. The latest 42 flagged discovery results contained four accounts below
20%, including 10% and 18.18% cycles. Numeric tolerance keeps the exact 20% labeled boundary
eligible while rejecting those lower ratios. The gate is applied before extractor, locked-profit,
sacrifice and repeated-extractor decisions so no alternate branch can bypass it.

## Impact

No endpoint, request, route, database or MT state changes. Existing response fields remain and each
evidence cycle adds `bonusRatioEligible` and `requiredBonusToCash`. Single-account Toxic checks and
platform discovery share the same rule; previously stored job results remain historical snapshots.

## Documentation updated

Updated `TOX-BONUS-001`, `TOX-BONUS-SCAN-001`, business rules and test strategy.

## Verification

Focused tests cover 10%, 18.18%, exact 20% and a low-ratio coordinated-sacrifice bypass attempt.
Read-only replay retained all eight labeled exact-20% boundary samples. Of the latest scan's 42
previous high/severe results, 38 retained a risk level and four fell below warning. Production API
recheck of account 7793009 changed 92/severe to 39/no-obvious-risk and marked all five 10% cycles
ineligible without adding query work.

## Deployment and rollback

No migration or frontend build is required. Restart the interactive and discovery workers to load
the rule. Rollback restores the previous detector code; historical SQLite job rows remain valid.
