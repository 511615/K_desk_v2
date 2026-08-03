---
change_id: 20260803-1730-aut-copy-pool-equity-baseline-correction
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Correct copy-pool equity baselines and hard-gate reasons

## Before and after

The factor build previously subtracted the first observed funding movement from the same equity
row. Pre-funding zero rows and first-funded rows could therefore become adjusted equity at or below
zero and were published as `negative_equity`, even when the platform equity was never negative.
Daily drawdown also required a point before the first partial trading day inside the 60-day window,
although the repository had no exact pre-window anchor.

The first positive funded observation now establishes capital without subtracting its own funding.
Earlier zero-equity rows are excluded from the adjusted path. Raw platform equity below zero remains
`negative_equity`, but only authoritative platform daily/current evidence may publish that code;
an incomplete reconstructed snapshot path cannot. Later adjusted capital exhaustion remains a hard rejection under
`cashflow_adjusted_capital_exhaustion`. MT4 and MT5 history reads add the nearest daily anchor before
the bounded range through progressively expanding indexed Login/time windows. Daily coverage ignores
only the partial cutoff day, accepts an exact rollover anchor and uses a new account's first funded
observation as its first-day baseline.

## Impact

This changes daily factor-build classification and drawdown evidence only. It does not weaken raw
negative-equity, MDD, 20/60-day coverage, stop-out, holding or after-cost profitability gates. Remote
access remains SELECT-only. The 8777 API is additive-compatible because reason codes remain bounded
strings and no existing field or URL changes.

## Verification

Domain, factor-service and MT4/MT5 repository tests cover funded baselines, raw negative equity,
post-loss replenishment, cutoff-day handling and pre-window anchors. An isolated all-route Shadow
PreflightOnly ForceRebuild must complete before release and compare old/new rejection counts without
writing the live producer directory.

## Documentation updated

Updated the AUT-POOL-001 current-state document and the Business Rules, Data and Routing and Test
Strategy authorities with the corrected equity-baseline, daily-anchor and gate-code semantics.

## Deployment and rollback

No running service is changed by the isolated rebuild. Deployment requires the normal verified
develop-to-main promotion and producer restart. Rollback restores the prior factor-domain/service
and repository code; existing runtime files and Ticket ownership remain compatible.
