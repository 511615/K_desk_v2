---
change_id: 20260810-1500-acc-rel-score-propagated-kuzu
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: addition
status: unreleased
compatibility: compatible
---

# Add threshold-propagated Kuzu relationship investigation

## Before and after

Before, the standalone Kuzu trial rendered a fixed one-to-three-hop fact graph and intentionally
had no risk score. After, the account-detail relationship entry and endpoint recursively obtain
read-only evidence for score-eligible accounts, materialize it into a request-scoped Kuzu projection,
and propagate investigation score without a hop limit. Low-score outer nodes are retained but not
expanded; real account discovery is capped at 100 and reports truncation.

## Impact

The standalone endpoints remain additive, while the account-detail relationship view and endpoint
contract are intentionally replaced. Existing source reads remain read-only; MT5 same-server current
LastIP edges and an optional high-score (`>=30`) Toxic synchronised open/close query are now live.
The only write is a temporary local Kuzu projection removed before response. No AC/DBG/MT/CRM/SQLite
authority is written.

## Documentation updated

The account feature registry, architecture, data/routing, business rule, API and test authorities
now describe the score-propagated local projection and its safety limits.

## Verification

Focused unit/API tests prove recursive account expansion, threshold stopping, evidence-family
de-duplication, same-IP/Toxic ledgers, cycle safety, colour mapping, local Kuzu reopening and invalid
threshold rejection. Fast and Full governed checks are required before handoff.

## Deployment and rollback

Deployment has not been performed: the governed production launcher correctly refuses an uncommitted
main worktree. No persistent local Kuzu graph is created automatically. After a reviewed deployment,
the account page uses an ephemeral request projection and enables Toxic evidence. Roll back by
reverting this change or calling the endpoint without `include_toxic`; no authoritative data requires
restoration.
