---
change_id: 20260720-1100-fin-live3-cent-fallback
features: ["ACC-DETAIL-001", "ACC-SEARCH-001", "FIN-COMP-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Detect new Live3 cent accounts before daily export

## Before and after

New MT5 Live3 account 241003365 had no `mt5_daily_view` row. K_desk therefore treated its raw USC
money as unscaled unknown currency and displayed balance, equity, P/L, deposits and same-name totals
at 100 times their USD value. Currency resolution now falls back to the read-only
`mt5_users_view.Group` when daily currency is unavailable and recognizes delimiter-bounded `Cent`
or `USC` segments.

## Impact

Account search metadata, legacy account detail metrics, finance panels, high-frequency exposure and
same-name account totals for MT4/MT5 cent groups. Platform money is scaled by `0.01`; price, lots,
identifiers, timestamps and CRM rebate amounts retain their existing units.

## Documentation updated

`DATA_AND_ROUTING.md`, `BUSINESS_RULES.md`, `TEST_STRATEGY.md` and the three affected feature
documents.

## Verification

Unit tests cover group parsing, MT5 users-view fallback and account-search metadata. Read-only live
validation uses AC schema `sass_crm_ac_mt5_live3` account 241003365 and its same-name accounts.

## Deployment and rollback

No API or database migration. Restart only the account web service after Full verification. Roll
back this code and restart `8777`; local data and remote provider state are unchanged.
