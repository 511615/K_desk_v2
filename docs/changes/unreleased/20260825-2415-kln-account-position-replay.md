---
change_id: 20260825-2415-kln-account-position-replay
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add an all-product account position replay to the direct K-line panel

## Before and after

The direct K-line's `仓位` panel calculated only the current chart symbol from the recent display
rows and a fallback balance. It now receives a compact all-product event replay for the chart time
window, with pre-swept count and lot totals, plus the existing factual Balance/Credit and liquidation
timeline.

## Impact

Candlesticks, markers and Profit bars remain selected-symbol evidence. The lower position panel now
shows all overlapping product positions at a clicked time, factual Balance/Credit, and only actual
platform Stop Out or negative-balance-clear records. The initial server calculation is bounded to
the already-read account history; panning and zooming use supplied series and the browser keeps a
bounded minute snapshot cache.

## Accuracy and limitations

The replay does not manufacture intraday total floating P/L, margin, margin level or a liquidation
price when a product lacks a same-source M1 mark or historical contract specification. Those fields
remain explicitly unavailable until their factual inputs are available. This is intentional: a
default leverage or symbol multiplier would be misleading risk evidence.

## Documentation updated

Updated the account-detail and Lightweight renderer current-state documents.

## Verification

The domain regression proves all overlapping products are retained and all chart-time count/lot
points are created by one sweep. Renderer tests prove the compact replay is embedded and consumed
by the all-product position panel, and generated JavaScript is parsed with Node.

## Deployment and rollback

No account, trade, quote, balance or server-side state is changed. Reverting restores the former
single-symbol position approximation.
