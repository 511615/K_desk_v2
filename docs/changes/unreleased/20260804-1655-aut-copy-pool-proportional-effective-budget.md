---
change_id: 20260804-1655-aut-copy-pool-proportional-effective-budget
features: ["AUT-POOL-001"]
change_type: business-rule
status: unreleased
compatibility: compatible
---

# Preserve proportional weights under the effective-risk budget

## Before and after

Base sleeve weights already represented a 100% allocation while the runtime client-risk utilization
budget remained a separate 25%. When current effective weights exceeded that budget, the Producer
previously removed the excess from the lowest-ranked sleeves first. This could leave a hard-qualified
account with positive base weight but zero effective weight.

The Producer now multiplies every positive effective sleeve weight by one common scale when their
sum exceeds the client-risk budget. Relative percentages are preserved, the sum remains bounded at
25%, and a lower-ranked qualified sleeve is not eliminated solely by portfolio budget enforcement.

## Impact

This changes Producer allocation only. It does not increase the 25% client-risk utilization budget
or bypass terminal permission, signal expiry, quote/database health, margin, loss, product, Ticket
ownership or other execution gates. APIs and remote read-only data access are unchanged.

## Verification

A Producer regression proves that two fresh Demo-fast sleeves with 20% current base weight each are
both scaled to 12.5%, rather than 20% plus 5%, and that their total equals the 25% budget.

## Documentation updated

Updated AUT-POOL-001, Business Rules and Operations to distinguish 100% base allocation from the
separate proportionally enforced 25% runtime client-risk utilization budget.

## Deployment and rollback

Promotion requires the normal controlled Producer restart. Rollback restores the former ranked
tail-reduction behavior without any MT5 or persisted-state migration.
