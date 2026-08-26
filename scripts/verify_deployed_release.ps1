[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedGitSha,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$ExpectedVersion,
    [switch]$AccountOnly
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$meta = Invoke-RestMethod -Uri 'http://127.0.0.1:8777/api/meta' -TimeoutSec 15
if (-not $meta.ok) { throw 'Account API metadata is not healthy.' }
if (-not ([string]$ExpectedGitSha).StartsWith([string]$meta.gitSha)) { throw "Deployed Git SHA mismatch: expected prefix of $ExpectedGitSha, got $($meta.gitSha)." }
if ([string]$meta.version -ne $ExpectedVersion) { throw "Deployed version mismatch: expected $ExpectedVersion, got $($meta.version)." }
if ([IO.Path]::GetFullPath([string]$meta.sourceRoot) -ne [IO.Path]::GetFullPath($root)) { throw "Deployed source root mismatch: $($meta.sourceRoot)" }
if ([string]$meta.branch -ne 'main') { throw "Deployed branch is not main: $($meta.branch)" }
if ([string]$meta.profile -ne 'prod') { throw "Deployed profile is not prod: $($meta.profile)" }

$focus = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8777/kuzu-risk' -TimeoutSec 15
if (-not $focus.Content.Contains('data-graph-type="focus-force"')) { throw 'Default /kuzu-risk is not the focus-force workspace.' }
$galaxy = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8777/kuzu-risk?graph_type=galaxy' -TimeoutSec 15
if (-not $galaxy.Content.Contains('Kuzu 关联风险扩散')) { throw 'Explicit galaxy compatibility route is unavailable.' }

$health = @(& (Join-Path $root 'scripts\health_check_prod.ps1') -AccountOnly:$AccountOnly)
if (@($health | Where-Object { -not $_.Ready }).Count -gt 0) { throw 'Production readiness acceptance failed.' }
$pnpm = Get-Command pnpm -ErrorAction Stop
$previousE2eBaseUrl = $env:KDESK_E2E_BASE_URL
try {
    $env:KDESK_E2E_BASE_URL = 'http://127.0.0.1:8777'
    Push-Location -LiteralPath (Join-Path $root 'frontend')
    & $pnpm.Source exec playwright test e2e/relationship-galaxy.spec.ts
    if ($LASTEXITCODE -ne 0) { throw "Deployed Galaxy relationship E2E failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
    $env:KDESK_E2E_BASE_URL = $previousE2eBaseUrl
}
Write-Output "Deployment verified: $($meta.version) $($meta.gitSha) focus-force default, galaxy compatibility."
