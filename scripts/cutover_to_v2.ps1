param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("CUTOVER-KDESK")]
    [string]$ConfirmCutover
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = Join-Path $Root "runtime\cutover_backup\$Timestamp"
$ProdRuntime = Join-Path $Root "runtime\prod"
$LegacyRoot = "D:\risk\K_desk_ai_dev"
$LegacyLedger = Join-Path $LegacyRoot "local_data\problem_account_registry\problematic_accounts.xlsx"
$LegacyIpDatabase = Join-Path $LegacyRoot "local_data\problem_account_registry\account_login_ips.sqlite"
$LegacyQuickActions = Join-Path $LegacyRoot "local_data\problem_account_registry\quick_actions.json"
$LegacyStart = Join-Path $LegacyRoot "scripts\start_all.ps1"
$StartProd = Join-Path $Root "scripts\start_prod.ps1"
$StopDev = Join-Path $Root "scripts\stop_dev.ps1"
$StopProd = Join-Path $Root "scripts\stop_prod.ps1"

foreach ($required in @($Python, $LegacyLedger, $LegacyStart, $StartProd, $StopDev, $StopProd)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required cutover file is missing: $required" }
}
foreach ($url in @("http://127.0.0.1:8877/health/ready", "http://127.0.0.1:8866/health/ready")) {
    $health = Invoke-RestMethod -Uri $url -TimeoutSec 10
    if (-not $health.ok) { throw "Development acceptance service is not ready: $url" }
}

New-Item -ItemType Directory -Force -Path $BackupDir, $ProdRuntime | Out-Null
Copy-Item -LiteralPath $LegacyLedger -Destination (Join-Path $BackupDir "problematic_accounts.xlsx") -Force
if (Test-Path -LiteralPath $LegacyQuickActions) {
    Copy-Item -LiteralPath $LegacyQuickActions -Destination (Join-Path $BackupDir "quick_actions.json") -Force
}
foreach ($source in @($LegacyIpDatabase, "$LegacyIpDatabase-wal", "$LegacyIpDatabase-shm")) {
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $BackupDir (Split-Path -Leaf $source)) -Force
    }
}
foreach ($name in @("kdesk.sqlite", "kdesk.sqlite-wal", "kdesk.sqlite-shm", "account_login_ips.sqlite", "account_login_ips.sqlite-wal", "account_login_ips.sqlite-shm")) {
    $source = Join-Path $ProdRuntime $name
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $BackupDir "v2_before_$name") -Force
    }
}

$artifactRoot = "D:\risk\output_data"
if (Test-Path -LiteralPath $artifactRoot) {
    Get-ChildItem -LiteralPath $artifactRoot -File -Recurse -ErrorAction SilentlyContinue |
        Select-Object FullName, Length, @{Name = "LastWriteTime"; Expression = { $_.LastWriteTime.ToString("s") }} |
        ConvertTo-Json -Depth 3 |
        Set-Content -LiteralPath (Join-Path $BackupDir "artifact_manifest.json") -Encoding utf8
}
Get-ChildItem -LiteralPath $LegacyRoot -File -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "\\(outputs|local_data|pydeps|__pycache__)\\" } |
    Get-FileHash -Algorithm SHA256 |
    ConvertTo-Json -Depth 3 |
    Set-Content -LiteralPath (Join-Path $BackupDir "legacy_source_hashes.json") -Encoding utf8

$env:KDESK_V2_ROOT = $Root
$env:KDESK_PROFILE = "prod"
$env:KDESK_RUNTIME_DIR = $ProdRuntime
$env:KDESK_DATABASE = Join-Path $ProdRuntime "kdesk.sqlite"
$env:KDESK_QUEUE_DATABASE = Join-Path $ProdRuntime "jobs.sqlite"
$env:KDESK_ARTIFACT_DIR = Join-Path $ProdRuntime "artifacts"
$env:KDESK_UPLOAD_DIR = Join-Path $ProdRuntime "uploads"
$env:KDESK_LOG_DIR = Join-Path $ProdRuntime "logs"
$env:KDESK_BOOTSTRAP_XLSX = Join-Path $ProdRuntime "import\problematic_accounts.xlsx"
$env:KDESK_LEGACY_TRADE_DATABASE = "D:\risk\output_data\account_trade_lookup\trades.sqlite"
$env:KDESK_ACCOUNT_PORT = "8777"
$env:KDESK_KLINE_PORT = "8766"
$env:KDESK_UI_MODE = "vue"
$env:KDESK_LEGACY_OUTPUT = "D:\risk\output_data"

$legacyStopped = $false
try {
    foreach ($port in @(8777, 8766)) {
        $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        foreach ($listener in $listeners) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
            if ($process.CommandLine -notlike "*$LegacyRoot*") {
                throw "Refusing to stop unexpected process on port ${port}: $($process.CommandLine)"
            }
            Stop-Process -Id $listener.OwningProcess -Force
        }
    }
    $legacyStopped = $true

    Start-Sleep -Milliseconds 800
    Copy-Item -LiteralPath $LegacyLedger -Destination (Join-Path $BackupDir "problematic_accounts_final.xlsx") -Force
    $prodCompat = Join-Path $ProdRuntime "legacy_compat"
    New-Item -ItemType Directory -Force -Path $prodCompat | Out-Null
    if (Test-Path -LiteralPath $LegacyQuickActions) {
        Copy-Item -LiteralPath $LegacyQuickActions -Destination (Join-Path $prodCompat "quick_actions.json") -Force
    }
    foreach ($suffix in @("", "-wal", "-shm")) {
        $source = "$LegacyIpDatabase$suffix"
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination "$ProdRuntime\account_login_ips.sqlite$suffix" -Force
        }
    }

    & $Python -m kdesk.cli import-excel $LegacyLedger
    if ($LASTEXITCODE -ne 0) { throw "Final ledger import failed" }

    & $StopDev
    & $StartProd
    & (Join-Path $Root "scripts\health_check_prod.ps1") | Tee-Object -Variable healthResults
    if (@($healthResults | Where-Object { -not $_.Ready }).Count -gt 0) {
        throw "Production health check failed"
    }

    $commit = (git -C $Root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to read production Git commit" }
    [pscustomobject]@{
        CutoverAt = (Get-Date).ToString("s")
        Commit = $commit
        BackupDirectory = $BackupDir
        AccountUrl = "http://127.0.0.1:8777"
        KlineUrl = "http://127.0.0.1:8766"
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $ProdRuntime "cutover.json") -Encoding utf8
} catch {
    $failure = $_
    try { & $StopProd } catch { Write-Warning "Could not stop partially started v2 production service: $($_.Exception.Message)" }
    if ($legacyStopped) {
        Start-Process -FilePath "pwsh" -ArgumentList @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $LegacyStart) -WindowStyle Hidden
    }
    throw $failure
}

Write-Host "K_desk v2 cutover complete. Backup: $BackupDir"
