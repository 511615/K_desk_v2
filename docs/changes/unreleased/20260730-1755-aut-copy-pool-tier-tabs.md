---
change_id: 20260730-1755-aut-copy-pool-tier-tabs
features: ["AUT-POOL-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Browse customer-pool tiers in place

## Before and after

The customer-pool tier panel showed static numeric cells only. Operators had to find the same sleeve
again in the large pool table to inspect the customers in a tier.

The panel now provides Chinese tier tabs for active, entry observation, monitor, reserve, recovery,
execution suspension and hard rejection. Selecting a tab displays the matching account-product
sleeves in place with actual trading Login links, product, planned/effective weights, current state
and primary reason. Dynamic sleeve state takes precedence over the daily pool tier; only material
client-risk states override that tier.

## Impact

This is a read-only Vue presentation change. It reuses the existing dashboard `pool`,
`dynamicSleeves` and `clientRisks` projections, adds no API, does not expose aliases, and cannot
change producer selection, customer state or Demo execution.

## Verification

Frontend helper tests cover tier precedence, localized labels and reasons. A mounted Vue page test
covers tier-count rendering, tab switching, Login detail visibility and absence of `C001` aliases.
Full verification covers 306 main/legacy Python tests, the Producer suite, 22 frontend tests and the
Vue production build.

## Documentation updated

Updated AUT-POOL-001 current-state UI behavior and acceptance coverage.

## Deployment and rollback

Deployment promotes the verified frontend through `develop` and `main`, then restarts only the 8777
account service. The independently running Producer is not restarted. Rollback is limited to
reverting the frontend tabbed read view and its tests; dashboard and producer snapshot contracts
remain unchanged.
