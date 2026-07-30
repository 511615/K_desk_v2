---
change_id: 20260730-1711-aut-copy-pool-demo-fast-activation
features: ["AUT-POOL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Explicit Demo fast activation

## Before and after

- Dynamic sleeves normally require two consecutive active-zone rankings and ten continuously
  healthy entry-shadow minutes.
- The explicit `-DemoFastActivation`/`--demo-fast-activation` option selects one ranking and two
  healthy minutes only on `ACCMGlobal-Demo` in `StagedLive`.
- Producer and dashboard status expose requested/effective state and the effective thresholds;
  unsupported server or mode combinations visibly retain the normal policy.

## Impact

The option shortens the observation period only when every explicit scope condition matches. It
does not enable live trading, bypass operational or risk gates, chase existing source positions,
increase weight while unhealthy, change APIs incompatibly or modify database/MT Manager state.

## Verification

Domain tests pin the one-ranking/two-minute and default two-ranking/ten-minute policies. Producer
tests cover CLI parsing, server/mode enforcement and a pending reconciliation health reset using the
two-minute configuration. Snapshot repository tests cover the additive status fields.

## Documentation updated

Updated AUT-POOL-001, operations, business rules and test strategy for the explicitly scoped option.

## Deployment and rollback

No deployment or process action is included. The option is disabled by default; rollback removes
the switch and additive status fields without a data migration.
