---
change_id: 20260730-2350-aut-copy-pool-execution-stability
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Stabilize minimum-lot execution and MT4 signal time

## Before and after

Raw MT4 `OPEN_TIME` was interpreted as Beijing time even though every replicated MT4 source stores
that platform datetime in UTC. A new AC MT4 position observed in about three seconds was therefore
misclassified as approximately eight hours old and rejected as expired.

Separately, the explicit Demo minimum-lot exception opened a 0.01-lot Ticket but did not preserve
that exception on the next reconciliation. Two same-direction source Positions could alternately
close and reopen the single allowed minimum lot on each 500 ms cycle.

The producer now attaches UTC to raw MT4 open time, preserves an eligible minimum-lot owner while no
other Ticket occupies its product/direction, and hard-stops plus flattens before sending more than
eight open requests in a rolling minute.

## Impact

Timely MT4 positions can enter the normal copy decision. Demo minimum-lot ownership remains stable
across reconciliation and cannot generate an open/close oscillation. The order-rate guard limits the
blast radius of any future opening loop. Remote databases and MT Manager remain read-only; the only
write path remains the explicitly authorized MT5 Demo client account.

## Verification

Regressions cover UTC conversion of a real-shape MT4 current row, a three-second snapshot signal,
two same-direction source Positions across repeated reconciliation and the rolling open-request hard
stop. Full verification covers application, legacy, Producer and frontend suites plus the production
build.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing authority, business rules, operations and test
strategy.

## Deployment and rollback

Deploy only after `develop` and `main` Full verification. Stop the old Producer, verify the Demo
account is flat, promote the tested commit, then restart from clean `main`. Rollback stops the new
Producer and returns to the prior source; do not restart the known oscillating version with live Demo
authorization.
