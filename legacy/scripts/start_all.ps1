$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = $env:K_DESK_PYTHON
if (-not $Python) {
    $Python = "C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
}

$env:K_DESK_ROOT = $Root
$env:TRADE_KLINE_TOOL_DIR = Join-Path $Root "tools\trade_kline_tool"
$env:ACCOUNT_REGISTRY_PORT = "8777"
$env:TRADE_KLINE_WEB_PORT = "8766"
$env:K_DESK_AI_CONFIG = "D:\risk\api.txt"
if (Test-Path $env:K_DESK_AI_CONFIG) {
    $env:K_DESK_AI_PROVIDER = "openai"
    if (-not $env:K_DESK_AI_MODEL) {
        $env:K_DESK_AI_MODEL = "gpt-5.4-mini"
    }
}
if (-not $env:TRADE_KLINE_OUT_DIR) {
    $legacyOut = "D:\risk\output_data"
    if (Test-Path (Split-Path -Parent $legacyOut)) {
        $env:TRADE_KLINE_OUT_DIR = $legacyOut
    } else {
        $env:TRADE_KLINE_OUT_DIR = Join-Path $Root "outputs\kline"
    }
}
if (-not $env:TRADE_KLINE_PYDEPS) {
    $legacyPydeps = "D:\risk\pydeps"
    if (Test-Path $legacyPydeps) {
        $env:TRADE_KLINE_PYDEPS = $legacyPydeps
    } else {
        $env:TRADE_KLINE_PYDEPS = Join-Path $Root "pydeps"
    }
}
$env:ACCOUNT_REGISTRY_DATA_DIR = Join-Path $Root "local_data\problem_account_registry"
$env:TRADE_KLINE_WEB_URL = "http://127.0.0.1:8766"

New-Item -ItemType Directory -Force -Path $env:TRADE_KLINE_OUT_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:ACCOUNT_REGISTRY_DATA_DIR | Out-Null

function Start-ServiceIfMissing {
    param(
        [int]$Port,
        [string]$App,
        [string]$Log,
        [string]$Err
    )

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listener) {
        Start-Process -FilePath $Python `
            -ArgumentList @($App) `
            -WorkingDirectory $Root `
            -WindowStyle Hidden `
            -RedirectStandardOutput $Log `
            -RedirectStandardError $Err
        Start-Sleep -Seconds 2
    }
}

Start-ServiceIfMissing `
    -Port 8777 `
    -App (Join-Path $Root "apps\problem_account_registry\app.py") `
    -Log (Join-Path $Root "outputs\problem_account_registry.log") `
    -Err (Join-Path $Root "outputs\problem_account_registry.err.log")

Start-ServiceIfMissing `
    -Port 8766 `
    -App (Join-Path $Root "apps\trade_kline_web\app.py") `
    -Log (Join-Path $Root "outputs\trade_kline_web.log") `
    -Err (Join-Path $Root "outputs\trade_kline_web.err.log")

Start-Process "http://127.0.0.1:8777"
Start-Process "http://127.0.0.1:8766"
