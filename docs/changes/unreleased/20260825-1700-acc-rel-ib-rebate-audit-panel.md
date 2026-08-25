---
change_id: 20260825-1700-acc-rel-ib-rebate-audit-panel
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: improvement
status: unreleased
compatibility: compatible
---

# Direct-IB rebate audit panel

## Problem

The relationship snapshot already returned `ib_direct_rebate` members and their inclusion evidence,
but Galaxy rendered them as a generic IB relationship. Operators could not see the rebate-led
selection reason or the returned money and deal metrics without tracing an individual edge.

## Before and after

Before, direct-IB rebate evidence was visually indistinguishable from a normal IB line.

After, Galaxy renders a dedicated `IB 直属返佣核查` side-panel card per direct IB. It reports the
returned abnormal/total count where available and lists each materialised member with its inclusion
reason, status, actual trade P/L, rebate, combined profit, rebate share, related deal count and latest
rebate record. Selecting a row selects the account only and cannot toggle a star-track community.

## Impact

This is a client-side presentation change using the existing read-only relationship-network snapshot.
It changes neither query routing, expansion eligibility, scoring, relation construction nor source
database state. Accounts absent from the returned bounded anomaly projection are not implied by the
panel.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Added the Galaxy page contract test for the dedicated IB rebate panel markers.
- Ran the focused Galaxy rendering and immutable-click-dispatch tests.
- Release verification will load the live `216056` Galaxy page and inspect the returned direct-IB
  rebate evidence, including the rebate-dominant account row.

## Deployment and rollback

Deploy through the standard development promotion and production release scripts. Roll back by
releasing the immediately previous production commit; no data migration or remote write is involved.
