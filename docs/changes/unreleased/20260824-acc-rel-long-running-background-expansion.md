---
change_id: 20260824-acc-rel-long-running-background-expansion
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# ACC-REL long-running background expansion

## Problem

Relationship discovery was already executed behind a single-flight background coordinator, but the
production composition still injected a 30-second request-wide deadline and a six-second evidence-source
timeout. Slow but valid EA/CRM reads could consume the total budget and leave score-eligible accounts
unexpanded even though the UI and account service were still healthy.

## Change

- Removed the request-wide relationship discovery deadline.
- Removed the production child-process lifetime deadline; the disposable process now lives for the
  investigation and is still reclaimed immediately when the investigation completes or fails.
- Increased the per-source hard ceiling to 120 seconds so valid slow reads can finish while a permanently
  stuck adapter remains bounded.
- Kept one background relationship job and one lane per evidence family, preventing slow discovery from
  blocking normal HTTP work or multiplying database workers.
- Added elapsed-time and last-update heartbeat fields to polling snapshots.
- Kept the focus workspace polling for the full background lifetime instead of stopping after 90 seconds.
- Final progress now distinguishes completion from safety-cap truncation and preserves the pending count.

## Before and after

Before, a relationship investigation could stop after 30 seconds even when every discovered account still
met the propagation threshold. After, the background investigation continues until the threshold frontier is
exhausted or an explicit account/projection safety cap is reached.

## Impact

Slow relationship investigations can take longer, as requested, but remain isolated from HTTP handling and
other account functions. The UI receives an elapsed-time heartbeat throughout the task. Database concurrency
does not increase because the existing single-flight coordinator and per-source lanes remain unchanged.

## Documentation updated

Updated the relationship-network and score-propagated-investigation current-state documents plus the system
architecture description of background execution and source hard ceilings.

## Compatibility and safety

No route, request parameter, database query permission or response field was removed. New progress fields
are additive. Existing account/projection caps and read-only database constraints remain in force.

## Verification

Unit and API contract tests cover no global deadline, the 120-second source ceiling, background heartbeat,
unbounded UI polling, no production process lifetime deadline and final progress state. Account `216056`
is the production verification case.

## Deployment and rollback

Promote through dev to main and restart only the account service on port 8777. Rolling back this change
restores the former 30-second total budget and six-second source ceiling.
