---
change_id: 20260811-acc-rel-source-lanes
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Bound timed-out relationship evidence work by source family

## Before and after

Before, every expanded account created a new short-lived executor for its CRM, Copy and EA source
calls. A slow call returned partial coverage after its timeout, but the underlying thread could keep
running. Continuous expansion therefore accumulated slow threads and increased 8777 memory.

After, the relationship network owns one persistent execution lane per evidence family. A timed-out
queued call is cancelled before it starts, while at most one already-running call per source family
can remain. This preserves continued expansion and per-source coverage without allowing a large
current-LastIP cohort to multiply background source work.

## Impact

No endpoint, scoring, source-routing or data contract changes. A temporarily saturated source may be
reported as timed out for an account; other available evidence families and later score-eligible
accounts continue normally. App shutdown closes the local source lanes.

## Documentation updated

Updated ACC-REL-001, ACC-REL-003, architecture, data-routing and test strategy with the source-lane
concurrency boundary.

## Verification

The new regression holds an EA call open across three account builds and verifies that peak running
EA work remains one. Relationship/API regressions and Full governed verification are required.

## Deployment and rollback

Deploy only the verified 8777 account service from `main`. No data migration exists. Roll back by
restarting the previous verified account-service commit.
