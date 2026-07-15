$ErrorActionPreference = "Stop"

foreach ($port in @(8877, 8866)) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        $expectedModule = if ($port -eq 8877) { "kdesk.api.account_app" } else { "kdesk.api.kline_app" }
        if ($process.CommandLine -like "*$expectedModule*") {
            Stop-Process -Id $listener.OwningProcess -Force
        } else {
            throw "Refusing to stop port $port because the expected v2 module was not found"
        }
    }
}

$workers = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*K_desk_v2*" -and $_.CommandLine -like "*kdesk.worker.runner*"
}
foreach ($worker in $workers) {
    Stop-Process -Id $worker.ProcessId -Force
}
