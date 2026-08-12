---
change_id: 20260812-acc-rel-root-chain-rendering
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Render a root chain for every relationship node

## Before and after

The overview drew only the selected account's branch. A non-selected account could therefore appear
without any visible route to the problem account. The overview now builds a deduplicated visible
parent-chain edge set for every rendered account and concrete IB identity, from the problem account
outward. The selected branch continues to add only evidence not already in that set. Node radii were
increased so the account number, local mark and terminal indicators are usable at normal zoom.

## Impact

This is a Canvas-only rendering fix. It does not query additional remote data, change propagation,
or alter the relationship API contract. Hidden CRM/evidence connector nodes remain hidden; their
relationship type is carried by the collapsed visible segment.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- API page regression test requires the root-chain renderer and its user-facing guarantee.
- Inline Canvas JavaScript syntax check passes.
- Fast and Full governed verification are required before deployment.

## Deployment and rollback

Restart only the verified `kdesk.api.account_app` listener on 127.0.0.1:8777. Rollback is a restart
at the preceding Git revision; no data migration or source write occurs.
