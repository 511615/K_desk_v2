$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Source = "D:\risk\K_desk_ai_dev\local_data\problem_account_registry\problematic_accounts.xlsx"
$ImportDir = Join-Path $Root "runtime\dev\import"
$Target = Join-Path $ImportDir "problematic_accounts.xlsx"

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Production ledger does not exist: $Source"
}
New-Item -ItemType Directory -Force -Path $ImportDir | Out-Null
Copy-Item -LiteralPath $Source -Destination $Target -Force

$hash = Get-FileHash -LiteralPath $Target -Algorithm SHA256
[pscustomobject]@{
    Source = $Source
    Target = $Target
    Bytes = (Get-Item -LiteralPath $Target).Length
    Sha256 = $hash.Hash
}
