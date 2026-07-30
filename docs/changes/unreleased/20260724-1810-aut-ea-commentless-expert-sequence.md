---
change_id: 20260724-1810-aut-ea-commentless-expert-sequence
features: ["AUT-EA-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Detect conservative no-comment ExpertID sequences

## Before and after

The account page correctly marked non-zero MT5 ExpertID executions as EA, but the EA query required
an opening Comment seed. Accounts whose opening Comments were empty therefore returned no group even
when several same-server accounts repeated the same complete ExpertIDs and synchronized trades.

The EA query now adds a separate no-comment fallback. It requires at least five complete shared
ExpertIDs, 80% bilateral coverage, matching symbol and direction within two seconds, at least three
distinct opening times and a 60-second span. It never matches a numeric prefix. Qualifying results
are shown as `可能是跟单路由` with `countedAsEa=false` and remain outside EA KPIs.

## Impact

The existing path, parameters and response fields remain compatible. Sequence evidence adds
`signatureType`, `sharedExpertIds` and `expertSequence`. The page compacts long identifier lists to
eight samples and a count while retaining complete API/report evidence. Reads stay on the selected
MT5 logical server, validate CRM routing and remain read-only. No schema or local-data migration is
required.

## Documentation updated

Updated `ea-comment-profit.md`, `BUSINESS_RULES.md`, `DATA_AND_ROUTING.md`, `TEST_STRATEGY.md` and
`PORTS_AND_APIS.md`.

## Verification

Focused tests require complete-ID matching and reject prefix-only similarity, fewer than five IDs,
one-time batches, wrong direction and overlap below 80%. The live read-only DBG CN MT5 account
`2014201` check identified `2014201`, `2014202`, `2014137` and `2014195`, found 49 complete IDs shared
across the reconstructed closed-trade range, returned one possible-route group, no provider error and
zero EA-summary groups. Fast verification passed. Full verification passed with 291 Python/legacy
tests, 18 frontend tests and the production Vue build.

## Deployment and rollback

Deployment restarts only the account Web service on port 8777. Rollback restores the EA grouping
module and legacy page template; no data rollback is needed because the change performs read-only
remote queries and does not learn blank Comments.

Production account Web was restarted and now listens as PID 18484. K-line PID 16448 was not
restarted. Both readiness endpoints returned `status=ready`. Browser acceptance confirmed the
separate route headline, four linked accounts, compact 49-ID display, complete profit table and no
layout overlap.
