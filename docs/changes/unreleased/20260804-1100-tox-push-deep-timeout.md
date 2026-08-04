---
change_id: 20260804-1100-tox-push-deep-timeout
features: ["TOX-PUSH-001", "JOB-RECOVERY-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Bound platform push deep checks

## Before and after

One slow account deep check could wait indefinitely on read-only historical, synchronization or Tick
analysis. Because deep checks were serial, the complete platform discovery job then showed no new
progress and held the discovery worker.

Each deep candidate now runs in a separate child process with explicit stage messages, 10-second
heartbeats and a 300-second execution ceiling. A timed-out candidate is recorded as recoverable
unavailable evidence while later candidates continue. Push-discovery jobs also retain one automatic
Worker-restart recovery attempt.

## Impact

The existing push-discovery API and result rows remain compatible. Additive job events identify the
candidate, stage and elapsed seconds. No remote database, MT4 or MT5 state is modified.

## Documentation updated

Updated the current-state documents for market-pushing detection and persistent job progress and
recovery. Generated feature-registry and OpenAPI artifacts remain compatible because no public
endpoint schema changed.

## Verification

Unit tests verify complete stage reporting, bounded timeout configuration and child termination on a
hung candidate. The governed fast and full verification suites are required before deployment.

## Deployment and rollback

Restart the production discovery worker after deploying the script. Rolling back the script restores
the prior serial behavior; SQLite job data and completed result artifacts remain compatible.
