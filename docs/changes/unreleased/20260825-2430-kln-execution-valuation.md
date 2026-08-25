---
change_id: 20260825-2430-kln-execution-valuation
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Value all-product MT5 positions from exported execution inputs

## Before and after

The inline account position panel could replay all products, Balance and Credit, but displayed
floating P/L, margin and risk ratios as unavailable. It now carries read-only MT5 execution contract
and conversion inputs plus product calculation metadata into the compact replay and computes them
at the selected M1 timestamp.

The implementation also corrects current-position `VolumeExt` conversion to MT5's 1/100,000,000-lot
unit. The previous 1/10,000 conversion would inflate a current position by 10,000 and could not be
used for a defensible account-wide risk calculation.

## Impact

The inline `仓位` cards and table now show all-product per-execution marks, floating P/L and
estimated margin where the required inputs are complete. Candles, order markers, realised Profit
bars, manual K-line generation and public API paths remain unchanged.

## Accuracy and limitations

Floating P/L is calculated per execution from its own product's accepted M1 close mark, direction,
recorded contract size and recorded profit conversion rate. Margin uses the account's exported
leverage and the source product's supported calculation mode and directional margin rule. The UI
shows a total only if every active row is fully sourced; otherwise it identifies the missing row
without substituting a default. Balance/Credit and liquidation events retain their existing factual
ledger semantics. Group stop-out thresholds are not exported by the available source, so no guessed
liquidation price is presented as a fact.

## Performance and safety

The server returns compact close-only quote arrays and product metadata once. The browser binary
searches an individual product's M1 marks and evaluates only the open rows at a clicked minute;
pan/zoom does not scan the whole account history or call a terminal. All database and terminal reads
remain read-only.

## Verification

Regression tests cover preserving execution valuation fields and embedding/using the valuation
payload. The generated renderer JavaScript is parsed by Node before promotion.

## Documentation updated

Updated the account-detail and Lightweight renderer feature specifications with the valuation data
contract, supported calculation modes, missing-input behavior and no-default policy.

## Deployment and rollback

This is read-only account, quote and database access only; it changes no MT4/MT5 Manager or server
state. Reverting this change restores the prior explicit unavailable valuation cards.
