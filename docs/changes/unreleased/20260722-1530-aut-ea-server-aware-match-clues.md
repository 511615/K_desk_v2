---
change_id: 20260722-1530-aut-ea-server-aware-match-clues
features: ["AUT-EA-001", "ACC-DETAIL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Make EA matching server-aware and auditable

## Before and after

EA discovery could treat a closing `[tp 4029.00]` Comment shared by unrelated strategies as one EA.
Exact named comments were source-local, MT4 MAGIC was not returned by the group query, and member
rows did not explain why an account was included.

Pure TP/SL/SO exit comments are now excluded. MT5 candidates use the opening `Entry=0` Comment and
ExpertID; MT4 uses COMMENT and MAGIC because MT4 has no Entry field. Same-server members must match
both Comment and identifier. Cross-server exact named members match by Comment. Dynamic numeric
families retain the safer family-plus-ExpertID rule. Every API/UI/Excel member row now lists the
observed identifier and a Chinese match clue; no confidence score is introduced.

## Impact

The endpoint, parameters and existing response fields remain compatible. New response fields are
additive. Exact named discovery issues one bounded read per configured physical source on the same
platform and never performs per-account requests. MT5 uses indexed Comment/opening rows; MT4 remains
bounded by the searched account's observed interval. Remote databases and MT servers remain read-only.

## Documentation updated

`BUSINESS_RULES.md`, `DATA_AND_ROUTING.md`, `PORTS_AND_APIS.md`, `TEST_STRATEGY.md`,
`account-detail-legacy.md` and `ea-comment-profit.md`.

## Verification

Focused regressions cover exit-comment exclusion, same-server ExpertID/MAGIC enforcement,
cross-server Comment clues, dialog columns, workbook clues and reconciliation formulas. Focused
legacy tests passed 122 cases and report tests passed 2 cases. Fast verification passed governance,
compile and Ruff. Full verification passed 230 Python/legacy tests, 11 frontend tests and the
production build. A cold read-only `638111` query completed in 7.5 seconds with no provider error;
production returned only `FXRE+PDE` and `GOLDFORGE`, every member had a match clue and no TP/SL/SO
exit-comment group was present.

## Deployment and rollback

No migration is required. Deployment restarted account service 8777 from PID 15500 to PID 16216;
K-line 8766 remained on PID 14072 and both services stayed ready. Workers were unaffected. Rollback
restores the previous EA query module, page template and report builder. No local or remote data
rollback is required.
