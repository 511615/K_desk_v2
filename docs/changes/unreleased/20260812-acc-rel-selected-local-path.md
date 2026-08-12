---
change_id: 20260812-acc-rel-selected-local-path
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Limit graph links to the selected account's evidence

## Before and after

The overview rendered every visible node's root path concurrently. This made accounts that were only
separately linked through the problem account look related to one another. The graph now renders only
the selected account's direct evidence cluster/outward descendants and its own deduplicated path back
to the problem account. Siblings linked solely through the root are not joined or highlighted.

## Impact

This changes Canvas presentation only. It adds no database or remote queries and leaves relationship
discovery, scoring and API payloads unchanged. Selecting another account recomputes the corresponding
local cluster and root path.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Page regression requires the explicit selected-account/local-path wording.
- Inline Canvas JavaScript syntax check passes.
- Fast and Full governed verification are required before deployment.

## Deployment and rollback

Restart only the verified `kdesk.api.account_app` listener on 127.0.0.1:8777. Rollback is a restart
at the preceding Git revision; no data migration or source write occurs.
