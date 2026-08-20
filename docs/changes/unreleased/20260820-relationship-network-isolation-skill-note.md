---
change_id: 20260820-relationship-network-isolation-skill-note
features: ["GOV-LIFECYCLE-001"]
change_type: hardening
title: Record the isolated relationship-network v2 workflow in maintenance guidance
status: unreleased
compatibility: compatible
---

## Before and after

Before, the maintenance guidance described the general `dev/main/back` release flow but did not
record the relationship-network pilot's dual-version boundary, named temporary branch exception,
feature flags or module-level rollback behavior.

After, both the repository and installed maintenance Skills require relationship-network v2 to be
developed as a named `feature/acc-rel-*` branch from `dev`, with normalized evidence contracts,
independent layers, compatibility tests and flags defaulting off in production. The legacy API and
Galaxy view remain available until an explicit rollout.

## Impact

This is governance and documentation only. It does not enable v2, change source databases or alter
the production route.

## Documentation updated

- `skills/kdesk-maintenance/SKILL.md`
- `C:\Users\amber\.codex\skills\kdesk-maintenance\SKILL.md`
- `docs/features/governance/feature-lifecycle.md`

## Verification

- Governance artifact generation and Fast verification are required after this record is committed.
- The note is checked against Feature ID `GOV-LIFECYCLE-001`.

## Deployment and rollback

No deployment is performed. If the v2 pilot is unstable, disable its flags and continue using the
legacy relationship API/page; production rollback remains controlled by `back` and release snapshots.
