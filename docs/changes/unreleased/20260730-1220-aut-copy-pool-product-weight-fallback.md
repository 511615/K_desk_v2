---
change_id: 20260730-1220-aut-copy-pool-product-weight-fallback
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Preserve a 100% base-weight total with sparse product coverage

## Before and after

The producer applied the 40% product diversification cap even when only one or two products passed
all hard gates. That made the base sleeve weights total only 40% or 80%, conflating selection weights
with live risk utilization.

The cap now remains hard when at least three qualified products can satisfy it. With fewer products,
the otherwise unallocatable remainder is distributed evenly across the qualified products and an
explicit fallback flag is written to source coverage. Base sleeve weights therefore total 100%,
while combination utilization and the independent live 40% product-direction cluster gate continue
to control executable risk.

## Impact

The dedicated dashboard shows actual monitor/active counts and active products from the build
contract. No account is added, no hard selection gate changes, and no database, MT account, order or
Manager state is modified.

## Verification

Producer tests cover one-, two- and three-product allocation. K_desk tests cover the additive source
coverage projection. A fresh all-source read-only preflight and Full verification remain required
before Shadow starts.

## Documentation updated

Updated the AUT-POOL-001 current-state feature document, business rules, ports/API contract and
operations producer version. Source coverage documents the additive population/product projection.

## Deployment and rollback

Rollback restores capped incomplete base-weight totals but requires no data or MT migration. The
producer and 8777 reader should be deployed together; Demo Live remains disabled.
