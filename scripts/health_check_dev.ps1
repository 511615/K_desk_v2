$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name = "Account v2"; Url = "http://127.0.0.1:8877/health/ready" },
    @{ Name = "K-line v2"; Url = "http://127.0.0.1:8866/health/ready" }
)

foreach ($check in $checks) {
    try {
        $response = Invoke-RestMethod -Uri $check.Url -TimeoutSec 10
        [pscustomobject]@{ Name = $check.Name; Ready = $response.ok; Status = $response.status; Url = $check.Url }
    } catch {
        [pscustomobject]@{ Name = $check.Name; Ready = $false; Status = $_.Exception.Message; Url = $check.Url }
    }
}
