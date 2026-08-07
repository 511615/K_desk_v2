---
change_id: 20260807-1405-aut-pool-001-demo-minimum-cluster-floor
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Demo minimum-lot cluster floor

## Before and after

The explicit Demo minimum-lot override could mark an XAUUSD sleeve executable while the live
product-direction cluster gate could not fit even one 0.01-lot order. At the observed 9,795 USD
equity, one gold minimum lot carried about 64.19 USD of stress while the ordinary 40% cluster share
was about 58.77 USD. Every otherwise eligible gold entry was therefore quantized to zero.

The Demo-only cluster allowance is now the greater of its ordinary 40% share and one product
minimum lot's stress. This admits one indivisible minimum lot when total portfolio stress and margin
still permit it. A second same-direction minimum remains rejected when it exceeds that bounded
allowance.

## Impact

This changes sizing only when `-AllowDemoMinLotOverride` is explicitly enabled on
`ACCMGlobal-Demo` in `StagedLive`. Production/non-Demo modes, zero-weight sleeves, old-position
no-chase, signal expiry, quote/spread/database gates, whole-portfolio stress and margin controls are
unchanged.

## Documentation updated

AUT-POOL-001 and the business rules now define the adaptive one-minimum-lot cluster floor. The test
strategy records the realistic gold boundary and second-lot rejection.

## Verification

Producer sizing tests cover the observed stress boundary, the first 0.01-lot admission and the
second same-direction rejection. Fast and Full governed verification are required before promotion.

## Deployment and rollback

Promote from the tested development branch, then restart only the unique Producer while the Demo is
flat. Rollback returns to the ordinary 40% cluster cap; persisted Ticket ownership and source cursors
remain compatible.
