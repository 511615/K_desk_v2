$checks = @(
    @{ Name = "Account Registry AI Dev"; Url = "http://127.0.0.1:8777/api/accounts"; Port = 8777 },
    @{ Name = "Trade K-line Web AI Dev"; Url = "http://127.0.0.1:8766/"; Port = 8766 }
)

foreach ($check in $checks) {
    $listener = Get-NetTCPConnection -LocalPort $check.Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listener) {
        Write-Host "$($check.Name): port $($check.Port) is not listening"
        continue
    }
    try {
        $response = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 10
        Write-Host "$($check.Name): HTTP $($response.StatusCode)"
    } catch {
        Write-Host "$($check.Name): ERROR $($_.Exception.Message)"
    }
}
