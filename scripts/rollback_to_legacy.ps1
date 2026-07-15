param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("ROLLBACK-KDESK")]
    [string]$ConfirmRollback
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$V2Python = Join-Path $Root ".venv\Scripts\python.exe"
$Export = Join-Path $Root "runtime\prod\rollback\problematic_accounts.xlsx"
$LegacyLedger = "D:\risk\K_desk_ai_dev\local_data\problem_account_registry\problematic_accounts.xlsx"
$LegacyStart = "D:\risk\K_desk_ai_dev\scripts\start_all.ps1"

if (-not (Test-Path -LiteralPath $V2Python)) { throw "v2 runtime missing" }
if (-not (Test-Path -LiteralPath $LegacyStart)) { throw "legacy start script missing" }

$env:KDESK_PROFILE = "prod"
$env:KDESK_V2_ROOT = $Root.Path
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Export) | Out-Null
& $V2Python -m kdesk.cli export-excel $Export
if ($LASTEXITCODE -ne 0) { throw "Failed to export v2 ledger before rollback" }

$backup = "$LegacyLedger.before_v2_rollback_$(Get-Date -Format 'yyyyMMdd_HHmmss').bak"
Copy-Item -LiteralPath $LegacyLedger -Destination $backup -Force
Copy-Item -LiteralPath $Export -Destination $LegacyLedger -Force

& (Join-Path $Root "scripts\stop_dev.ps1")
Start-Process -FilePath "pwsh" -ArgumentList @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $LegacyStart) -WindowStyle Hidden
Write-Host "Legacy service restart requested. Backup: $backup"
