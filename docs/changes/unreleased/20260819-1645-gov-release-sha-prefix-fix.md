---
change_id: 20260819-1645-gov-release-sha-prefix-fix
features: ["GOV-LIFECYCLE-001"]
change_type: bugfix
title: Accept the abbreviated runtime Git SHA during release verification
status: unreleased
compatibility: compatible
---

## Before and after

Before, the verifier compared the full release SHA as though the runtime metadata returned a full
SHA. The API intentionally exposes a short SHA prefix, so a valid deployment was rejected and the
release rollback path ran.

After, the verifier checks that the runtime SHA prefix is the beginning of the intended full SHA.

## Impact

This only corrects post-start release identity validation. It does not change API or database data.

## Documentation updated

- `scripts/verify_deployed_release.ps1`
- `tests/test_production_versioning.py`

## Verification

- PowerShell parser check passed.
- Production versioning tests passed.

## Deployment and rollback

Deploy through `scripts\\release_prod.ps1`; the existing snapshot rollback remains available.
