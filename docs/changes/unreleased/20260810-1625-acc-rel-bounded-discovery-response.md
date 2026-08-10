---
change_id: 20260810-1625-acc-rel-bounded-discovery-response
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Bound account relationship discovery response time

## Before and after

The first deployed score-propagated graph recreated the temporary Kuzu graph after every discovered
account and automatically requested multi-platform Toxic evidence. At low thresholds this could grow
memory and CPU without returning a page response promptly.

## Impact

Recursive discovery now uses the pure in-memory scorer and creates the temporary Kuzu graph only once
for the final response. Each source has a six-second wait budget, total discovery has a 12-second
budget, and partial coverage is returned explicitly. Toxic is opt-in in the page and limited to two
high-score checks. Browser waiting is limited to 45 seconds with retry guidance.

## Documentation updated

ACC-REL-001 and ACC-REL-003 now describe the opt-in Toxic control, single final Kuzu materialization,
source/total query budgets and partial-result behavior. Architecture, routing, API, business-rule and
test authorities record the same response-time contract.

## Verification

Unit tests prove one Kuzu materialization and timeout coverage. A read-only AC CN MT5 account smoke
test at threshold 12 returned a partial graph in 14.62 seconds.

## Deployment and rollback

Restart only 8777 after Full verification. Rollback restores the prior commit and restarts only 8777;
no remote or local authoritative data needs restoration.
