param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("ROLLBACK-KDESK")]
    [string]$ConfirmRollback
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$V2Python = Join-Path $Root ".venv\Scripts\python.exe"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ProdRuntime = Join-Path $Root "runtime\prod"
$Export = Join-Path $ProdRuntime "rollback\problematic_accounts_$Timestamp.xlsx"
$LegacyRoot = "D:\risk\K_desk_ai_dev"
$LegacyLedger = Join-Path $LegacyRoot "local_data\problem_account_registry\problematic_accounts.xlsx"
$LegacyIpDatabase = Join-Path $LegacyRoot "local_data\problem_account_registry\account_login_ips.sqlite"
$LegacyStart = Join-Path $LegacyRoot "scripts\start_all.ps1"

foreach ($required in @($V2Python, $LegacyLedger, $LegacyStart)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required rollback file is missing: $required" }
}

$env:KDESK_PROFILE = "prod"
$env:KDESK_V2_ROOT = $Root
$env:KDESK_RUNTIME_DIR = $ProdRuntime
& (Join-Path $Root "scripts\stop_prod.ps1")

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Export) | Out-Null
& $V2Python -m kdesk.cli export-excel $Export
if ($LASTEXITCODE -ne 0) { throw "Failed to export v2 ledger before rollback" }

$ledgerBackup = "$LegacyLedger.before_v2_rollback_$Timestamp.bak"
Copy-Item -LiteralPath $LegacyLedger -Destination $ledgerBackup -Force
Copy-Item -LiteralPath $Export -Destination $LegacyLedger -Force

foreach ($suffix in @("", "-wal", "-shm")) {
    $source = "$ProdRuntime\account_login_ips.sqlite$suffix"
    $target = "$LegacyIpDatabase$suffix"
    if (Test-Path -LiteralPath $source) {
        if (Test-Path -LiteralPath $target) {
            Copy-Item -LiteralPath $target -Destination "$target.before_v2_rollback_$Timestamp.bak" -Force
        }
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}

Start-Process -FilePath "pwsh" -ArgumentList @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $LegacyStart) -WindowStyle Hidden
Start-Sleep -Seconds 4
foreach ($url in @("http://127.0.0.1:8777/", "http://127.0.0.1:8766/")) {
    $response = Invoke-WebRequest -Uri $url -TimeoutSec 15 -UseBasicParsing
    if ($response.StatusCode -ne 200) { throw "Legacy rollback health check failed: $url" }
}
Write-Host "Legacy rollback complete. Ledger backup: $ledgerBackup"
