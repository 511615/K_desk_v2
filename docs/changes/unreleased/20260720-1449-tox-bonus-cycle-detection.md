---
change_id: 20260720-1449-tox-bonus-cycle-detection
features: ["TOX-BONUS-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Detect historical bonus-arbitrage funding cycles

## Before and after

The existing Toxic bonus check used only current Credit, current margin pressure and trade bursts.
It therefore missed accounts after withdrawal and Credit removal and could not distinguish an
ordinary promotion user from a completed profit-extraction loop. The new governed detector
reconstructs historical cash, credit, trade, extraction and related-account cycles.

## Correctness

Credit lifetime is dynamic rather than a fixed four-hour or 21-day bucket. Withdrawal reversals are
retained as attempted extraction, while actual cash and internal-transfer net flows are reconciled
without double counting a transfer that later returns. Completed extraction, locked profit and
sacrifice-account paths have separate score gates. An unpaired sacrifice account is capped below
warning, and locked profit without extraction is capped at warning.

## Impact

Only the existing `bonus_arbitrage` Toxic result changes. APIs, request fields, other Toxic types,
push discovery, rebate discovery, SQLite storage and MT/CRM state are unchanged.

## Documentation updated

New `TOX-BONUS-001` current-state document plus business-rule, data-routing and test authorities.

## Verification

The labeled workbook cohort contains 39 unique accounts across AC GB MT4/MT5 and AC CN MT5.
Read-only development validation reconstructed exact sample chains including account 621928:
500 cash, 500 Credit, 625.53 trading profit, 1,125.53 transfer and full Credit removal. A separate
30-account same-month promotional-credit cohort is used to pressure-test false positives; a grant
alone remains below warning, while previously unlabeled accounts with near-exact extraction loops
remain candidates rather than being forced negative.

## Deployment and rollback

No migration or service endpoint change. A worker restart loads the new domain/application adapter;
rollback removes the worker replacement and restores the old current-Credit placeholder result.
