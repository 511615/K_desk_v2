---
change_id: 20260722-1154-tox-bonus-preventive-heavy-position
features: ["TOX-BONUS-001", "TOX-BONUS-SCAN-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Warn on high-bonus heavy positioning before extraction

## Before and after

The detector emphasized completed or attempted extraction, locked profit and realized sacrifice.
It also discarded currently open MT4/MT5 positions. A high-Credit account could therefore establish
the risky leg of a cross-platform hedge without warning until positions closed or funds moved.
The detector now retains open positions and has an independent preventive exposure path that does
not require withdrawal, realized profit or a visible peer.

## Correctness

The path requires every one of: the existing 20% hard eligibility gate, Credit at least 50% of
paired cash, entry within 24 hours, early peak concurrent exposure at least 0.50 standard lots per
1,000 cash-plus-Credit units, and at least 80% same-direction lots. Concurrent exposure avoids
misclassifying high-turnover small-order EA activity. Without a visible opposing leg the path is
capped at warning; five-second opposite matches covering at least 40% of lots promote high risk.
Missing peer evidence cannot clear the warning because a hedge may exist on another platform.

## Impact

No endpoint, request, database schema or remote state changes. Evidence cycles add early trade,
open-position, peak exposure, direction concentration and preventive-path fields. MT5 opening-only
deal groups and MT4 1970-sentinel positions now participate in read-only scoring. Existing closed
cycle paths and the 20% hard gate remain compatible.

## Documentation updated

Updated `TOX-BONUS-001`, `TOX-BONUS-SCAN-001`, business rules, data routing and test strategy.

## Verification

Focused tests cover warning without extraction/peer, visible synchronized promotion, low ratio,
light exposure, balanced direction, late entry and current MT4/MT5 position normalization. Read-only
replay found the preventive path in four labeled accounts: each had 100% Credit, 100% early direction
concentration and 0.75-2.00 peak lots per 1,000 funded units. In the latest 100-account deep cohort,
all 37 previous high/severe results retained their level without a new preventive promotion. Only
two of 63 below-warning accounts had 50%+ Credit; their 0.041/0.066 peak exposure and approximately
60% direction concentration kept both at their original 28.5/22.3 scores.
Production API acceptance for labeled account 615737 retained its 90/severe conclusion and added
the preventive trigger with 2.00 peak concurrent lots, 2.00 lots per 1,000 funded units and 100%
direction concentration. The complete read-only check finished in 1.1 seconds.

## Deployment and rollback

No migration or frontend build change is required. Restart interactive and discovery workers to
load the rule. Rollback restores the prior domain and adapter code; existing job snapshots remain.
