$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Runtime = Join-Path $Root "runtime\dev"
$LogDir = Join-Path $Runtime "logs"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Development runtime is missing. Run scripts\bootstrap_dev.ps1 first."
}

$env:KDESK_V2_ROOT = $Root.Path
$env:KDESK_PROFILE = "dev"
$env:KDESK_RUNTIME_DIR = $Runtime
$env:KDESK_DATABASE = Join-Path $Runtime "kdesk.sqlite"
$env:KDESK_QUEUE_DATABASE = Join-Path $Runtime "jobs.sqlite"
$env:KDESK_ARTIFACT_DIR = Join-Path $Runtime "artifacts"
$env:KDESK_UPLOAD_DIR = Join-Path $Runtime "uploads"
$env:KDESK_LOG_DIR = $LogDir
$env:KDESK_BOOTSTRAP_XLSX = Join-Path $Runtime "import\problematic_accounts.xlsx"
$env:KDESK_LEGACY_TRADE_DATABASE = "D:\risk\output_data\account_trade_lookup\trades.sqlite"
$env:KDESK_ACCOUNT_PORT = "8877"
$env:KDESK_KLINE_PORT = "8866"
$env:KDESK_UI_MODE = "vue"
$env:KDESK_LEGACY_OUTPUT = "D:\risk\output_data"
$env:ACCOUNT_REGISTRY_PORT = "8877"
$env:TRADE_KLINE_WEB_PORT = "8866"
$env:TRADE_KLINE_WEB_URL = "http://127.0.0.1:8866"
$env:TRADE_KLINE_OUT_DIR = Join-Path $Runtime "artifacts"
$env:ACCOUNT_REGISTRY_DATA_DIR = Join-Path $Runtime "legacy_compat"
$env:ACCOUNT_LOGIN_IP_DB_PATH = Join-Path $Runtime "account_login_ips.sqlite"
$mysqlPassword = [Environment]::GetEnvironmentVariable("ACCOUNT_TRADE_MYSQL_PASSWORD", "User")
if (-not $env:ACCOUNT_TRADE_MYSQL_PASSWORD -and $mysqlPassword) {
    $env:ACCOUNT_TRADE_MYSQL_PASSWORD = $mysqlPassword
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

& $Python -m alembic -c (Join-Path $Root "alembic.ini") upgrade head
if ($LASTEXITCODE -ne 0) { throw "Database migration failed" }

function Start-KDeskProcess {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [int]$Port = 0
    )
    if ($Port -gt 0) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            Write-Host "$Name already listening on port $Port"
            return
        }
    }
    Start-Process -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "$Name.log") `
        -RedirectStandardError (Join-Path $LogDir "$Name.err.log")
}

Start-KDeskProcess -Name "account-web" -Port 8877 -Arguments @("-m", "uvicorn", "kdesk.api.account_app:app", "--host", "127.0.0.1", "--port", "8877", "--workers", "1")
Start-KDeskProcess -Name "kline-web" -Port 8866 -Arguments @("-m", "uvicorn", "kdesk.api.kline_app:app", "--host", "127.0.0.1", "--port", "8866", "--workers", "1")

$worker = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*K_desk_v2*" -and
    $_.CommandLine -like "*kdesk.worker.runner*" -and $_.CommandLine -like "*--profile dev*"
}
if (-not $worker) {
    Start-KDeskProcess -Name "worker" -Arguments @("-m", "kdesk.worker.runner", "--profile", "dev")
}

Start-Sleep -Seconds 2
Write-Host "Account: http://127.0.0.1:8877"
Write-Host "K-line: http://127.0.0.1:8866"
