# Business rules

## Finance

- `closedNetProfit = grossClosedProfit + tradingFees + interest`.
- `comprehensiveProfit = closedNetProfit + holdingProfit + rebate + compensation + reward + negativeBalanceClear`.
- Net deposit is deposits minus withdrawals and excludes compensation, rewards and negative-balance clearing.
- MT5 `CRM-DP-` comments are deposits and `CRM-CW` comments are withdrawals.
- MT4 `CPS_` balance rows are compensation and `CCB-Reward` rows are negative-balance clearing.
- Rebate detail is hierarchical: aggregate at the requested grain before joining trades so trade
  counts are not multiplied. Display currency follows confirmed USD/USC conversion rules.

## Automation

- Copy origin detection uses explicit source identifiers in comments/magic fields and reports each
  source separately.
- Follower profit is shown per follower and source order; net profit includes gross profit,
  commission, swap and taxes in display currency.
- EA comment grouping retains the normalized exact EA name and excludes generic, signal-copy and
  origin-reference comments.

## Toxic and market-pushing

Detectors operate on the selected account source and order set. Market-pushing evidence may include
recurring peer accounts, open/close synchronization and tick evidence. Missing quote providers or
partial evidence must degrade explicitly; unavailable evidence must not be interpreted as a clean
result. Detection never changes an account or trade.

Feature documents contain the detailed current behavior and acceptance samples for each rule.
