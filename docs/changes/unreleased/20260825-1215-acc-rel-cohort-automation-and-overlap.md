---
change_id: 20260825-1215-acc-rel-cohort-automation-and-overlap
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Preserve per-account automation evidence and overlapping Galaxy communities

## Before and after

The recursive relationship builder treated membership in an already-read current-LastIP/CID cohort as
permission to pass `include_automation=false` for that account. This skipped EA and Copy evidence even
though the peer can trade differently from its cohort representative. The Galaxy renderer also assigned
each account one canonical score-tree community, so raw LastIP/same-name/IB components that shared an
account could visually collapse into a one-node group.

The builder now deduplicates only the repeated LastIP/CID follow-up. Every score-eligible account keeps
its own EA and Copy evidence query. Galaxy derives relation-family components from all returned evidence
edges; intersecting components remain visible and an account with multiple memberships is not collapsed
into a single aggregate anchor.

## Impact

Relationship scans may make additional bounded EA/Copy reads for eligible LastIP/CID peers. Scores,
thresholds, source routes, APIs, Kuzu projection and all MT/CRM/AC/DBG read-only constraints remain
unchanged. The visual change is presentation-only and additive: it exposes existing evidence without
creating an inferred relation.

## Documentation updated

Updated `ACC-REL-001`, `ACC-REL-003` and data-routing documentation to state the per-account
automation rule, cohort-only deduplication and overlapping community presentation.

## Verification

`tests/test_relationship_risk.py` proves a peer already known through LastIP is still invoked with
automation enabled. `tests/test_api.py` proves the Galaxy page contains the full-edge overlap component
and non-collapse guard. The relationship-risk and API suites pass.

## Deployment and rollback

Promote the verified relationship commit and restart only 8777 through the governed release script.
Rollback restores the previous verified application commit and restarts 8777; no migration or external
state reversal is required.
