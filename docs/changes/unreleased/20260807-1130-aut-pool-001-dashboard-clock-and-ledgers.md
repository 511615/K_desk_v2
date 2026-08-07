---
change_id: 20260807-1130-aut-pool-001-dashboard-clock-and-ledgers
features: ["AUT-POOL-001"]
change_type: ui_detail
status: unreleased
compatibility: compatible
---

# AUT-POOL-001 dashboard clock and current ledger display

## Before and after

The dynamic copy-pool dashboard needed an explicit Beijing-time display and clearer separation of
current Demo account/Ticket ownership from historical execution events. The dashboard now uses a
shared Beijing-time formatter and renders those facts in independently bounded panels.

## Impact

This is a read-only display and formatting change. It does not alter pool selection, source routing,
strategy execution, account state, or broker/MT operations.

## Documentation updated

Updated AUT-POOL-001 code/test mappings and current UI behavior.

## Verification

Focused TypeScript/Vue tests cover Beijing-time formatting, bounded dashboard payload mapping and
the CopyPool page. Full repository verification is required before release.

## Deployment and rollback

The change is additive. Rollback restores the prior dashboard rendering only; no state migration or
data repair is needed.
