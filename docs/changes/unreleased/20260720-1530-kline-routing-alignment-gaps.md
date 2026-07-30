---
change_id: 20260720-1530-kline-routing-alignment-gaps
features: ["KLN-DB-001", "JOB-RECOVERY-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Repair K-line quote routing and closed-market display

## Before and after

Generated charts used a separate light UI, one fixed Terminal and first-match symbols. Calibration
checked only open prices at GMT/GMT+3, accepted low-confidence mappings and could shift the entire
price series. One symbol exception aborted a multi-symbol job. Quote-index drawing silently snapped
missing times forward and collapsed weekends without marking them.

New charts preserve the established white chart workspace, use controlled read-only provider routes, score candidate symbols
and validate both trade endpoints under explicit thresholds. GMT expansion occurs only after the
existing modes fail. Automatic price shifting is removed. Successful symbols survive other symbol
failures and jobs persist structured details. Actual M1 gaps split aggregation; users can switch
between labelled compressed time and real elapsed-time blanks, while missing quotes use hollow
markers. Dotted broker suffixes such as `XAUUSD.G` and `XAUUSD.P` resolve into the base-symbol
candidate family before validation. Open markers use directional up/down arrows for buy/sell and
close markers remain squares; missing-quote endpoints use hollow versions of the same shapes.

## Impact

New chart output, K-line job result JSON, credential-free provider configuration, provider-qualified
caches, account/task-center status and native K-line domain/application rules. Historical HTML,
SQLite schema, URLs, ports, request parameters and output stems are unchanged.

## Documentation updated

K-line, job recovery and account-detail feature documents; architecture, API, routing, business-rule,
operations and test authorities; the legacy generator API/README and environment example.

## Verification

Focused tests cover routing, aliases, validation thresholds, partial results, gap segmentation and
directional trade markers. Fast and Full governance gates passed with 194 Python/legacy tests and
11 frontend tests. Desktop/mobile browser checks confirmed the white canvas, gap controls and
wrapped task-center filenames. A bounded read-only Terminal catalog check resolved `XAUUSD.G` to
`XAUUSD`; no account switch or Manager operation was performed.

## Deployment and rollback

Deploy code and optional local quote-source JSON together after development fixture acceptance.
Production deployment requires separate authorization. Roll back code and configuration only; do
not migrate SQLite or rebuild historical charts. No MT4/MT5 Manager mutation is permitted.
