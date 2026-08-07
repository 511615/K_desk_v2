---
change_id: 20260807-1230-kln-timeline-001-kline-funds-position-replay
features: ["KLN-TIMELINE-001", "KLN-DB-001", "FIN-HISTORY-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# K-line factual funds and position replay

## Before and after

Database-generated K-line HTML loaded a position enhancement that had no database funds input. It
could display a fallback 10,000 balance, 1:500 leverage and empty balance actions. New charts receive
the routed historical Balance/Credit replay, a funds panel and a funds/order event table. Position
display no longer represents fallback margin/equity ratios as account facts.

## Impact

The existing K-line job route and ports remain unchanged. Its Worker performs an additional
read-only selected-account ledger read and embeds a versioned runtime timeline input into the final
HTML. The K-line enhancement is now versioned inside the repository rather than importing the
untracked `D:\risk` prototype script. No MT, CRM or local ledger data is written.

## Documentation updated

Added KLN-TIMELINE-001; updated KLN-DB-001, FIN-HISTORY-001, data routing, business rules, API and
test authorities.

## Verification

Focused domain/HTML/JavaScript parsing tests, K-line tests and governed Fast/Full verification are
required before deployment.

## Deployment and rollback

Rollback removes the additive timeline argument and injected HTML controls. Existing older output
files remain usable; no schema migration or account data recovery is required.
