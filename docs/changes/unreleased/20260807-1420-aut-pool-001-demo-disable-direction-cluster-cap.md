---
change_id: 20260807-1420-aut-pool-001-demo-disable-direction-cluster-cap
features: ["AUT-POOL-001"]
change_type: behavior
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: disable the direction-cluster cap for explicit Demo testing

## Before and after

When `AllowDemoMinLotOverride` is explicitly enabled for `ACCMGlobal-Demo` in `StagedLive`, the
product-direction cluster cap no longer limits new independent customer Tickets. The unchanged
whole-portfolio stress budget, margin capacity, ownership, data, quote, spread and stop gates still
apply. Non-Demo execution retains the 40% product-direction cluster cap.

Previously the explicit Demo override admitted only one product-direction minimum lot. After this
change, eligible same-direction customers may each own an independent minimum-lot Ticket until the
unchanged whole-portfolio stress or margin budget is exhausted.

## Impact

The Demo experiment needs observable order flow from multiple same-direction active customers.
The former adaptive one-minimum cluster floor admitted the first XAUUSD minimum lot but rejected the
next one even when the whole-portfolio stress budget still had capacity.

Non-Demo execution retains the ordinary 40% product-direction cap. No API, snapshot schema,
database routing or MT ownership contract changes.

## Verification

- Regression proves two realistic same-direction XAUUSD minimum lots are accepted in explicit Demo
  mode and the next lot is rejected by the unchanged whole-portfolio stress budget.
- Existing non-Demo cluster-cap and margin/risk tests remain required.

## Documentation updated

- `docs/features/automation/dynamic-copy-pool-monitor.md`
- `docs/BUSINESS_RULES.md`
- `docs/TEST_STRATEGY.md`

## Deployment and rollback

Restart the single Producer after merging to main; the 8777 service does not need a restart. Roll
back this commit and restart the Producer to restore the adaptive one-minimum cluster floor. No
MT4/MT5 Manager operation is involved.
