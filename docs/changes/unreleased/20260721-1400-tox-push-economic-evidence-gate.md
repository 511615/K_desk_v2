---
change_id: 20260721-1400-tox-push-economic-evidence-gate
features: ["TOX-PUSH-001"]
change_type: behavior
status: unreleased
compatibility: compatible
---

# Require economic evidence in platform push results

## Before and after

Platform discovery could rank an account as high or severe from structure, Tick and synchronization
evidence even when its lifetime or suspected-interval net was negative or economically immaterial.
Optional positive-profit screening reduced this only when manually enabled. Discovery now treats
positive and meaningful profit as part of the final push classification rather than merely a scan
breadth option.

Structurally ranked candidates always receive the existing indexed lifetime net/deposit profile.
Non-positive lifetime net is removed before expensive Tick and peer analysis. A completed deep result
is listed only when suspected intervals have positive net and either at least 100 normalized display
currency units, or at least 50 units and 10% of cumulative qualifying deposits. Rejected deep rows
remain in a local audit artifact and do not count as failures.

## Evidence and calibration

The `用户画像.xlsx` push sheet contained 77 unique routed AC accounts. Among 61 rows without an
explicit uncertain/losing note, 51 had positive lifetime net; median net was 962.37 and median
net/deposit return was 20.62%. Among 16 manually uncertain rows, seven were non-positive; median net
was 62.07 and median return was 0.33%. Applying the final rule to the 2026-07-21 production scan
would retain three of 50 deep results and remove all five screenshot rows with negative or small
economic outcomes.

## Impact

The result list is smaller and more specific. Existing candidate controls, structure score, Tick
formulas and synchronization definitions remain unchanged. Summary and row fields are additive.
Lifetime profiling uses existing read-only indexed routes; no schema migration or MT state change is
required.

## Documentation updated

Market-pushing current state, business rules and test strategy.

## Verification

Unit tests cover negative lifetime net, negative interval net, low-return rejection, the inclusive
relative boundary and the inclusive absolute boundary. Production-image replay and the labeled
profile set are used for acceptance.

## Deployment and rollback

Restart the persistent discovery worker and account web process. Rollback restores the prior broad
result list; stored jobs and SQLite data require no conversion.
