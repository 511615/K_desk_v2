---
change_id: 20260811-acc-rel-deadline-cutoff
features: ["ACC-REL-003"]
change_type: performance
status: unreleased
compatibility: compatible
---

# Stop late relationship follow-up reads at the discovery deadline

## Before and after

An account evidence read was capped by the remaining discovery time, but after it consumed that
budget the service could still start same-account LastIP or optional Toxic follow-up work. The service
now scores already returned evidence and returns its verified partial graph at that point.

## Impact

The propagation result remains complete for evidence already received. The response explicitly retains
the existing `queryBudgetExhausted` partial-result marker; it never claims skipped late reads were run.

## Documentation updated

Updated ACC-REL-003 deadline behavior.

## Verification

Focused relationship and Kuzu-page tests, plus governed Fast and Full verification, cover the change.

## Deployment and rollback

Deploy through the account-only 8777 launcher. Roll back by restarting the preceding commit; no
database, Kuzu, CRM or MT state is changed.
