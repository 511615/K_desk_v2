---
change_id: 20260722-2345-tox-bonus-cycle-margin-level
features: ["TOX-BONUS-001", "TOX-BONUS-SCAN-001"]
change_type: behavior
status: unreleased
compatibility: compatible
---

# Use full-cycle margin level for bonus heavy-position risk

## Before and after

The preventive rule only considered positions opened within 24 hours after Credit and compared
standard lots with funded money. It now checks every position state throughout the active Credit
cycle and uses the standard margin level `equity / used margin * 100%`. The first cycle minimum at
or below 200% is heavy positioning; at or below 100% is labelled extreme liquidation pressure.

## Correctness

Historical states reverse cash equity from the current balance and loaded ledger, replay cash,
Credit and closed-profit changes, and estimate used margin from opening price, contract size and
configured leverage. Historical floating P/L snapshots are unavailable and are labelled estimated.
An active current-cycle state prefers actual current Equity and Margin. Evidence retains the exact
minimum timestamp, equity, used margin, standard lots, order count and up to 50 concurrent orders.

The inclusive 20% Credit/cash eligibility gate remains mandatory. Direction, withdrawal and a
visible opposing leg remain optional evidence. The preventive path still reaches 75 rather than
claiming a confirmed historical breach solely from margin pressure.

## Impact

Eligible Credit cycles can now be flagged for heavy positioning that occurs days after the grant,
while accounts above the 200% margin-level line no longer qualify merely because their raw lots look
large. Account Toxic results and full-platform rows add margin-level evidence without changing request
payloads, durable job storage or the 20% funding gate.

## Performance and compatibility

Cycle replay updates active margin, lots and equity once per event and resolves exact orders only
for the retained minimum, avoiding quadratic work on large histories. Old `earlyPeak*` fields remain
as compatibility aliases, and the frontend falls back to them for completed historical jobs.
Cent/USC scaling applies only to monetary values; displayed standard lots are no longer scaled.

## Documentation updated

Updated both bonus feature documents plus business-rule, data-routing, API and test authorities.

## Verification

Domain tests cover full-cycle late positioning, threshold behavior, exact minimum-point evidence,
current open positions, Cent lot preservation and the 10,000-order performance guard. Discovery and
frontend tests cover additive projection and old-job fallback. Fast and Full verification plus
desktop and mobile browser QA are required before deployment.

## Deployment and rollback

Rebuild the frontend and restart the account and worker services. Rollback restores the old rule;
new stored fields are additive and remain harmless to older readers.
