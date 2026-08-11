---
change_id: 20260811-acc-rel-last-ip-cohort-dedupe
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: performance
status: unreleased
compatibility: compatible
---

# Reuse heavy automation evidence within a current-LastIP cohort

## Before and after

Every account sharing a current LastIP with the seed repeated EA and Copy discovery despite already
being part of the same strong session cohort. This made a large LastIP group slow and increased the
temporary memory high-water mark.

## Impact

The cohort representative reads EA and Copy evidence once. Its same-current-LastIP peers still
receive CRM and LastIP propagation, but skip duplicate EA/Copy reads. Each skipped source is shown
in coverage with a readable reason; this is a performance optimisation, not a claim that the sibling
has no EA or Copy activity.

## Documentation updated

Updated ACC-REL-001 and ACC-REL-003 current-state documents plus architecture, data-routing and
test-strategy authorities.

## Verification

Application tests prove that a cohort sibling invokes only mapping/CRM sources and returns three
explicit automation-skip coverage records. Full verification and a live read-only multi-hop/memory
acceptance are required before release.

## Deployment and rollback

No public API, remote database, MT Manager or port changes occur. Deploy by restarting only 8777.
Roll back by restoring the preceding account-service commit and restarting only 8777; no migration
or remote state change is involved.
