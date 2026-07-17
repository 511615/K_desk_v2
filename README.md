# K_desk

K_desk is the production modular risk workbench running on this Windows host. The account service
uses `127.0.0.1:8777`, the K-line service uses `127.0.0.1:8766`, and persistent background workers
process K-line, Toxic and discovery jobs. Account detail URLs continue to render the legacy detail
page through the governed `LegacyBridge` compatibility boundary.

## Maintenance entry point

Read [docs/README.md](docs/README.md) before changing the system. Every feature addition, behavior
change, bug fix, deletion, refactor or UI interaction change must:

1. identify or create a Feature ID;
2. update the feature's current-state document;
3. add an immutable file under `docs/changes/unreleased/`;
4. run `pwsh -File scripts/verify_change.ps1 -Mode Fast` at minimum.

Production startup remains:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File D:\risk\K_desk_v2\scripts\start_prod.ps1
```

Development writes stay under `runtime/dev`. Remote MySQL and MT4/MT5 integrations are read-only.
