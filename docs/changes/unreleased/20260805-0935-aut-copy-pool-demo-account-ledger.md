---
change_id: 20260805-0935-aut-copy-pool-demo-account-ledger
features: ["AUT-POOL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add the pinned Demo account ledger to the copy-pool header

## Before and after

The copy-pool page previously showed aggregate Demo equity and a lower-page source-to-Ticket
mapping. Operators could not see every actual position on the current Demo account or its real MT5
Deal history at the top of the page. The existing order stream was only a copier request/receipt
audit and could not substitute for broker execution history.

The Producer now writes an account-scoped public snapshot containing the pinned Login's margin
summary, all current MT5 positions and up to 200 trading Deals from the most recent 30 days. The
history read is cached for ten seconds and the complete snapshot is refreshed atomically every five
seconds. The dashboard places a dense account summary, current-position table and recent-Deal table
immediately below the page title and before manual controls. Copier-owned and other account activity
are explicitly distinguished.

## Impact

`GET /api/copy-pool/dashboard` additively returns `demoAccount`. The projection includes public
Ticket, product, side, volume, price and P/L evidence only. MT5 comments, Magic numbers, private
source keys and credentials are omitted. A snapshot whose Login/server differs from `status.json`
is discarded. Existing fields and the request/receipt order stream remain compatible.

## Verification

Producer tests cover account identity, position projection, Deal net P/L, history caching and
comment omission. Repository tests cover camel-case projection and empty state. Vue tests require
the account ledger to render before risk controls with current positions, real Deals and ownership.

## Documentation updated

Updated AUT-POOL-001, Ports and APIs, and Operations with the account snapshot contract, bounded
refresh behavior, frontend placement and public-field restrictions.

## Deployment and rollback

Promote through `develop`, cherry-pick to `main`, restart the Producer to create the public snapshot,
then restart only 8777 to load the additive projection and rebuilt frontend. Rollback removes the
panel and projection reader; the extra public JSON file is inert and can remain on disk.
