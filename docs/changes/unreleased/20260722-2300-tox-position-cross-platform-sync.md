---
change_id: 20260722-2300-tox-position-cross-platform-sync
features: ["TOX-POSITION-001", "TOX-POSITION-SCAN-001"]
change_type: correction
status: unreleased
compatibility: compatible
---

# Require cross-platform synchronized opening and closing

## Before and after

Peer accounts were finalized from same-physical-source opening proximity and a discovery result could
fall back to that opening-only candidate hint. Final same-direction and suspected-hedge evidence now
requires the same canonical symbol, a fully closed target and peer position, opening within five seconds
and final closing within five seconds. Deep checks search all configured AC/DBG MT4 and MT5 physical
sources and display the account plus target/peer order identifiers and timing deltas.
Shared physical tables resolve matched logins to their exact CRM logical server. Complete account and
pair totals are retained while detailed pair payloads are capped at 500 per direction.

The ranking and account modal now expose configured leverage, peak lots, estimated margin amount,
margin/equity (higher is fuller) and estimated margin level (lower is fuller). Penetration data gaps,
peer-source failures and skipped unclosed target orders are explicit.

## Correctness and performance

Opening-only proximity remains a cheap indexed candidate-ranking hint but never enters final scoring or
display. Shared physical sources are deduplicated. MT4 reads combine bounded open and close windows;
MT5 reads bounded opening windows and completes candidate positions in batches before verifying closed
volume. Up to four physical sources are read concurrently. All remote statements remain SELECT-only.

## Impact

Existing endpoints, request fields, type IDs, `peerAccounts` and account links remain compatible.
Completed results add margin, coverage and order-match fields. Old job snapshots remain renderable with
their margin values derived from preserved ratios. Their opening-only peer arrays are hidden and labeled
`需重跑` because those snapshots cannot prove synchronized closing.

## Documentation updated

Updated both position-risk feature documents plus the business-rule, data-routing, API and test-strategy
authorities. Regenerated the feature registry and OpenAPI snapshot.

## Verification

Domain, application and infrastructure tests cover open/close boundaries, missing closes, candidate
fallback prohibition, source deduplication and partial failures. Frontend tests and the production build
cover the new evidence labels and tables.

## Deployment and rollback

Restart the account service and both interactive/discovery workers after rebuilding the frontend.
Rollback restores routed-source opening-only peer evidence and removes the additive fields; no database
migration or state rollback is required.
