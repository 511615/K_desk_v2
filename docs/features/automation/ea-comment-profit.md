---
feature_id: AUT-EA-001
title: EA comment group profit
module: automation
status: active
apis: ["GET /api/accounts/by-login/{login}/ea-comment-profit", "GET /api/accounts/by-login/{login}/ea-report.xlsx"]
code: ["legacy/apps/problem_account_registry/ea_comment_group.py", "legacy/apps/problem_account_registry/app.py", "src/kdesk/api/account_app.py", "src/kdesk/infrastructure/automation_reports.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py", "tests/test_api.py", "tests/test_automation_reports.py"]
depends_on: ["ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-24
---

# EA comment group profit

## Purpose and user entry

The EA query next to copy query finds accounts using the same opening EA Comment and compares their
profit and costs. Same-server members must also match MT5 ExpertID or MT4 MAGIC; cross-server exact
named Comments remain comparable without requiring the platform-local identifier.
The same dialog also retains structurally identified copy-route comments for investigation, labelled
`可能是跟单路由`; they are evidence rows, not EA conclusions.
When an MT5 account has EA execution evidence but no usable opening Comment, a separate same-server
fallback may identify a repeated full-ExpertID execution sequence. This is also investigative route
evidence and never an EA-family conclusion.

## UI and behavior

Groups list EA identity, database/server, accounts, profitable/losing counts, orders, lots and
profit components. Dynamic groups may contain AC and DBG members in one table; every member carries
its own database, platform and server, and account links retain that route.
Every member also lists its observed ExpertID/MAGIC values and a Chinese match clue that states
whether the row matched by same-server Comment plus identifier or by cross-server Comment.
Every EA group is an independent native disclosure section. Groups start expanded; selecting the
group header collapses or expands only that group without issuing another request or changing the
page-local payload cache.
The successful result is cached in the current page by normalized filters, so closing and reopening
the dialog performs no new request. Explicit refresh, filter changes and page reload invalidate it;
failed requests are removed from cache and may be retried.
The query dialog provides one-click Excel export with an EA group summary, database/server-aware
account detail and definitions/errors. Current-account rows are highlighted and every detail row
contains an auditable net-profit reconciliation formula.
The dialog headline and workbook EA KPIs aggregate only groups with `countedAsEa=true`. Route-like
groups remain expandable with their own member profit, order and cost detail and are visibly marked
as excluded from the EA summary.
Long ExpertID sequences are compacted to eight samples plus the complete count in the page table;
the API and workbook retain the complete observed identifier list.

## API contract

The JSON endpoint returns `detected`, normalized comment groups, members, totals and limitations.
It additively exposes group `expertId` and `matchRule`, plus member `expertIds`, `matchClue` and
`matchClues` fields.
Classification fields are additive: `classification`, `classificationLabel`, `countedAsEa`,
`normalizedTemplate`, `stablePrefix`, `classificationEvidence` and `classificationSource`.
`eaSummary` excludes possible copy routes; `possibleCopyRouteSummary` reports them separately.
No-comment sequence groups additively expose `signatureType=expert-sequence`, `sharedExpertIds` and
an `expertSequence` object containing the enforced minimum shared count, overlap threshold, time
tolerance and full-group shared count.
The additive `.xlsx` endpoint accepts the same account source filters and returns a no-store workbook.

## Data, routing and read-only constraints

The selected source identifies opening-Comment seeds. Every seed first performs an exact full-Comment
read across configured physical sources on the same platform. MT5 uses only opening deals (`Entry=0`)
and the Comment index; MT4 uses a bounded observed interval because COMMENT and MAGIC are not
independently indexed. Same-server exact candidates match Comment and ExpertID/MAGIC; cross-server
exact candidates match Comment. Dynamic fallback starts only when all exact providers completed
successfully and fewer than two valid routed accounts remain for that seed. Provider failure is
reported and never converted into a dynamic fallback.

Fallback uses a bounded stable-prefix read and validates every candidate against the complete
normalized template before MT5 Position or MT4 ticket reconstruction. The local ignored SQLite file
`ea_comment_patterns.sqlite` records learned templates, evidence, rule version, observation count
and first/last seen time. Built-in system exclusions cannot be learned over; a stored manual rule has
priority over an automatically learned classification. Remote MT/CRM sources remain read-only.
High-cardinality numeric prefixes split adaptively by the next identifier digit; a shard that still
cannot be completed at the minimum depth fails explicitly instead of returning a truncated group.

The no-comment fallback is MT5 and same-logical-server only. It considers at most the latest 200
eligible events inside 31 days and queries by complete non-zero ExpertID plus a bounded opening-time
window. A peer must share at least five complete IDs, match at least 80% in both directions, match
symbol and buy/sell direction within two seconds, and span at least three distinct opening times and
60 seconds. Candidate accounts are CRM-route validated. Prefix similarity is never evidence; any
candidate or account-read safety-limit breach returns an explicit error and no group.

## Business rules and units

Platform/system events, strong close/stop-out markers, balance/deposit/withdrawal/credit rows,
origin references, generic channel text and pure contact comments are excluded. Net profit includes
costs. Mixed comments retain the meaningful strategy text after contact tokens are removed.

`CPT-SS#<id>`, `CPT #<id>`, `@route@source@route`, `channel/channel/source` and long
`account-source` pairs are possible copy routes. They are grouped by structural template but never
counted as EA. Dynamic EA templates include order references (`B1:<id>`, `Name{<id>}`), instance
fields (`RST_RESTART_*_<id>`, `DCA_*_<id>`), `CID=<id>` and strategy level labels such as
`BuyOrder#3`, `BR01`, `SR02`, Grid or Layer numbers. A previously unseen comment with stable text
and a long changing numeric field receives a deterministic fingerprint and is saved to the learned
registry.
Blank opening Comments are not learned as Comment templates. A qualifying complete-ExpertID sequence
is labelled `可能是跟单路由`, has `countedAsEa=false`, and is excluded from every EA headline KPI.
The group header's current-account orders, volume, profit and time range are taken from the same
complete reconstructed member used by the detail row, so rows with a missing exported ExpertID do
not create conflicting totals inside one result.

## Loading, empty and failure behavior

No valid EA/route Comment and no qualifying no-comment sequence returns empty groups. An exact provider failure returns an explicit
partial-query error and suppresses fallback for the affected platform. Query limitations are explicit
in both the page and report; a valid empty query still downloads an explicit empty workbook.

## Code and dependencies

EA grouping is isolated in `ea_comment_group.py` and exposed through the compatibility API.

## Tests and acceptance

Tests cover all listed route and dynamic-EA templates, unknown-format learning, system/contact
exclusions, exact-before-dynamic ordering, provider-error suppression, same-server identifier
enforcement, cross-server evidence, MT4 MAGIC, AC index shards, member totals, UI labels and workbook
EA-only KPIs. DBG CN MT5 account `2013674` remains the route-format regression: its `@8@...@7`
structure must be displayed as `可能是跟单路由`, must not contribute to `eaSummary`, and must retain
database/server-aware members and profit detail when structural fallback finds peers.
The 2026-07-24 live read-only result contained 12 routed accounts and 14,286 reconstructed Positions,
with no provider error and zero contribution to `eaSummary`.
DBG CN MT5 account `2014201` is the no-comment sequence regression. The live read-only result must
identify accounts `2014201`, `2014202`, `2014137` and `2014195` through complete ExpertID/time/symbol/
direction agreement, label the result `可能是跟单路由`, return no provider error and keep
`eaSummary.groups=0`. Tests reject same-prefix-only IDs, fewer than five shared IDs, one-time batches,
wrong direction and less than 80% bilateral overlap.

## Compatibility and deprecation

Existing routes, parameters, group/member totals and profit formulas remain compatible. All new
classification and summary fields are additive.
