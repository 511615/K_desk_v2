---
change_id: 20260826-0080-kln-all-product-financial-risk-pane
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Replace position count/lot telemetry with all-product account risk replay

## Before and after

The lower chart pane named `仓位` displayed all-product position count and total lots. Those values
did not satisfy the account-risk replay use case and could be confused with margin usage. The pane
is now `账户资金风险`: it plots replayed account Equity and used Margin in account currency across
the selected K-line time range.

## Impact

At every chart timestamp, the browser sweeps the compact all-product open-position replay, values
active executions from their supplied same-source M1 marks, and combines floating P/L with factual
Balance/Credit. The detailed snapshot remains the source for position rows, usage, margin level,
factual liquidation markers and the all-product equity-zero pressure boundary. Position count and
total lots remain available in that snapshot but are no longer risk-pane lines.

## Documentation updated

Updated `ACC-DETAIL-001` and `KLN-RENDER-001` with the currency-unified Equity/Margin pane,
crosshair-linked readout and snapshot semantics.

## Verification

Renderer regression asserts the `账户资金风险` pane, Equity/Margin series, visible in-pane readout
and crosshair-to-snapshot linkage. K-line/legacy tests, Python compilation and bundled Node
JavaScript syntax validation pass.

## Deployment and rollback

The change is renderer-only and uses the existing read-only compact replay payload. Reverting the
compatible renderer change restores the former count/lot chart lines; no data migration, account
operation or MT4/MT5 Manager action is involved.
