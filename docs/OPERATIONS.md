# Operations runbook

## Services

| Process | Production | Development |
| --- | --- | --- |
| Account web | `127.0.0.1:8777` | `127.0.0.1:8877` |
| K-line web | `127.0.0.1:8766` | `127.0.0.1:8866` |
| Workers | interactive and discovery queues | isolated dev queues |

Use `scripts/start_prod.ps1`, `stop_prod.ps1` and `health_check_prod.ps1`. The stop script verifies
port ownership before terminating a process. Production logs are under `runtime/prod/logs` and must
not contain credentials or sensitive account fields.

## Change verification

Run `scripts/verify_change.ps1` with `Fast`, `Full` or `Release`. Full is required before production
deployment. Release additionally requires explicitly enabled read-only contract checks and live
health acceptance.

Install repository hooks once with `scripts/install_git_hooks.ps1`. Pre-commit runs Fast and
pre-push runs Full. `scripts/publish_change.ps1 -Message '<summary>' [-Push]` is the recommended
direct-to-main workflow; it refuses to push when no remote is configured.

## Release sequence

1. Require a clean, recorded worktree and matching `2.x` version metadata.
2. Run Release verification and build the Vue assets.
3. Copy SQLite databases and compatibility workbook to a timestamped local rollback directory.
4. Stop only verified K_desk processes, run Alembic, start web/worker processes.
5. Check both readiness endpoints and representative account/legacy-page contracts.
6. On failure, stop the new processes, restore the snapshot and restart the prior version.

Use `scripts/release_prod.ps1 -Version <VERSION>`. It requires Release verification, creates
consistent SQLite backups with integrity checks, records a manifest, and attempts automatic data
restore/startup if migration or health acceptance fails.

GitHub stores code only. Local release snapshots protect deployment rollback but are not disaster
recovery for disk loss.

## Incident triage

Check readiness, process ownership, latest error logs, SQLite free space/lock state, remote provider
availability and job events in that order. Do not retry remote calls indefinitely. Never use an MT
Manager write operation as a recovery action.
