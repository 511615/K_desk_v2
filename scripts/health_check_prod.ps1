[CmdletBinding()]
param(
    [switch]$AccountOnly
)

$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name = "Account production"; Url = "http://127.0.0.1:8777/health/ready" }
)

if (-not $AccountOnly) {
    $checks += @{ Name = "K-line production"; Url = "http://127.0.0.1:8766/health/ready" }
}

foreach ($check in $checks) {
    try {
        $response = Invoke-RestMethod -Uri $check.Url -TimeoutSec 10
        [pscustomobject]@{ Name = $check.Name; Ready = $response.ok; Status = $response.status; Url = $check.Url }
    } catch {
        [pscustomobject]@{ Name = $check.Name; Ready = $false; Status = $_.Exception.Message; Url = $check.Url }
    }
}

if (-not $AccountOnly) {
    $expectedPython = (Resolve-Path (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe")).Path
    $processes = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -like "*kdesk.worker.runner*" -and
        $_.CommandLine -like "*--profile prod*" -and $_.ExecutablePath -eq $expectedPython
    })
    foreach ($queue in @("interactive", "discovery")) {
        $count = @($processes | Where-Object { $_.CommandLine -like "*--queue $queue*" }).Count
        [pscustomobject]@{
            Name = "Production $queue worker"
            Ready = $count -gt 0
            Status = if ($count -gt 0) { "$count process(es)" } else { "no worker process" }
            Url = "local process"
        }
    }
}
