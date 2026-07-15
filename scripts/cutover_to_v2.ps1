param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("CUTOVER-KDESK")]
    [string]$ConfirmCutover
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$BackupDir = Join-Path $Root ("runtime\cutover_backup\" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$LegacyLedger = "D:\risk\K_desk_ai_dev\local_data\problem_account_registry\problematic_accounts.xlsx"

if (-not (Test-Path -LiteralPath $Python)) { throw "v2 runtime missing" }
foreach ($url in @("http://127.0.0.1:8877/health/ready", "http://127.0.0.1:8866/health/ready")) {
    $health = Invoke-RestMethod -Uri $url -TimeoutSec 10
    if (-not $health.ok) { throw "Development acceptance service is not ready: $url" }
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $LegacyLedger -Destination (Join-Path $BackupDir "problematic_accounts.xlsx") -Force
Get-ChildItem -LiteralPath "D:\risk\K_desk_ai_dev" -File -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "\\(outputs|local_data|pydeps|__pycache__)\\" } |
    Get-FileHash -Algorithm SHA256 |
    ConvertTo-Json -Depth 3 |
    Set-Content -LiteralPath (Join-Path $BackupDir "legacy_source_hashes.json") -Encoding utf8

$env:KDESK_V2_ROOT = $Root.Path
$env:KDESK_PROFILE = "prod"
$env:KDESK_RUNTIME_DIR = Join-Path $Root "runtime\prod"
$env:KDESK_ACCOUNT_PORT = "8777"
$env:KDESK_KLINE_PORT = "8766"
$env:KDESK_UI_MODE = "vue"
$env:KDESK_LEGACY_OUTPUT = "D:\risk\output_data"
$mysqlPassword = [Environment]::GetEnvironmentVariable("ACCOUNT_TRADE_MYSQL_PASSWORD", "User")
if ($mysqlPassword) { $env:ACCOUNT_TRADE_MYSQL_PASSWORD = $mysqlPassword }

& $Python -m kdesk.cli import-excel $LegacyLedger
if ($LASTEXITCODE -ne 0) { throw "Final ledger import failed; legacy services remain active" }

foreach ($port in @(8777, 8766)) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($process.CommandLine -notlike "*K_desk_ai_dev*") { throw "Refusing to stop unexpected process on port $port" }
        Stop-Process -Id $listener.OwningProcess -Force
    }
}

Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "kdesk.api.account_app:app", "--host", "127.0.0.1", "--port", "8777", "--workers", "1") -WorkingDirectory $Root -WindowStyle Hidden
Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "kdesk.api.kline_app:app", "--host", "127.0.0.1", "--port", "8766", "--workers", "1") -WorkingDirectory $Root -WindowStyle Hidden
Start-Process -FilePath $Python -ArgumentList @("-m", "kdesk.worker.runner") -WorkingDirectory $Root -WindowStyle Hidden

Start-Sleep -Seconds 3
foreach ($url in @("http://127.0.0.1:8777/health/ready", "http://127.0.0.1:8766/health/ready")) {
    $health = Invoke-RestMethod -Uri $url -TimeoutSec 10
    if (-not $health.ok) { throw "Cutover health check failed; run rollback_to_legacy.ps1 immediately" }
}
Write-Host "K_desk v2 cutover complete. Backup: $BackupDir"
