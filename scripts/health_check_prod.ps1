$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name = "Account production"; Url = "http://127.0.0.1:8777/health/ready" },
    @{ Name = "K-line production"; Url = "http://127.0.0.1:8766/health/ready" }
)

foreach ($check in $checks) {
    try {
        $response = Invoke-RestMethod -Uri $check.Url -TimeoutSec 10
        [pscustomobject]@{ Name = $check.Name; Ready = $response.ok; Status = $response.status; Url = $check.Url }
    } catch {
        [pscustomobject]@{ Name = $check.Name; Ready = $false; Status = $_.Exception.Message; Url = $check.Url }
    }
}
