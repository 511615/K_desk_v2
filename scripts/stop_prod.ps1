$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-KDeskSupervisorProcess {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][string]$ExpectedModule
    )

    # `uvicorn --workers` owns the listener worker.  Stopping only that worker
    # lets its parent immediately spawn another process with the old in-memory
    # application, so a release can appear healthy while serving stale code.
    $supervisor = $Process
    while ($supervisor.ParentProcessId) {
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($supervisor.ParentProcessId)" -ErrorAction SilentlyContinue
        if ($null -eq $parent -or $parent.CommandLine -notlike "*$ExpectedModule*") {
            break
        }
        $supervisor = $parent
    }
    return $supervisor
}

foreach ($port in @(8777, 8766)) {
    $expectedModule = if ($port -eq 8777) { "kdesk.api.account_app" } else { "kdesk.api.kline_app" }
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($process.CommandLine -like "*$expectedModule*") {
            $supervisor = Get-KDeskSupervisorProcess -Process $process -ExpectedModule $expectedModule
            Stop-Process -Id $supervisor.ProcessId -Force
            Wait-Process -Id $supervisor.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
            # A parent killed during worker spawn can leave a short-lived
            # listener child behind. It is already verified as the expected
            # K_desk module above, so clear it before returning control to the
            # versioned launcher.
            if (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue) {
                Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        } else {
            $details = [ordered]@{
                Port = $port
                Pid = $listener.OwningProcess
                ProcessName = [string]$process.Name
                ExecutablePath = [string]$process.ExecutablePath
                CommandLine = [string]$process.CommandLine
            } | ConvertTo-Json -Compress
            throw "Refusing to stop port $port because it is not owned by K_desk_v2 $expectedModule. Occupant: $details"
        }
    }
}

$workers = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*kdesk.worker.runner*" -and
    $_.CommandLine -like "*--profile prod*"
})
foreach ($worker in $workers) {
    if (Get-Process -Id $worker.ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $worker.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
