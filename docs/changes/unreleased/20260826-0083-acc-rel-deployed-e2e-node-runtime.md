---
change_id: 20260826-0083-acc-rel-deployed-e2e-node-runtime
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Make deployed Galaxy browser acceptance self-contained

## Before and after

The production verifier could locate its bundled `pnpm` shim while the paired Node runtime was
absent from the release shell's `PATH`. It then failed before starting the deployed Galaxy test,
leaving a functioning release without its required browser acceptance result.

## Change

- Resolve the bundled Node runtime beside the fallback `pnpm` shim when `node` is not already
  available.
- Fail with a direct runtime message only when neither an installed nor bundled Node runtime exists.
- Preserve the existing deployed Galaxy E2E command and its strict relation-display assertions.

## Impact

Release verification only. It does not alter relationship data, graph layout, account discovery,
scores, API behavior, or remote trading state.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Execute the deployed-release verifier from a shell where `pnpm` is present but `node` is not.
- Confirm the verifier resolves Node and runs the Galaxy browser acceptance test against production.

## Deployment and rollback

Standard promotion/release. The change affects only the release-side test launcher and needs no data
repair or service migration.
