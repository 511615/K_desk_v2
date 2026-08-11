---
change_id: 20260811-1230-aut-pool-001-exit-only-ticket-recovery
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: preserve owned Tickets when an account leaves the pool

## Before and after

Before this fix, a forced complete pool rebuild discarded the persisted independent source-position
book before startup reconciliation. If an account had since failed the account-level hard gates but
still had a model-owned Demo Ticket, validation saw the real Ticket as `unknown_demo` and stopped the
Producer. The same boundary could also treat an account removed by hourly discovery as unsubscribed
before its existing source position had finished reducing.

Bootstrap now restores the independent source-position/Demo-Ticket book for both cached and complete
rebuilds. When a restored owned Ticket belongs to an account outside the new qualified universe, the
source route and represented products are retained as an `exit-only` risk-ledger subscription. Its
base/effective weights are zero and it cannot open or add risk. Source reductions are copied to the
existing Ticket using the authoritative source-volume change; source closes and reversals close the
old Ticket first. The subscription is removed after its owned Tickets are gone. Exact Ticket mapping
validation remains fail-closed for an unowned or missing Demo Ticket.

## Impact

This is a startup/rebuild safety correction. It prevents a valid model-owned Ticket from being
misclassified as an unknown external Ticket and keeps the source route available for exit handling.
It does not promote a hard-filtered account, grant it weight, or change the account/product gates.
No public endpoint or snapshot field is removed; exit-only status is private runtime state projected
through the existing risk/status surfaces.

## Documentation updated

Updated the AUT-POOL-001 current-state document with the exit-only lifecycle and ownership rules.
No API or OpenAPI shape changes are intended.

## Verification

Producer regressions must cover: a complete rebuild restoring an owned Demo Ticket; reconstruction of
the composite source route for a filtered account; zero base/effective weight and no new-risk request;
proportional source reduction; close-before-opposite on reversal; removal after source close; and the
existing unknown/missing Ticket hard-stop. Run the required Fast and Full K_desk verification before
promotion.

## Deployment and rollback

Deploy only from the tested main revision, with one Producer instance and the existing read-only
AC/DBG connections. No MT4/MT5 Manager, account, order, database or server state is modified by the
fix. If rollback is required, stop the single Producer and restore the preceding main revision;
reconcile the persisted source-position/Demo-Ticket book before any new-risk activation.
