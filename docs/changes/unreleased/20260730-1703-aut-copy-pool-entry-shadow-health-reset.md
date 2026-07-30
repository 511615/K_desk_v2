---
change_id: 20260730-1703-aut-copy-pool-entry-shadow-health-reset
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Preserve entry qualification across transient health failures

## Before and after

- A momentary unhealthy operational gate during entry shadow previously returned the sleeve to
  monitor and cleared both consecutive ranking qualifications.
- An otherwise qualified entry-shadow sleeve now remains in entry shadow with zero executable
  weight and restarts the complete continuous-health window configured by its activation policy.
- Losing factor qualification, current comprehensive product profit or activity eligibility still
  returns the sleeve to monitor immediately and clears the entry qualification state.

## Impact

The change affects only the Demo Producer's in-memory dynamic sleeve transition. It does not weaken
an execution gate, place an order, change an API, alter databases or modify MT state. A pending first
source-reconciliation frame can no longer erase a completed ranking qualification, but the sleeve
cannot become active until the newly started health window has elapsed.

## Verification

Pure domain tests cover health-window restart, retained qualification, delayed promotion and
immediate disqualification fallback. Producer integration covers a pending reconciliation count of
one followed by healthy frames and verifies that promotion occurs only after the restarted window.

## Documentation updated

Updated AUT-POOL-001, business rules and test strategy with the continuous-health reset behavior.

## Deployment and rollback

No deployment or process action is included. Rollback restores the former transition behavior; no
data migration or runtime-state conversion is required.
