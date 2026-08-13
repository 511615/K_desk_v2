[CmdletBinding()]
param(
    [switch]$AccountOnly
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$expectedDatabase = Join-Path $Root "runtime\prod\kdesk.sqlite"

$checks = @(
    @{ Name = "Account production"; Url = "http://127.0.0.1:8777/health/ready" }
)

if (-not $AccountOnly) {
    $checks += @{ Name = "K-line production"; Url = "http://127.0.0.1:8766/health/ready" }
}

foreach ($check in $checks) {
    try {
        $response = Invoke-RestMethod -Uri $check.Url -TimeoutSec 10
        $runtimeDatabase = if ($check.Name -eq "K-line production") { [string]$response.workerQueue } else { [string]$response.database }
        $profileReady = $check.Name -eq "K-line production" -or $response.profile -eq "prod"
        $runtimeReady = $runtimeDatabase -and ([IO.Path]::GetFullPath($runtimeDatabase) -eq [IO.Path]::GetFullPath($expectedDatabase))
        $ready = [bool]$response.ok -and $profileReady -and $runtimeReady
        $status = if ($ready) { $response.status } elseif (-not $profileReady) { "profile is not prod" } elseif (-not $runtimeReady) { "runtime database mismatch: $runtimeDatabase" } else { [string]$response.status }
        [pscustomobject]@{ Name = $check.Name; Ready = $ready; Status = $status; Url = $check.Url }
    } catch {
        [pscustomobject]@{ Name = $check.Name; Ready = $false; Status = $_.Exception.Message; Url = $check.Url }
    }
}

if (-not $AccountOnly) {
    $workerDirectory = Join-Path $Root "runtime\prod\workers"
    $markers = @(Get-ChildItem -LiteralPath $workerDirectory -Filter '*.json' -File -ErrorAction SilentlyContinue | ForEach-Object {
        try { $_ | Get-Content -Raw | ConvertFrom-Json } catch { $null }
    } | Where-Object {
        $_ -and $_.profile -eq 'prod' -and $_.pid -and (Get-Process -Id ([int]$_.pid) -ErrorAction SilentlyContinue)
    })
    foreach ($queue in @("interactive", "discovery")) {
        $count = @($markers | Where-Object { $_.queue -eq $queue }).Count
        [pscustomobject]@{
            Name = "Production $queue worker"
            Ready = $count -gt 0
            Status = if ($count -gt 0) { "$count process(es)" } else { "no worker process" }
            Url = "local process"
        }
    }
}
