---
change_id: 20260724-1712-aut-ea-exact-first-route-classification
features: ["AUT-EA-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Correct EA Comment classification and fallback order

## Before and after

The EA query launched exact and dynamic reads together and treated strict numeric `@` comments as
EA families. Route-like structures could therefore inflate EA account counts and profit, while new
dynamic structures had no durable observation history.

The query now completes exact full-Comment discovery first. Only a successful exact stage with fewer
than two valid routed accounts may use a bounded structural fallback. CPT, numeric `@`, numeric slash
and long account-source structures remain in the EA dialog as `可能是跟单路由`, with
`countedAsEa=false`. Known dynamic EA formats and unseen stable-text/long-number formats receive
normalized templates; non-exact observations are stored in local SQLite. System, stop-out, funding,
origin-reference and contact-only comments are excluded.

## Impact

The existing API path, parameters, group/member keys and profit formulas remain compatible.
Classification fields plus separate EA and route summaries are additive. The legacy dialog and EA
workbook retain route detail but exclude it from EA headline KPIs. The ignored local file
`ea_comment_patterns.sqlite` is created under `ACCOUNT_REGISTRY_DATA_DIR`; remote MT4, MT5 and CRM
access remains read-only.

## Documentation updated

Updated `ea-comment-profit.md`, `account-detail-legacy.md`, `BUSINESS_RULES.md`,
`DATA_AND_ROUTING.md` and `TEST_STRATEGY.md`. The prior immutable record that classified `@` as a
dynamic EA remains unchanged as historical evidence; this record supersedes that business conclusion.

## Verification

Focused fixtures cover all known route and dynamic-EA structures, exact-before-dynamic ordering,
provider-error suppression, local learning, Windows connection closure, exclusions, UI labels,
EA-only summaries and report reconciliation. Full repository verification and live read-only
acceptance results are recorded before deployment. The read-only account `2013674` check classified
`@8@{SOURCE_ID}@7` as a possible copy route, reconstructed 12 accounts and 14,286 Positions, returned
no provider error and kept `eaSummary.groups=0`.
Fast and Full verification passed: 289 Python/legacy tests, 18 frontend tests and the production Vue
build completed successfully.

## Deployment and rollback

No remote schema or platform migration is required. Deployment restarts only the K_desk account
service after tests. Rollback restores the EA grouping module, legacy page template and report
builder; the learned-pattern SQLite file may remain because older code does not read it.

Production account Web was restarted from PID 13100 to PID 18220. K-line PID 16448 was not
restarted. Both readiness checks passed. Browser acceptance on the legacy account page confirmed
the separate EA/route headline, visible `可能是跟单路由` badge, excluded-EA note and complete member
profit table without layout overlap.
