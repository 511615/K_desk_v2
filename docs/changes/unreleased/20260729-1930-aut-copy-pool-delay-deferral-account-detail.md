---
change_id: 20260729-1930-aut-copy-pool-delay-deferral-account-detail
features: ["AUT-POOL-001"]
change_type: change
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Defer historical delay factor and simplify account detail

## Before and after

V0.1 no longer loads historical Demo Tick partitions during pool construction. Historical delay
score and hard gates are disabled explicitly, while the remaining six factors normalize to 100%.
Real-time quote age, source staleness, measured signal latency and entry/exit expiry remain active;
new-risk signals use the lower of five seconds and holding P25 divided by three.

The account detail page removes the embedded copy-experiment panel and its dashboard request.
Account links from the dedicated copy-pool page still open the existing platform/server-aware detail
route. The dashboard exposes explicit deferred-delay status so zero compatibility metrics cannot be
misread as failed evidence.

## Impact

Pool composition changes because the remaining six factors are normalized without historical
delay evidence. Existing real-time execution safety gates remain active. The localhost dashboard
adds explicit status fields; the legacy account detail page becomes smaller and no longer requests
copy-pool data. No remote database, MT account, order or Manager state is changed.

## Documentation updated

Updated the AUT-POOL-001 feature document, business rules, data routing, ports/API contract,
operations, test strategy and execution-quality plan. This record supersedes the earlier planned
V0.1 Tick acceptance scope without deleting its future-design history.

## Verification

Producer tests cover no Tick-cache access, normalized scoring, hard-gate removal and the runtime
signal-age cap. K_desk backend/frontend tests cover deferred status, dedicated-page rendering and
absence of copy-pool markup and requests from account detail. Full governance verification remains
required before handoff.

## Deployment and rollback

Deploy the producer snapshot contract and 8777 build together. Rollback restores the previous
producer and UI; no database, MT account or Manager migration exists. The producer remains stopped
until read-only preflight and Shadow acceptance pass.
