[CmdletBinding()]
param(
    [switch]$AccountOnly
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Runtime = Join-Path $Root "runtime\prod"
$LogDir = Join-Path $Runtime "logs"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Production runtime is missing. Run scripts\bootstrap_dev.ps1 first."
}

$env:KDESK_V2_ROOT = $Root
$env:KDESK_PROFILE = "prod"
$env:KDESK_RUNTIME_DIR = $Runtime
$env:KDESK_DATABASE = Join-Path $Runtime "kdesk.sqlite"
$env:KDESK_QUEUE_DATABASE = Join-Path $Runtime "jobs.sqlite"
$env:KDESK_ARTIFACT_DIR = Join-Path $Runtime "artifacts"
$env:KDESK_UPLOAD_DIR = Join-Path $Runtime "uploads"
$env:KDESK_LOG_DIR = $LogDir
$env:KDESK_BOOTSTRAP_XLSX = Join-Path $Runtime "import\problematic_accounts.xlsx"
$env:KDESK_LEGACY_TRADE_DATABASE = "D:\risk\output_data\account_trade_lookup\trades.sqlite"
$env:KDESK_ACCOUNT_PORT = "8777"
$env:KDESK_KLINE_PORT = "8766"
$env:KDESK_UI_MODE = "vue"
$env:KDESK_LEGACY_OUTPUT = "D:\risk\output_data"
$env:ACCOUNT_REGISTRY_PORT = "8777"
$env:TRADE_KLINE_WEB_PORT = "8766"
$env:TRADE_KLINE_WEB_URL = "http://127.0.0.1:8766"
$env:TRADE_KLINE_OUT_DIR = Join-Path $Runtime "artifacts"
$env:ACCOUNT_REGISTRY_DATA_DIR = Join-Path $Runtime "legacy_compat"
$env:ACCOUNT_LOGIN_IP_DB_PATH = Join-Path $Runtime "account_login_ips.sqlite"
$mysqlPassword = [Environment]::GetEnvironmentVariable("ACCOUNT_TRADE_MYSQL_PASSWORD", "User")
if (-not $env:ACCOUNT_TRADE_MYSQL_PASSWORD -and $mysqlPassword) {
    $env:ACCOUNT_TRADE_MYSQL_PASSWORD = $mysqlPassword
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

& $Python -m alembic -c (Join-Path $Root "alembic.ini") upgrade head
if ($LASTEXITCODE -ne 0) { throw "Production database migration failed" }

function Start-KDeskProductionProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int]$Port = 0,
        [string]$ExpectedModule = ""
    )
    if ($Port -gt 0) {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -gt 0) {
            foreach ($listener in $listeners) {
                $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
                if (-not $ExpectedModule -or $process.CommandLine -notlike "*$ExpectedModule*") {
                    throw "Port $Port is owned by an unexpected process: $($process.CommandLine)"
                }
            }
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

Start-KDeskProductionProcess -Name "account-web" -Port 8777 -ExpectedModule "kdesk.api.account_app" -Arguments @("-m", "uvicorn", "kdesk.api.account_app:app", "--host", "127.0.0.1", "--port", "8777", "--workers", "1")
if (-not $AccountOnly) {
    Start-KDeskProductionProcess -Name "kline-web" -Port 8766 -ExpectedModule "kdesk.api.kline_app" -Arguments @("-m", "uvicorn", "kdesk.api.kline_app:app", "--host", "127.0.0.1", "--port", "8766", "--workers", "1")

    foreach ($queue in @("interactive", "discovery")) {
        $workers = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -eq "python.exe" -and $_.CommandLine -like "*kdesk.worker.runner*" -and
            $_.CommandLine -like "*--profile prod*" -and $_.CommandLine -like "*--queue $queue*"
        })
        if ($workers.Count -eq 0) {
            Start-KDeskProductionProcess -Name "worker-$queue" -Arguments @("-m", "kdesk.worker.runner", "--profile", "prod", "--queue", $queue)
        }
    }
}

Start-Sleep -Seconds 2
Write-Host "Account production: http://127.0.0.1:8777"
if (-not $AccountOnly) {
    Write-Host "K-line production: http://127.0.0.1:8766"
}
