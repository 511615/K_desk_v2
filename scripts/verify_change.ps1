[CmdletBinding()]
param(
    [ValidateSet('Fast', 'Full', 'Release')]
    [string]$Mode = 'Fast',
    [string]$Base = ''
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
$BundledNode = 'C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin'

if (-not (Get-Command node -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath (Join-Path $BundledNode 'node.exe'))) {
    $env:PATH = "$BundledNode;$env:PATH"
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Python environment is missing. Run scripts\bootstrap_dev.ps1 first.'
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$WorkingDirectory = $Root
    )
    Write-Host "==> $Label"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

$governanceArguments = @('scripts\governance.py', 'validate')
if ($Base) { $governanceArguments += @('--base', $Base) }
Invoke-NativeChecked -FilePath $Python -Arguments $governanceArguments -Label 'Governance and generated contracts'
Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'compileall', '-q', 'src', 'tests', 'scripts\governance.py') -Label 'Python compile'
Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'ruff', 'check', 'src', 'tests', 'scripts\governance.py') -Label 'Ruff'

if ($Mode -in @('Full', 'Release')) {
    Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'pytest') -Label 'Python and legacy tests'
    if (-not $Pnpm) { throw 'pnpm is required for Full and Release verification.' }
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('install', '--frozen-lockfile') -Label 'Frontend locked install' -WorkingDirectory (Join-Path $Root 'frontend')
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('test') -Label 'Frontend tests' -WorkingDirectory (Join-Path $Root 'frontend')
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('build') -Label 'Frontend production build' -WorkingDirectory (Join-Path $Root 'frontend')
}

if ($Mode -eq 'Release') {
    if ($env:KDESK_ENABLE_LIVE_CONTRACTS -ne '1') {
        throw 'Release verification requires KDESK_ENABLE_LIVE_CONTRACTS=1 and the read-only local contract fixture.'
    }
    $fixture = Join-Path $Root 'runtime\prod\contracts\server-matrix.json'
    if (-not (Test-Path -LiteralPath $fixture)) {
        throw "Read-only release contract fixture is missing: $fixture"
    }
    Invoke-NativeChecked -FilePath $Python -Arguments @('scripts\verify_live_matrix.py', '--fixture', $fixture) -Label 'Read-only ten-server contract matrix'
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('exec', 'playwright', 'install', 'chromium') -Label 'Playwright Chromium install' -WorkingDirectory (Join-Path $Root 'frontend')
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('test:e2e') -Label 'Production legacy-page E2E' -WorkingDirectory (Join-Path $Root 'frontend')
    & (Join-Path $Root 'scripts\health_check_prod.ps1') | ForEach-Object {
        if (-not $_.Ready) { throw "Production health check failed: $($_.Name) $($_.Status)" }
    }
}

Write-Host "K_desk $Mode verification passed."
