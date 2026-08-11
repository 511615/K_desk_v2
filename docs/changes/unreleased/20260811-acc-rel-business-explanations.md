---
change_id: 20260811-acc-rel-business-explanations
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: improvement
status: unreleased
compatibility: compatible
---

# Explain relationship layers and evidence in account-business terms

## Before and after

The Kuzu relationship page displayed technical labels such as `第 1 圈`, `1 跳` and `附加线索` without
stating how an account was reached from the problem account. CRM/IB cards could therefore be mistaken
for broad downstream IB membership rather than the IB's own trading accounts.

The selected-account caption now states the problem-account-relative layer and narrates the evidence
route. Every relationship selector and evidence header has a type-specific business explanation. The
direct-IB selector explicitly says that it represents the problem account's direct superior IB's own
trading accounts; peer cards say their layer relative to the problem account instead of a bare hop count.

## Impact

The response contract, scoring, routing, read-only source behavior and graph placement are unchanged.
This is a presentation-only clarification of existing facts and limitations.

## Documentation updated

Updated ACC-REL-001 and ACC-REL-003 current-state documentation for human-readable layer, path and
evidence-family wording.

## Verification

API page tests assert that the route and direct-IB business explanation are delivered. Governed Fast
and Full verification run before deployment.

## Deployment and rollback

Deploy through the main-branch account-only 8777 launcher. Roll back by restarting 8777 from the
preceding commit; no database, CRM, MT or Manager state changes.
