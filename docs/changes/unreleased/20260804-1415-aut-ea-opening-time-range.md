---
change_id: 20260804-1415-aut-ea-opening-time-range
features: ["AUT-EA-001", "ACC-DETAIL-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# AUT-EA-001: EA opening-time range

## Before and after

The EA endpoint accepted `start` and `end`, but the EA service ignored both values while loading
subject orders and matching peer accounts. The legacy dialog had no controls for the range.

The dialog now provides optional start/end controls and an explicit query action. The selected range
filters EA seed orders and all exact or dynamic peer matching by opening time. The EA Excel report
receives the identical range.

## Impact

Existing routes and optional `start`/`end` query parameters are unchanged. Blank values retain the
former full-history behavior. All remote MySQL reads remain read-only; no MT4 or MT5 Manager action
is used.

## Documentation updated

Updated `AUT-EA-001` and `ACC-DETAIL-001` with the control behavior, opening-time semantics, cache
scope and report parity.

## Deployment and rollback

Restart the localhost account service on port `8777` to load the server-rendered dialog and EA
service changes. Rollback is the prior legacy account service revision; no data migration or local
state restore is required.

## Verification

Added legacy regression coverage for subject-query forwarding, seed scope propagation, MT5 indexed
opening-deal SQL predicates and the legacy dialog controls. Full test and governed verification are
recorded with the implementation.
