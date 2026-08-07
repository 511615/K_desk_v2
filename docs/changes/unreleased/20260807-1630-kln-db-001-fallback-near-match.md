---
change_id: 20260807-1630-kln-db-fallback-near-match
features: ["KLN-DB-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Accept bounded near-matches from a fallback K-line quote source

## Before and after

The fallback quote gate rejected an otherwise aligned source when a small number of endpoints fell
just outside their M1 envelope. AC GB MT5 account 644101 demonstrated this: 7/10 raw envelope hits,
9/10 endpoint tolerance hits, zero median normalized distance and one 1.17-distance outlier were
rejected.

The gate now accepts this narrow profile only when raw hits are at least 70%, tolerance hits at least
90%, median normalized distance at most 0.25 and maximum normalized distance at most 1.25. The
existing 80%-hit and all-within-tolerance acceptance paths remain unchanged.

## Impact

Only read-only K-line quote calibration changes. No MT4/MT5 Manager operation, account/trade write,
database schema, timeline replay, API path or output data contract changes. Strongly misaligned,
low-hit and distant-outlier fallback sources remain rejected.

## Documentation updated

Updated `KLN-DB-001` and the K-line quote-validation rule in `BUSINESS_RULES.md`.

## Verification

Unit coverage includes the observed 7/10 + 9/10 near-match and a 1.26-distance outlier rejection,
alongside the existing stricter fallback cases. Full K_desk validation and a production read-only
regeneration for account 644101 are required before release.

## Deployment and rollback

Release through the standard production script. Rollback restores the prior quote gate; no source
terminal state or account data is mutated.
