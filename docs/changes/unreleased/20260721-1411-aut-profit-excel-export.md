---
change_id: 20260721-1411-aut-profit-excel-export
features: ["AUT-COPY-001", "AUT-FOLLOWER-001", "AUT-EA-001", "ACC-DETAIL-001"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Export copy and EA profit reports

## Before and after

Copy-origin, Signal-group and EA-comment results were visible only inside the account-detail dialogs.
Reviewers had to manually copy account and profit rows before sharing or reconciling results.

Both dialogs now provide one-click Excel export using the current platform/server filters. The copy
workbook contains a consolidated summary, CPT follower detail, CPT source orders, Signal member
profit and definitions/errors. The EA workbook contains group summary, account detail and
definitions/errors. Account IDs are text, profit values are numeric, positive/negative values are
visually distinct, current accounts are highlighted and component-level rows include reconciliation
formulas.

## Impact

Two additive read-only download routes on account service 8777 and two visible buttons on the legacy
account page. Existing JSON paths and fields are unchanged. The export reuses the same copy/EA query
payloads and short-lived process cache, so it cannot introduce a different profit formula.

## Documentation updated

`PORTS_AND_APIS.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md`, `copy-origin-query.md`,
`follower-profit.md` and `ea-comment-profit.md`.

## Verification

Focused tests cover populated and empty workbooks, expected sheets/tables, account text cells,
numeric profit formatting, reconciliation formulas, response media type/filename and UI controls.
The focused report/API selection passed 4 tests, the focused legacy copy/EA selection passed 11
tests and targeted Ruff passed. Fast verification passed. Full verification passed 220 Python and
legacy tests, 11 frontend tests and the production Vue build.

Production acceptance on account 7798437 confirmed that both legacy dialogs expose `导出 Excel`
and reach `报表已导出`. Direct production downloads returned HTTP 200 with the Excel media type,
no-store cache policy and timestamped attachment names; the copy report completed in 588 ms and the
EA report in 20 ms. Both `8777` and `8766` readiness checks remained ready after deployment.

## Deployment and rollback

No schema, queue or data migration. Only account service 8777 was restarted; K-line service 8766
retained its existing process. Rollback removes the two download routes, report builder and UI
buttons; SQLite and all remote read-only sources are unchanged.
