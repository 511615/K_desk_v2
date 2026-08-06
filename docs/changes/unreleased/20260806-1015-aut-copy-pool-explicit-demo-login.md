---
change_id: 20260806-1015-aut-copy-pool-explicit-demo-login
features: ["AUT-POOL-001"]
change_type: bug-fix
title: Select and pin the explicitly approved Demo Login during Producer startup
status: unreleased
compatibility: compatible
---

The governed copy-pool launcher now passes the approved Demo Login to the Producer. MT5
initialization may select that saved account on `ACCMGlobal-Demo` before the existing server,
trade-mode, hedging and identity checks run. This prevents a portable terminal left on another
account from blocking startup while preserving the fail-closed Live-account boundary.
The adapter requires three consecutive approved identity samples during the terminal's asynchronous
reconnect so a transient Demo sample followed by a Live sample cannot pass startup.

## Before and after

Previously the Producer only accepted whichever account was active when MT5 IPC initialized. A
terminal left on Live was rejected, while an external pre-start switch to Demo could be followed by
another initialization that disabled AutoTrading. The Producer now performs the one approved account
selection itself and pins the verified identity for all later samples.

## Safety and compatibility

No password is accepted, logged or persisted; account selection relies on the portable terminal's
saved Demo session. Omitting `--demo-login` retains the prior fail-closed behavior. A failed login,
wrong server, non-Demo trade mode, non-hedging account or later identity change remains a hard stop.
This change does not touch MT4/MT5 Manager, the read-only databases, the 8777 API, pool membership or
source-to-Demo Ticket ownership.

## Impact

Producer startup and deployment operations change; pool selection, public APIs, read-only routing
and trade sizing do not. The explicit Login parameter is backward-compatible because omitting it
retains the previous connected-account validation behavior.

## Documentation updated

- `docs/features/automation/dynamic-copy-pool-monitor.md`
- `docs/OPERATIONS.md`

## Deployment and rollback

Restart the single Producer without `-ForceRebuild` so it restores the completed v10 same-day pool.
After the Producer has selected the Demo account, enable AutoTrading once in that terminal and use
the Producer status snapshot as the identity/authorization authority. Rollback is stopping the
Producer and restoring the prior launcher and MT5 adapter revision.

## Verification

- Unit tests cover explicit Demo selection, preserved no-parameter fail-closed behavior, login
failure and post-login identity mismatch.
- The successful-login fixture includes a Demo-to-Live-to-Demo transition and must wait for the
  final Demo identity to stabilize.
- PowerShell parser, focused Producer tests, Fast verification and Full verification are required
  before deployment.
