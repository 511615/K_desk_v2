---
change_id: 20260804-1540-aut-copy-pool-weight-floor-relaxation
features: ["AUT-POOL-001"]
change_type: business-rule
status: unreleased
compatibility: compatible
---

# Allocate weight across hard-qualified sleeves

## Before and after

The pool previously applied a second `monitor_score > 0.55` gate after the hard factor and cost
filters. It also computed allocation alpha as `(adjusted_score - 0.55)^1.5`, so a hard-qualified
account below that score received zero base weight and could never be copied.

Hard-qualified sleeves that pass the existing holding, copyability and stressed-profit checks now
remain eligible for ranking. Their positive adjusted factor scores are used directly as proportional
allocation alpha. The score changes the percentage; it does not erase the account from the active
weight pool.

## Cache and deployment behavior

The producer uses a same-day v8 weight-floor migration for accepted v6/v7 snapshots. It reuses the
complete private universe, recomputes selection and weights, and preserves source-position to Demo-
Ticket ownership. No remote writes, historical expansion or old-position chasing is introduced.

Technical execution gates remain active: database/quote health, terminal permission, signal expiry,
portfolio and per-client risk, margin, product limits and Ticket ownership still control whether a
new order can be sent.

## Impact

This is a compatible Producer-only business-rule correction. Dashboard fields and 8777/8766 routes
are unchanged; their existing base-weight, activity and pool-tier values reflect the new allocation
only after the controlled Producer restart. Remote CRM/trading databases remain read-only, and no
MT4/MT5 Manager operation is introduced.

## Verification

Producer regression coverage proves that a hard-qualified sleeve below 0.55 receives positive base
weight, that the old accepted cache migrates to the new weight schema, and that the factor gate still
rejects failed cost evidence. Full K_desk verification is required before promotion.

## Documentation updated

Updated AUT-POOL-001 current-state, the automation business rules and the Producer operations
runbook with positive-score allocation, v7-to-v8 cache migration and unchanged execution gates.

## Deployment and rollback

Development testing does not restart a service. Promotion restarts only the copy-pool Producer from
the verified main worktree, which migrates a valid same-day v7 cache without a database rebuild.
Rollback is code-only. The prior v7 snapshot remains readable, and restoring the previous Producer
version restores the former weight-floor behavior without changing MT5 state or ownership records.
