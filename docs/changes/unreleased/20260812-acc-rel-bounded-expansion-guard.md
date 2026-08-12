---
change_id: 20260812-acc-rel-bounded-expansion-guard
features: ["ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Prevent broad relationship expansion from exhausting the account service

## Before and after

An IB direct-rebate branch could materialize up to 2,000 account candidates, then request further
remote evidence for all score-eligible accounts without a request-wide deadline. A sufficiently broad
branch could retain large graph payloads and source work in the 8777 account-service process.

Live account investigation now has a 30-second discovery deadline, at most 48 remote account
expansions, three-second evidence waits, a 150-account direct-IB branch limit, and a 120-node / 360-edge
Kuzu projection limit. It returns the evidence already read with an explicit truncation message.

## Impact and compatibility

The API contract and relationship semantics remain compatible. A broad branch may now return a
partial, explicitly marked graph rather than continuing indefinitely. The direct-rebate list remains
read-only and grouped to account level; top-IB aggregates remain unexpanded.

## Documentation updated

Updated ACC-REL-003 safety budgets, source waits, branch limits and Kuzu projection limits.

## Verification

Added a broad-IB regression that proves the remote account-expansion safety cap stops the pending
queue and reports why. Focused relationship tests, fast and full governed verification are required.

## Deployment and rollback

Deploy by restarting only the 8777 production account service. No database, CRM, MT4, MT5 Manager
or Kuzu persistent data is changed. Roll back by restoring the prior verified account-service commit
and restarting 8777.
