$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
foreach ($port in @(8777, 8766)) {
    $expectedModule = if ($port -eq 8777) { "kdesk.api.account_app" } else { "kdesk.api.kline_app" }
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($process.CommandLine -like "*$expectedModule*") {
            Stop-Process -Id $listener.OwningProcess -Force
        } else {
            throw "Refusing to stop port $port because it is not owned by K_desk_v2 $expectedModule"
        }
    }
}

$workers = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*kdesk.worker.runner*" -and
    $_.CommandLine -like "*--profile prod*"
})
foreach ($worker in $workers) {
    if (Get-Process -Id $worker.ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $worker.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
