---
change_id: 20260729-1915-aut-copy-pool-v4-dashboard-projection
features: ["AUT-POOL-001"]
change_type: api
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Project execution-quality snapshots on 8777

## Before and after

The v4 copier writes delay-replay, drawdown, holding-quality and dynamic-schedule fields, but the
8777 dashboard discarded them. The local snapshot projection now exposes a bounded, additive public
representation for every current account-product sleeve.

## Impact

Pool rows add factor readiness, base score and validated gate codes, all seven factor components,
entry/exit/combined delay metrics, drawdown coverage and holding quality. The response adds
`dynamicSleeves` and `scheduler`. Dynamic state is joined to a public route and product before it is
returned, so private composite sleeve keys and unknown state never enter the API.

No database, MT terminal, MT Manager, copier, order or account operation is introduced. Existing
fields, pages and alias redirects remain compatible.

## Documentation updated

Updated AUT-POOL-001 current behavior plus API, data-routing, operations and test authorities.

## Verification

`tests/test_copy_pool_monitor.py` covers the v4 projection and verifies that an unmapped private
sleeve key is omitted.

## Deployment and rollback

This is an additive 8777-only read projection. Deploy with the existing main service; do not start a
new port or process. Rollback restores the previous K_desk build, after which v4 fields are ignored
while the copier snapshots remain unchanged.
