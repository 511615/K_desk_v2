---
change_id: 20260825-2510-kln-portfolio-risk-boundary
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Calculate the replayed all-product risk boundary

## Before and after

Before this change, the account-wide position replay showed factual liquidation
markers but could not show a computed price risk boundary.  The inline K-line
`仓位` snapshot now calculates a per-product portfolio stress boundary from
reconstructed historical funds, every open product position, each execution's
contract/conversion inputs and same-source M1 marks.  It shows the closest
adverse price and percentage move in a dedicated risk card.

## Impact

The change is additive to the direct inline K-line position snapshot. Candles,
closed-order Profit bars, factual liquidation markers and existing APIs retain
their prior semantics.

## Semantics and accuracy

For one product at a time, the calculation holds other products at their
clicked-timestamp M1 marks, sums the product's signed account-currency P/L
slope, and solves the exact price where current replayed equity becomes zero.
This is a deterministic historical replay scenario, not a prediction.

The available read-only MT5 account and product exports do not provide the
account group's configured Stop Out percentage.  Therefore the card explicitly
uses and labels an `权益归零压力价`; it does not claim that price is an actual
broker liquidation level.  Existing sourced Stop Out / negative-balance-clear
markers remain factual evidence and stay separately counted.

## Performance and safety

The browser evaluates only the currently open compact replay rows after a chart
click.  It reuses already-delivered M1 marks and makes no database, terminal or
Manager request.  No trading, account or server state is changed.

## Documentation updated

Updated `ACC-DETAIL-001` and `KLN-RENDER-001` with the stress scenario,
all-product calculation scope and explicit distinction from a broker Stop Out.

## Verification

Renderer tests assert the dedicated card, explicit no-guessed-stop-out wording,
and the price-boundary solver. The rendered JavaScript is syntax-checked with
the bundled Node runtime and evaluated against a deterministic numerical case.

## Deployment and rollback

Removing this compatible client-side card and the two valuation metadata fields
restores the previous position snapshot.
