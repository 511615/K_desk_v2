---
change_id: 20260722-1900-tox-bonus-historical-breach
features: ["TOX-BONUS-001", "TOX-BONUS-SCAN-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Detect historical funded breaches and remove direction gating

## Before and after

The preventive path required 80% same-direction exposure and reached only warning without a visible
opposite account. A recovered negative account could also lose its strongest evidence because only
the cycle's final net loss was considered. The detector now treats a 50%+ bonus followed within 24
hours by 0.50 peak lots per 1,000 funded units as high risk regardless of buy/sell concentration,
withdrawal or visible peer. It also asks whether the account ever breached funding during the full
bonus cycle, not only whether it is negative now.

## Correctness

A confirmed negative-balance reset/clearing event, the lowest historical cumulative closed trading
result reaching cash plus Credit, or current negative balance/equity establishes a severe historical
breach. Loss reaching 75%-99% of funding warns. Later profit, deposit or reset does not erase the
retained low point. Trades closing at the same timestamp are netted before comparison to prevent row
ordering from creating a false breach. The existing inclusive 20% bonus-to-cash hard gate remains.
A recovered near-breach that later completes an extraction loop retains the stronger extraction
floor; the unpaired-sacrifice cap applies only when no extraction loop exists.

Visible five-second opposite-order coverage now changes confidence and evidence wording only for
the high-bonus heavy-position path; it does not control classification or score. Peer matching
continues to support the separate coordinated-sacrifice and extraction evidence paths.

## Impact

No endpoint, request, database schema or remote state changes. Existing response fields remain
compatible. Evidence cycles add the historical low timestamp, structured reset rows, breach flags
and breach explanations. Single-account checks and platform deep checks share the same domain rule.

## Documentation updated

Updated `TOX-BONUS-001`, `TOX-BONUS-SCAN-001`, business rules, data routing and test strategy.

## Verification

Focused tests cover high-bonus balanced exposure, peer confidence without score promotion,
negative-balance resets, loss followed by recovery, current negative balance/equity, the 75% warning
boundary, the 20% hard gate and same-time close netting. Full verification and read-only replay are
recorded at handoff.

## Deployment and rollback

No migration or frontend build change is required. Restart interactive and discovery workers to
load the domain rule. Rollback restores the prior domain code; durable historical job snapshots
remain readable and unchanged.
