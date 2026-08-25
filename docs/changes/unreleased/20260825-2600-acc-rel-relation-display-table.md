---
change_id: 20260825-2600-acc-rel-relation-display-table
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add snapshot-bound relationship display tables

## Before and after

Edge evidence could be read through `relation-detail`, while Galaxy rendered a separate IB rebate
card by parsing its display evidence. Operators could not consistently distinguish one account's
relationship facts from a multi-account statistical summary.

The additive `relation-display` endpoint and shared focus/Galaxy panel now classify a raw edge as
single-account or group scope. The group panel exposes structured relation metrics, separate known,
included and statistic coverage, pagination and original-evidence access. Direct-IB rebate uses the
returned cohort denominator and never presents materialised-member sums as whole-cohort totals.

## Impact

The graph remains unchanged: only same-CRM communities can be collapsed or expanded, no table action
starts new expansion, and a member-row click only highlights the existing account. Remote summary
reads are bounded, routed and read-only. Existing `relation-detail`, graph, account-detail and port
contracts remain available.

## Documentation updated

Updated ACC-REL-001 / ACC-REL-003 current-state documents, API registration, data-routing, business
rules and test strategy with the table scope, coverage and currency rules.

## Verification

Unit/API regressions cover single-vs-group selection, IB coverage, group member paging, invalid edge,
stale snapshot and both renderer contracts. Full governance and release checks remain required before
promotion.

## Deployment and rollback

The change is additive and uses the normal controlled K_desk promotion. Reverting the endpoint and
shared panel restores existing relation-detail behavior without a data migration or remote-state
rollback.
